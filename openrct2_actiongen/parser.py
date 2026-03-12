"""Parse OpenRCT2 C++ source to extract action definitions."""

import re
from dataclasses import dataclass
from pathlib import Path

import tree_sitter_cpp as tscpp
from tree_sitter import Language, Parser

# Matches entries like: { "ridecreate", GameCommand::CreateRide },
_PLUGIN_API_VERSION_RE = re.compile(
    r"kPluginApiVersion\s*=\s*(\d+)"
)

# Matches entries like: { "ridecreate", GameCommand::CreateRide },
_ACTION_NAME_RE = re.compile(
    r'\{\s*"(\w+)"\s*,\s*GameCommand::(\w+)\s*\}'
)

# 2-arg form: visitor.Visit("jsName", _member) or visitor.Visit("jsName", _member.field)
# Matches member declarations like: ride_type_t _rideType{ kRideTypeNull };
# Captures: (type, member_name)
_MEMBER_DECL_RE = re.compile(
    r"^\s+([\w:]+(?:<[\w:,\s]+>)?)\s+(_\w+)\s*(?:\{[^}]*\}|=[^;]+)?\s*;",
    re.MULTILINE,
)

_VISIT_NAMED_RE = re.compile(
    r'visitor\.Visit\(\s*"(\w+)"\s*,\s*(\w+(?:\.\w+)?)\s*\)'
)

# 1-arg form: visitor.Visit(_member) — unnamed coordinate
_VISIT_UNNAMED_RE = re.compile(
    r'visitor\.Visit\(\s*(_\w+)\s*\)'
)


# C++ type → JSON type resolution
_CPP_TO_JSON_TYPE: dict[str, str] = {
    "bool": "boolean",
    "std::string": "string",
}

# Coordinate types → expanded field names (all fields are "number")
COORD_EXPANSIONS: dict[str, list[str]] = {
    "CoordsXY": ["x", "y"],
    "CoordsXYZ": ["x", "y", "z"],
    "CoordsXYZD": ["x", "y", "z", "direction"],
    "MapRange": ["x1", "y1", "x2", "y2"],
}


@dataclass
class ResolvedParam:
    """A fully resolved action parameter."""

    js_name: str
    json_type: str   # "boolean", "number", or "string"
    cpp_type: str    # original C++ type for reference


@dataclass
class VisitCall:
    """A single visitor.Visit() call extracted from AcceptParameters."""

    js_name: str | None  # None for unnamed coordinates
    member: str          # C++ member: "_rideType", "_origin", "_slope.type"


def parse_plugin_api_version(source_root: Path) -> int:
    """Parse kPluginApiVersion from ScriptEngine.h."""
    script_engine_h = source_root / "src" / "openrct2" / "scripting" / "ScriptEngine.h"
    text = script_engine_h.read_text()

    match = _PLUGIN_API_VERSION_RE.search(text)
    if not match:
        raise ValueError("kPluginApiVersion not found in ScriptEngine.h")

    return int(match.group(1))


def parse_action_name_map(source_root: Path) -> dict[str, str]:
    """Parse ActionNameToType map from ScriptEngine.cpp.

    Returns dict mapping JS action name to GameCommand enum name.
    e.g. {"ridecreate": "CreateRide", "trackplace": "PlaceTrack", ...}
    """
    script_engine = source_root / "src" / "openrct2" / "scripting" / "ScriptEngine.cpp"
    text = script_engine.read_text()

    # Find the ActionNameToType block
    start = text.find("ActionNameToType")
    if start == -1:
        raise ValueError("ActionNameToType map not found in ScriptEngine.cpp")

    # Only search from the map declaration to its closing brace
    end = text.find("};", start)
    if end == -1:
        raise ValueError("Could not find end of ActionNameToType map")

    block = text[start:end]
    matches = _ACTION_NAME_RE.findall(block)

    if not matches:
        raise ValueError("No action entries found in ActionNameToType map")

    return {js_name: enum_name for js_name, enum_name in matches}


def extract_visit_calls(body: str) -> list[VisitCall]:
    """Extract visitor.Visit() calls from an AcceptParameters body.

    Returns calls in order of appearance.
    """
    calls: list[VisitCall] = []

    for line in body.splitlines():
        # Try 2-arg (named) first — it's more specific
        m = _VISIT_NAMED_RE.search(line)
        if m:
            calls.append(VisitCall(js_name=m.group(1), member=m.group(2)))
            continue

        # Try 1-arg (unnamed coordinate)
        m = _VISIT_UNNAMED_RE.search(line)
        if m:
            calls.append(VisitCall(js_name=None, member=m.group(1)))

    return calls


def parse_member_types(header_path: Path) -> dict[str, str]:
    """Parse member variable declarations from an Action header file.

    Returns dict mapping member name to C++ type.
    e.g. {"_rideType": "ride_type_t", "_origin": "CoordsXYZD", "_slope": "FootpathSlope"}
    """
    text = header_path.read_text()
    matches = _MEMBER_DECL_RE.findall(text)
    return {member: cpp_type for cpp_type, member in matches}


def resolve_params(
    calls: list[VisitCall], member_types: dict[str, str]
) -> list[ResolvedParam]:
    """Resolve Visit calls + member types into final parameter list.

    Expands coordinate types into individual fields.
    Maps C++ types to JSON types (bool→boolean, string→string, else→number).
    """
    params: list[ResolvedParam] = []

    for call in calls:
        base_member = call.member.split(".")[0]
        cpp_type = member_types.get(base_member, "unknown")

        if call.js_name is None:
            # Unnamed coordinate — expand based on type
            fields = COORD_EXPANSIONS.get(cpp_type)
            if fields is None:
                raise ValueError(
                    f"Unnamed Visit for member {call.member} has "
                    f"unrecognized coordinate type: {cpp_type}"
                )
            for field in fields:
                params.append(ResolvedParam(
                    js_name=field, json_type="number", cpp_type=cpp_type,
                ))
        else:
            # Named parameter — resolve type
            json_type = _cpp_to_json_type(cpp_type)
            params.append(ResolvedParam(
                js_name=call.js_name, json_type=json_type, cpp_type=cpp_type,
            ))

    return params


def _cpp_to_json_type(cpp_type: str) -> str:
    """Map a C++ type to a JSON type."""
    if cpp_type in _CPP_TO_JSON_TYPE:
        return _CPP_TO_JSON_TYPE[cpp_type]
    # Everything else (int32_t, uint8_t, enums, RideId, etc.) is a number
    return "number"


def find_header_for_action(source_root: Path, class_name: str) -> Path | None:
    """Find the .h file matching an action class name."""
    actions_dir = source_root / "src" / "openrct2" / "actions"
    results = list(actions_dir.glob(f"**/{class_name}.h"))
    if results:
        return results[0]
    return None


def _get_parser() -> Parser:
    """Create a tree-sitter C++ parser."""
    parser = Parser(Language(tscpp.language()))
    return parser


def find_accept_parameters_bodies(source_root: Path) -> dict[str, str]:
    """Find AcceptParameters method bodies for all action files.

    Returns dict mapping class name (e.g. "RideCreateAction") to the
    raw text of the AcceptParameters method body.
    """
    parser = _get_parser()
    actions_dir = source_root / "src" / "openrct2" / "actions"
    results: dict[str, str] = {}

    for cpp_file in sorted(actions_dir.glob("**/*Action.cpp")):
        source = cpp_file.read_bytes()
        tree = parser.parse(source)

        body = _extract_accept_parameters_body(tree.root_node, source)
        if body is not None:
            # "RideCreateAction.cpp" -> "RideCreateAction"
            class_name = cpp_file.stem
            results[class_name] = body

    return results


def _extract_accept_parameters_body(root, source: bytes) -> str | None:
    """Walk the tree to find AcceptParameters and return its body text."""
    for node in _walk(root):
        # Look for function_definition nodes
        if node.type != "function_definition":
            continue

        # Check if the declarator contains "AcceptParameters"
        declarator = node.child_by_field_name("declarator")
        if declarator is None:
            continue

        declarator_text = source[declarator.start_byte:declarator.end_byte].decode()
        if "AcceptParameters" not in declarator_text:
            continue

        # Found it — extract the compound_statement (body)
        body = node.child_by_field_name("body")
        if body is None:
            continue

        return source[body.start_byte:body.end_byte].decode()

    return None


def _walk(node):
    """Depth-first walk of all nodes in the tree."""
    yield node
    for child in node.children:
        yield from _walk(child)
