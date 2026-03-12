"""Parse OpenRCT2 C++ source to extract action definitions."""

import re
from pathlib import Path

# Matches entries like: { "ridecreate", GameCommand::CreateRide },
_ACTION_NAME_RE = re.compile(
    r'\{\s*"(\w+)"\s*,\s*GameCommand::(\w+)\s*\}'
)


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
