"""Render Jinja2 templates from an ActionsIR."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

from openrct2_codegen.actions.ir import ActionsIR
from openrct2_codegen.enums.ir import EnumsIR
from openrct2_codegen.render import make_env

_TEMPLATES_DIR = Path(__file__).parent / "templates"

CppType = str
ParamName = str
EnumName = str

# Manual overrides for cpp_type names that don't exactly match an enum name.
_CPP_TYPE_TO_ENUM: dict[CppType, EnumName] = {
    "ride_type_t": "RideType",
}

# Overrides that also require a matching parameter name.
# CoordsXYZD expands to (x, y, z, direction) — only `direction` is a Direction enum.
_CPP_TYPE_NAME_TO_ENUM: dict[tuple[CppType, ParamName], EnumName] = {
    ("CoordsXYZD", "direction"): "Direction",
}


def _build_enum_map(enum_names: set[EnumName]) -> dict[CppType, EnumName]:
    """Build a cpp_type → enum name mapping.

    Direct matches (cpp_type == enum name) are discovered automatically.
    Manual overrides in _CPP_TYPE_TO_ENUM are only applied when the target
    enum exists in the provided set.
    """
    mapping: dict[CppType, EnumName] = {}
    for name in enum_names:
        mapping[name] = name
    for cpp_type, enum_name in _CPP_TYPE_TO_ENUM.items():
        if enum_name in enum_names:
            mapping[cpp_type] = enum_name
    return mapping


def _cpp_class_to_method(cpp_class: str) -> str:
    """Convert a C++ action class name to a Python method name.

    RideCreateAction -> ride_create
    BalloonPressAction -> balloon_press
    """
    name = cpp_class.removesuffix("Action")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name).lower()


def _camel_to_snake(name: str) -> str:
    """Convert a camelCase parameter name to snake_case.

    primaryColour -> primary_colour
    rideType -> ride_type
    """
    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name).lower()


_EnumMap = dict[CppType, EnumName]
_NameEnumMap = dict[tuple[CppType, ParamName], EnumName]


def _resolve_enum(param: dict, enum_map: _EnumMap, name_enum_map: _NameEnumMap) -> EnumName | None:
    """Resolve a parameter to an enum name, or None if no match."""
    # Check (cpp_type, name) conditional overrides first.
    enum_name = name_enum_map.get((param["cpp_type"], param["name"]))
    if enum_name is not None:
        return enum_name
    # Then check the simple cpp_type map.
    return enum_map.get(param["cpp_type"])


def _make_py_type_filter(enum_map: _EnumMap, name_enum_map: _NameEnumMap):
    """Create a Jinja2 filter that maps a parameter dict to a Python type string.

    Parameters whose cpp_type resolves to a known enum get that enum name.
    Everything else falls back to ir_type → int/bool/str.
    """
    _ir_fallback = {"number": "int", "boolean": "bool", "string": "str"}

    def _py_type(param: dict) -> str:
        enum_name = _resolve_enum(param, enum_map, name_enum_map)
        if enum_name is not None:
            return enum_name
        return _ir_fallback[param["type"]]

    return _py_type


def render_template(
    template_name: str,
    ir: ActionsIR,
    enums_ir: EnumsIR | None = None,
) -> str:
    """Render an actions codegen template with the given IR.

    When *enums_ir* is provided, action parameters whose C++ type matches a
    known enum are annotated with that enum type instead of plain ``int``.
    """
    j2_file = _TEMPLATES_DIR / f"{template_name}.j2"
    if not j2_file.is_file():
        raise ValueError(f"Unknown template: {template_name!r} (no file at {j2_file})")

    if enums_ir is not None and enums_ir.openrct2_version != ir.openrct2_version:
        warnings.warn(
            f"OpenRCT2 version mismatch: actions IR is {ir.openrct2_version}, "
            f"enums IR is {enums_ir.openrct2_version}. "
            f"Enum types may be inaccurate.",
            stacklevel=2,
        )

    enum_names = set(enums_ir.enums.keys()) if enums_ir else set()
    enum_map = _build_enum_map(enum_names)
    name_enum_map = {k: v for k, v in _CPP_TYPE_NAME_TO_ENUM.items() if v in enum_names}

    # Collect the set of enum names actually used by any action parameter.
    used_enums: set[str] = set()
    for action in ir.actions:
        for p in action.parameters:
            enum_name = _resolve_enum(p.model_dump(), enum_map, name_enum_map)
            if enum_name is not None:
                used_enums.add(enum_name)

    filters = {
        "cpp_class_to_method": _cpp_class_to_method,
        "camel_to_snake": _camel_to_snake,
        "py_type": _make_py_type_filter(enum_map, name_enum_map),
    }

    env = make_env(_TEMPLATES_DIR, filters)
    template = env.get_template(j2_file.name)

    return template.render(
        generator_version=ir.generator_version,
        openrct2_version=ir.openrct2_version,
        api_version=ir.api_version,
        generated_at=ir.generated_at,
        actions=[a.model_dump() for a in ir.actions],
        enum_imports=sorted(used_enums),
    )
