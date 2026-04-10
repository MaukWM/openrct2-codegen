"""Render Jinja2 templates from an ActionsIR."""

from __future__ import annotations

import re
from pathlib import Path

from openrct2_codegen.actions.ir import ActionsIR
from openrct2_codegen.render import make_env

_TEMPLATES_DIR = Path(__file__).parent / "templates"


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


_IR_TYPE_TO_PY = {"number": "int", "boolean": "bool", "string": "str"}


def _py_type(param: dict) -> str:
    """Map a parameter dict to a Python type annotation string.

    Uses ``enum_type`` from the IR when present, otherwise falls back to
    the basic ir_type → int/bool/str mapping. When ``enum_loose`` is set,
    renders as ``EnumType | int`` to accept sentinel values.
    """
    enum = param.get("enum_type")
    if enum:
        if param.get("enum_loose"):
            return f"{enum} | int"
        return enum
    return _IR_TYPE_TO_PY[param["type"]]


def render_template(template_name: str, ir: ActionsIR) -> str:
    """Render an actions codegen template with the given IR."""
    j2_file = _TEMPLATES_DIR / f"{template_name}.j2"
    if not j2_file.is_file():
        raise ValueError(f"Unknown template: {template_name!r} (no file at {j2_file})")

    # Collect the set of enum names actually used by any action parameter.
    used_enums: set[str] = set()
    for action in ir.actions:
        for p in action.parameters:
            if p.enum_type is not None:
                used_enums.add(p.enum_type)

    filters = {
        "cpp_class_to_method": _cpp_class_to_method,
        "camel_to_snake": _camel_to_snake,
        "py_type": _py_type,
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
