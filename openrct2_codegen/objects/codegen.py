"""Render Jinja2 templates from an ObjectsIR."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openrct2_codegen.objects.ir import ObjectsIR
from openrct2_codegen.render import make_env

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _name_to_const(name: str) -> str:
    """Convert an object name to a SCREAMING_SNAKE_CASE constant.

    "Merry-Go-Round" → "MERRY_GO_ROUND"
    "3D Cinema" → "_3D_CINEMA"
    "Burger Bar" → "BURGER_BAR"
    "Fried Chicken Stall" → "FRIED_CHICKEN_STALL"
    """
    # Replace hyphens and spaces with underscores, strip non-alphanumeric
    result = re.sub(r"[^a-zA-Z0-9]", "_", name)
    # Collapse multiple underscores
    result = re.sub(r"_+", "_", result).strip("_").upper()
    # Python identifiers can't start with a digit
    if result and result[0].isdigit():
        result = f"_{result}"
    return result


def _dedup_const(const_name: str, used: dict[str, int]) -> str:
    """Return a unique constant name, appending _2, _3, etc. for duplicates."""
    if const_name in used:
        used[const_name] += 1
        return f"{const_name}_{used[const_name]}"
    used[const_name] = 1
    return const_name


# ── Template data classes ────────────────────────────────────────────


@dataclass
class _ObjectTemplateData:
    """Base template data shared by all object types."""

    const_name: str
    identifier: str
    name: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class _RideObjectTemplateData(_ObjectTemplateData):
    """Ride-specific template data (computed fields not in source JSON)."""

    ride_type: str = ""  # resolved from properties["type"] (can be str or list)
    tiles_x: int | None = None  # from RideTypeDescriptor join
    tiles_y: int | None = None
    clearance_height: int | None = None


# ── Preparation functions ────────────────────────────────────────────


def _slug_to_const(identifier: str) -> str:
    """Derive a SCREAMING_SNAKE constant from the last segment of an identifier.

    "rct2.footpath_surface.tarmac_brown" → "TARMAC_BROWN"
    "rct2.footpath_railings.bamboo_black" → "BAMBOO_BLACK"
    """
    slug = identifier.rsplit(".", 1)[-1]
    return slug.upper()


def _prepare_objects(
    ir: ObjectsIR,
    object_type: str,
    *,
    names_from_slug: bool = False,
) -> list[_ObjectTemplateData]:
    """Filter objects of a given type from the IR."""
    results: list[_ObjectTemplateData] = []
    used_names: dict[str, int] = {}

    for obj in ir.objects:
        if obj.object_type != object_type:
            continue

        if names_from_slug:
            const_name = _dedup_const(_slug_to_const(obj.identifier), used_names)
        else:
            const_name = _dedup_const(_name_to_const(obj.name), used_names)

        results.append(
            _ObjectTemplateData(
                const_name=const_name,
                identifier=obj.identifier,
                name=obj.name,
                properties=obj.properties,
            )
        )

    return results


def _prepare_ride_objects(ir: ObjectsIR) -> list[_RideObjectTemplateData]:
    """Filter ride objects from the IR, join with descriptors, prepare template data."""
    descriptors = ir.ride_type_descriptors
    results: list[_RideObjectTemplateData] = []
    used_names: dict[str, int] = {}

    for obj in ir.objects:
        if obj.object_type != "ride":
            continue

        ride_type_raw = obj.properties.get("type")
        if not ride_type_raw:
            continue
        ride_type = (
            ride_type_raw[0] if isinstance(ride_type_raw, list) else ride_type_raw
        )

        const_name = _dedup_const(_name_to_const(obj.name), used_names)
        desc = descriptors.get(ride_type)

        results.append(
            _RideObjectTemplateData(
                const_name=const_name,
                identifier=obj.identifier,
                name=obj.name,
                properties=obj.properties,
                ride_type=ride_type,
                tiles_x=desc.tiles_x if desc else None,
                tiles_y=desc.tiles_y if desc else None,
                clearance_height=desc.clearance_height if desc else None,
            )
        )

    return results


def _group_by_category(
    objects: list[_RideObjectTemplateData], ir: ObjectsIR
) -> dict[str, list[_RideObjectTemplateData]]:
    """Group ride objects by category for namespace classes."""
    categories: dict[str, list[_RideObjectTemplateData]] = {}

    ride_objects = [o for o in ir.objects if o.object_type == "ride"]
    ride_by_id = {o.identifier: o for o in ride_objects}

    for tmpl_data in objects:
        ir_obj = ride_by_id.get(tmpl_data.identifier)
        if not ir_obj:
            continue

        category = ir_obj.properties.get("category", "unknown")
        cats = category if isinstance(category, list) else [category]
        for cat in cats:
            categories.setdefault(cat, []).append(tmpl_data)

    return {
        k: sorted(v, key=lambda o: o.const_name) for k, v in sorted(categories.items())
    }


def _to_screaming_snake(name: str) -> str:
    """Convert lowerCamelCase or PascalCase to SCREAMING_SNAKE_CASE."""
    result = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).upper()
    if result and result[0].isdigit():
        result = f"_{result}"
    return result


_FILTERS = {
    "capitalize": str.capitalize,
    "repr": repr,
    "to_screaming_snake": _to_screaming_snake,
}


def render_template(
    template_name: str,
    ir: ObjectsIR,
    track_group_values: dict[str, int] | None = None,
) -> str:
    """Render an objects codegen template with the given IR.

    Args:
        template_name: Template file name (without .j2).
        ir: The objects IR.
        track_group_values: TrackGroup camelCase name → int value mapping
            (from enums IR). Required for track-groups.ts template.
    """
    j2_file = _TEMPLATES_DIR / f"{template_name}.j2"
    if not j2_file.is_file():
        raise ValueError(f"Unknown template: {template_name!r} (no file at {j2_file})")

    env = make_env(_TEMPLATES_DIR, _FILTERS)
    template = env.get_template(j2_file.name)

    if template_name == "track-groups.ts":
        return _render_track_groups_ts(template, ir, track_group_values or {})

    ride_objects = _prepare_ride_objects(ir)
    categories = _group_by_category(ride_objects, ir)
    footpath_surfaces = _prepare_objects(ir, "footpath_surface", names_from_slug=True)
    footpath_railings = _prepare_objects(ir, "footpath_railings", names_from_slug=True)
    footpath_additions = _prepare_objects(ir, "footpath_item", names_from_slug=True)

    return template.render(
        generator_version=ir.generator_version,
        openrct2_version=ir.openrct2_version,
        objects_version=ir.objects_version,
        generated_at=ir.generated_at,
        objects=ride_objects,
        categories=categories,
        descriptors=ir.ride_type_descriptors,
        track_element_groups=ir.track_element_groups,
        footpath_surfaces=footpath_surfaces,
        footpath_additions=footpath_additions,
        footpath_railings=footpath_railings,
    )


def _render_track_groups_ts(
    template: Any,
    ir: ObjectsIR,
    track_group_values: dict[str, int],
) -> str:
    """Render the track-groups.ts template with int-resolved group data."""
    # Resolve enabledTrackGroups: ride_type → list of TrackGroup ints
    enabled_groups: dict[str, list[int]] = {}
    extra_groups: dict[str, list[int]] = {}
    for rt_name, desc in ir.ride_type_descriptors.items():
        if desc.enabled_track_groups:
            enabled_groups[rt_name] = [
                track_group_values[g]
                for g in desc.enabled_track_groups
                if g in track_group_values
            ]
        if desc.extra_track_groups:
            extra_groups[rt_name] = [
                track_group_values[g]
                for g in desc.extra_track_groups
                if g in track_group_values
            ]

    # Resolve track_element_groups: list of TrackGroup ints
    track_elem_to_group_ints = [
        track_group_values.get(g, -1) for g in ir.track_element_groups
    ]

    # TrackGroup enum as (name, value) pairs
    track_group_enum = sorted(track_group_values.items(), key=lambda x: x[1])

    return template.render(
        generator_version=ir.generator_version,
        openrct2_version=ir.openrct2_version,
        objects_version=ir.objects_version,
        generated_at=ir.generated_at,
        track_group_enum=track_group_enum,
        enabled_groups=enabled_groups,
        extra_groups=extra_groups,
        track_elem_to_group_ints=track_elem_to_group_ints,
    )
