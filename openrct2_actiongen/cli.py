"""CLI entry point for openrct2-actiongen."""

from pathlib import Path

import click

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
    "--output",
    type=click.Path(path_type=Path),
    default=Path("actions.json"),
    help="Output path for actions.json.",
    show_default=True,
)
@click.option("--verbose", is_flag=True, help="Show detailed progress.")
def generate(
    openrct2_version: str | None,
    openrct2_source: Path | None,
    output: Path,
    verbose: bool,
) -> None:
    """Generate actions.json from OpenRCT2 source."""
    source_root = get_source(version=openrct2_version, local_path=openrct2_source)

    action_files = list(source_root.glob("src/openrct2/actions/**/*Action.cpp"))
    click.echo(f"Source: {source_root}")
    click.echo(f"Found {len(action_files)} action files")
    click.echo(f"Output: {output}")

    # TODO: parse → IR → write actions.json
    click.echo("Parser not yet implemented.")
