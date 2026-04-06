"""Render Jinja2 templates from an EnumsIR."""

import re
from pathlib import Path

from openrct2_codegen.enums.ir import EnumsIR
from openrct2_codegen.render import make_env

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _to_screaming_snake(name: str) -> str:
    """Convert lowerCamelCase or PascalCase to SCREAMING_SNAKE_CASE.

    spiralRollerCoaster → SPIRAL_ROLLER_COASTER
    TrackColourMain → TRACK_COLOUR_MAIN
    3dCinema → _3D_CINEMA  (Python identifiers can't start with a digit)
    """
    result = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).upper()
    if result[0].isdigit():
        result = f"_{result}"
    return result


_FILTERS = {
    "to_screaming_snake": _to_screaming_snake,
}


def render_template(template_name: str, ir: EnumsIR) -> str:
    """Render an enums codegen template with the given IR."""
    j2_file = _TEMPLATES_DIR / f"{template_name}.j2"
    if not j2_file.is_file():
        raise ValueError(f"Unknown template: {template_name!r} (no file at {j2_file})")

    env = make_env(_TEMPLATES_DIR, _FILTERS)
    template = env.get_template(j2_file.name)

    return template.render(
        generator_version=ir.generator_version,
        openrct2_version=ir.openrct2_version,
        generated_at=ir.generated_at,
        enums={name: edef.model_dump() for name, edef in sorted(ir.enums.items())},
    )
