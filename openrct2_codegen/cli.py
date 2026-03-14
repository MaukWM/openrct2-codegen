"""CLI entry point for openrct2-codegen."""

import json
from pathlib import Path

import click

from openrct2_codegen.codegen import render_template
from openrct2_codegen.ir import ActionsIR
from openrct2_codegen.parser import parse_actions
from openrct2_codegen.source import get_dts_path, get_source
from openrct2_codegen.state_parser import parse_state


@click.group()
def main() -> None:
    """Generate action and state bindings from OpenRCT2 source."""


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
    "--actions-out",
    type=click.Path(path_type=Path),
    default=Path("generated/actions.json"),
    show_default=True,
    help="Output path for actions.json IR.",
)
@click.option(
    "--state-out",
    type=click.Path(path_type=Path),
    default=Path("generated/state.json"),
    show_default=True,
    help="Output path for state.json IR.",
)
@click.option("--verbose", is_flag=True, help="Show detailed progress.")
def generate(
    openrct2_version: str | None,
    openrct2_source: Path | None,
    actions_out: Path,
    state_out: Path,
    verbose: bool,
) -> None:
    """Generate actions.json and state.json IRs from OpenRCT2 source."""
    source_root = get_source(version=openrct2_version, local_path=openrct2_source)
    version = openrct2_version or source_root.name

    actions_out.parent.mkdir(parents=True, exist_ok=True)
    state_out.parent.mkdir(parents=True, exist_ok=True)
    click.echo(f"Source: OpenRCT2 {version} at {source_root}")

    # Actions IR
    actions_ir = parse_actions(source_root, version=version)
    click.echo(f"Parsed {len(actions_ir.actions)} actions")
    actions_out.write_text(json.dumps(actions_ir.model_dump(), indent=2) + "\n")
    click.echo(f"actions.json → {actions_out}")

    # State IR
    dts_path = get_dts_path(source_root)
    state_ir = parse_state(dts_path, openrct2_version=version, source_root=source_root)
    click.echo(f"Parsed {len(state_ir.interfaces)} interfaces, {len(state_ir.enums)} enums")
    state_out.write_text(state_ir.model_dump_json(indent=2))
    click.echo(f"state.json  → {state_out}")


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
    default=None,
    help="Output path for rendered file. Defaults to generated/<template>.",
)
def render(
    ir: Path,
    template: str,
    out: Path | None,
) -> None:
    """Render a codegen template from an IR file."""
    out = out or Path("generated") / template
    out.parent.mkdir(parents=True, exist_ok=True)

    actions_ir = ActionsIR.model_validate_json(ir.read_text())
    rendered = render_template(template, actions_ir)
    out.write_text(rendered)
    click.echo(f"{template} → {out}")
