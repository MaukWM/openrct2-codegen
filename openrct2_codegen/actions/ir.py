"""IR schema for actions.json — the output of the parser."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

CppType = str
ParamName = str
EnumName = str


class ActionParameter(BaseModel):
    """A single parameter accepted by a game action."""

    name: str
    type: Literal["boolean", "number", "string"]
    cpp_type: str
    enum_type: EnumName | None = None


class Action(BaseModel):
    """A single game action with its full parameter signature."""

    js_name: str         # "ridecreate"
    cpp_class: str       # "RideCreateAction"
    game_command: str    # "CreateRide"
    # Derived from subdirectory name (e.g. "ride", "park", "terraform").
    # Defaults to "general" for pre-v0.4.32 where actions are flat in actions/.
    category: str
    parameters: list[ActionParameter]


class ActionsIR(BaseModel):
    """Top-level IR: the full actions.json schema."""

    openrct2_version: str
    api_version: int
    generated_at: str
    generator_version: str
    actions: list[Action]


# -- Enum enrichment --------------------------------------------------------
#
# Resolves cpp_type (and optionally param name) to a known enum name.
# Called during `generate` after both actions and enums are parsed.

# cpp_type → enum: for types whose name doesn't match the enum exactly.
_CPP_TYPE_TO_ENUM: dict[CppType, EnumName] = {
    "ride_type_t": "RideType",
}

# (cpp_type, param_name) → enum: for types where cpp_type is generic but
# the param name reveals the semantic type.
# - CoordsXYZD expands to (x, y, z, direction) — only `direction` is Direction.
# - staffType is stored as uint8_t but semantically is StaffType.
_CPP_TYPE_NAME_TO_ENUM: dict[tuple[CppType, ParamName], EnumName] = {
    ("CoordsXYZD", "direction"): "Direction",
    ("uint8_t", "staffType"): "StaffType",
}


def enrich_enum_types(actions_ir: ActionsIR, enum_names: set[EnumName]) -> None:
    """Resolve and set ``enum_type`` on every action parameter where possible.

    Mutates *actions_ir* in place. Resolution order:
    1. (cpp_type, param_name) conditional overrides
    2. cpp_type manual overrides (for naming mismatches)
    3. Direct match: cpp_type == enum name
    """
    # Build the lookup: cpp_type → enum (direct matches + manual overrides).
    type_map: dict[CppType, EnumName] = {name: name for name in enum_names}
    for cpp_type, enum_name in _CPP_TYPE_TO_ENUM.items():
        if enum_name in enum_names:
            type_map[cpp_type] = enum_name

    # Build the name-conditional lookup (only for entries whose target enum exists).
    name_map = {k: v for k, v in _CPP_TYPE_NAME_TO_ENUM.items() if v in enum_names}

    for action in actions_ir.actions:
        for p in action.parameters:
            # Priority 1: (cpp_type, name) conditional override.
            resolved = name_map.get((p.cpp_type, p.name))
            if resolved is None:
                # Priority 2+3: cpp_type override or direct match.
                resolved = type_map.get(p.cpp_type)
            p.enum_type = resolved
