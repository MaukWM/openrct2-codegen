"""CLI entry point for openrct2-actiongen."""

import json
from pathlib import Path

import click

from openrct2_actiongen.codegen import render_template
from openrct2_actiongen.ir import ActionsIR
from openrct2_actiongen.parser import parse_actions
from openrct2_actiongen.source import get_source


@click.group()
def main() -> None:
    """Parse OpenRCT2 C++ source to generate action binding definitions."""


@main.command()
@click.option(
    "--openrct2-version",
    type=str,
    default=None,
    help="OpenRCT2 version tag to download (e.g. v0.4.32).",
)
@click.option(
    "--openrct2-source",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to local OpenRCT2 source checkout.",
)
@click.option(
    "--ir",
    type=click.Path(path_type=Path),
    default=Path("actions.json"),
    help="Output path for actions.json IR.",
    show_default=True,
)
@click.option("--verbose", is_flag=True, help="Show detailed progress.")
def generate(
    openrct2_version: str | None,
    openrct2_source: Path | None,
    ir: Path,
    verbose: bool,
) -> None:
    """Generate actions.json IR from OpenRCT2 source."""
    source_root = get_source(version=openrct2_version, local_path=openrct2_source)
    version = openrct2_version or source_root.name

    click.echo(f"Parsing {version} source at {source_root}")
    actions_ir = parse_actions(source_root, version=version)
    click.echo(f"Parsed {len(actions_ir.actions)} actions")

    ir.write_text(json.dumps(actions_ir.model_dump(), indent=2) + "\n")
    click.echo(f"IR written to {ir}")


@main.command()
@click.option(
    "--ir",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to actions.json IR file.",
)
@click.option(
    "--template",
    type=str,
    required=True,
    help="Template to render (e.g. actions.ts).",
)
@click.option(
    "--out",
    type=click.Path(path_type=Path),
    required=True,
    help="Output path for rendered file.",
)
def render(
    ir: Path,
    template: str,
    out: Path,
) -> None:
    """Render a codegen template from an actions.json IR file."""
    actions_ir = ActionsIR.model_validate_json(ir.read_text())
    click.echo(f"Loaded {len(actions_ir.actions)} actions from {ir}")

    rendered = render_template(template, actions_ir)
    out.write_text(rendered)
    click.echo(f"Rendered {template} to {out}")
