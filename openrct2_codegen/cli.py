"""CLI entry point for openrct2-codegen."""

import json
from pathlib import Path

import click

import openrct2_codegen.actions.codegen as actions_codegen
import openrct2_codegen.enums.codegen as enums_codegen
import openrct2_codegen.objects.codegen as objects_codegen
import openrct2_codegen.state.codegen as state_codegen
from openrct2_codegen.actions.ir import ActionsIR, enrich_enum_types
from openrct2_codegen.actions.parser import parse_actions
from openrct2_codegen.enums.ir import EnumsIR
from openrct2_codegen.enums.parser import parse_enums
from openrct2_codegen.objects.parser import parse_objects
from openrct2_codegen.source import (
    get_dts_path,
    get_objects_source,
    get_pinned_objects_version,
    get_source,
)
from openrct2_codegen.state.ir import StateIR
from openrct2_codegen.state.parser import parse_state


_DEFAULT_ACTIONS_IR = Path("generated/actions.json")
_DEFAULT_STATE_IR = Path("generated/state.json")
_DEFAULT_ENUMS_IR = Path("generated/enums.json")
_DEFAULT_OBJECTS_IR = Path("generated/objects.json")


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
    default=_DEFAULT_ACTIONS_IR,
    show_default=True,
    help="Output path for actions.json IR.",
)
@click.option(
    "--state-out",
    type=click.Path(path_type=Path),
    default=_DEFAULT_STATE_IR,
    show_default=True,
    help="Output path for state.json IR.",
)
@click.option(
    "--enums-out",
    type=click.Path(path_type=Path),
    default=_DEFAULT_ENUMS_IR,
    show_default=True,
    help="Output path for enums.json IR.",
)
@click.option(
    "--objects-out",
    type=click.Path(path_type=Path),
    default=_DEFAULT_OBJECTS_IR,
    show_default=True,
    help="Output path for objects.json IR.",
)
@click.option("--verbose", is_flag=True, help="Show detailed progress.")
def generate(
    openrct2_version: str | None,
    openrct2_source: Path | None,
    actions_out: Path,
    state_out: Path,
    enums_out: Path,
    objects_out: Path,
    verbose: bool,
) -> None:
    """Generate actions.json, state.json, enums.json, and objects.json IRs from OpenRCT2 source."""
    source_root = get_source(version=openrct2_version, local_path=openrct2_source)
    version = openrct2_version or source_root.name

    actions_out.parent.mkdir(parents=True, exist_ok=True)
    state_out.parent.mkdir(parents=True, exist_ok=True)
    enums_out.parent.mkdir(parents=True, exist_ok=True)
    click.echo(f"Source: OpenRCT2 {version} at {source_root}")

    # Enums IR (first — needed for enriching actions)
    enums_ir = parse_enums(source_root, version=version)
    click.echo(f"Parsed {len(enums_ir.enums)} enum types")
    enums_out.write_text(enums_ir.model_dump_json(indent=2))
    click.echo(f"enums.json  → {enums_out}")

    # Actions IR (enriched with enum types from enums IR)
    actions_ir = parse_actions(source_root, version=version)
    enrich_enum_types(actions_ir, set(enums_ir.enums.keys()))
    click.echo(f"Parsed {len(actions_ir.actions)} actions")
    actions_out.write_text(json.dumps(actions_ir.model_dump(), indent=2) + "\n")
    click.echo(f"actions.json → {actions_out}")

    # State IR
    dts_path = get_dts_path(source_root)
    state_ir = parse_state(dts_path, openrct2_version=version, source_root=source_root)
    click.echo(
        f"Parsed {len(state_ir.interfaces)} interfaces, {len(state_ir.enums)} enums"
    )
    state_out.write_text(state_ir.model_dump_json(indent=2))
    click.echo(f"state.json  → {state_out}")

    # Objects IR (ride object catalog + flat ride footprints)
    objects_out.parent.mkdir(parents=True, exist_ok=True)
    obj_version = get_pinned_objects_version(source_root)
    click.echo(f"Objects version pinned by assets.json: {obj_version}")
    objects_root = get_objects_source(obj_version)
    objects_ir = parse_objects(
        source_root, objects_root, version=version, objects_version=obj_version
    )
    click.echo(
        f"Parsed {len(objects_ir.ride_objects)} ride objects, "
        f"{len(objects_ir.ride_type_descriptors)} ride type descriptors"
    )
    objects_out.write_text(objects_ir.model_dump_json(indent=2))
    click.echo(f"objects.json → {objects_out}")


_ACTIONS_TEMPLATES = {"actions.ts", "actions.py"}
_STATE_TEMPLATES = {"state.ts", "state.py"}
_ENUMS_TEMPLATES = {"enums.py"}
_OBJECTS_TEMPLATES = {"objects.py"}


@main.command()
@click.option(
    "--template",
    type=click.Choice(
        sorted(
            _ACTIONS_TEMPLATES
            | _STATE_TEMPLATES
            | _ENUMS_TEMPLATES
            | _OBJECTS_TEMPLATES
        )
    ),
    required=True,
    help="Template to render.",
)
@click.option(
    "--ir",
    type=click.Path(path_type=Path),
    default=None,
    help=(
        f"Path to IR file. Defaults to {_DEFAULT_ACTIONS_IR} for actions templates, "
        f"{_DEFAULT_STATE_IR} for state templates, {_DEFAULT_ENUMS_IR} for enums templates, "
        f"{_DEFAULT_OBJECTS_IR} for objects templates."
    ),
)
@click.option(
    "--out",
    type=click.Path(path_type=Path),
    default=None,
    help="Output path. Defaults to generated/<template>.",
)
def render(
    template: str,
    ir: Path | None,
    out: Path | None,
) -> None:
    """Render a codegen template from an IR file."""
    out = out or Path("generated") / template
    out.parent.mkdir(parents=True, exist_ok=True)

    if template in _ENUMS_TEMPLATES:
        ir = ir or _DEFAULT_ENUMS_IR
        if not ir.exists():
            raise click.ClickException(
                f"IR file not found: {ir} — run 'generate' first."
            )
        enums_ir = EnumsIR.model_validate_json(ir.read_text())
        rendered = enums_codegen.render_template(template, enums_ir)
    elif template in _STATE_TEMPLATES:
        ir = ir or _DEFAULT_STATE_IR
        if not ir.exists():
            raise click.ClickException(
                f"IR file not found: {ir} — run 'generate' first."
            )
        state_ir = StateIR.model_validate_json(ir.read_text())
        rendered = state_codegen.render_template(template, state_ir)
    elif template in _OBJECTS_TEMPLATES:
        ir = ir or _DEFAULT_OBJECTS_IR
        if not ir.exists():
            raise click.ClickException(
                f"IR file not found: {ir} — run 'generate' first."
            )
        from openrct2_codegen.objects.ir import ObjectsIR

        objects_ir = ObjectsIR.model_validate_json(ir.read_text())
        rendered = objects_codegen.render_template(template, objects_ir)
    else:
        ir = ir or _DEFAULT_ACTIONS_IR
        if not ir.exists():
            raise click.ClickException(
                f"IR file not found: {ir} — run 'generate' first."
            )
        actions_ir = ActionsIR.model_validate_json(ir.read_text())
        rendered = actions_codegen.render_template(template, actions_ir)

    out.write_text(rendered)
    click.echo(f"{template} → {out}")
