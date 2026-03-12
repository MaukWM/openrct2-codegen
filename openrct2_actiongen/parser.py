"""Parse OpenRCT2 C++ source to extract action definitions."""

import re
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
