"""Render Jinja2 templates from an ActionsIR."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from openrct2_actiongen.ir import ActionsIR

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_template(template_name: str, ir: ActionsIR) -> str:
    """Render a codegen template with the given IR.

    template_name: stem of the output file (e.g. "actions.ts").
    Loads templates/{template_name}.j2 and renders it with the IR data.
    """
    j2_file = _TEMPLATES_DIR / f"{template_name}.j2"
    if not j2_file.is_file():
        raise ValueError(f"Unknown template: {template_name!r} (no file at {j2_file})")

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(j2_file.name)

    return template.render(
        generator_version=ir.generator_version,
        openrct2_version=ir.openrct2_version,
        api_version=ir.api_version,
        generated_at=ir.generated_at,
        actions=[a.model_dump() for a in ir.actions],
    )
