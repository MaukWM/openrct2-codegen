"""Render Jinja2 templates from an ObjectsIR."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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


@dataclass
class _RideObjectTemplateData:
    """Pre-processed ride object data for the template."""

    const_name: str
    identifier: str
    name: str
    ride_type: str
    category_repr: str  # Python repr of category (str or list)
    tiles_x: int | None
    tiles_y: int | None
    clearance_height: int | None


def _prepare_ride_objects(ir: ObjectsIR) -> list[_RideObjectTemplateData]:
    """Filter ride objects from the IR, join with descriptors, prepare template data."""
    descriptors = ir.ride_type_descriptors
    results: list[_RideObjectTemplateData] = []

    # Track used const names to handle duplicates
    used_names: dict[str, int] = {}

    for obj in ir.objects:
        if obj.object_type != "ride":
            continue

        ride_type_raw = obj.properties.get("type")
        if not ride_type_raw:
            continue
        # type can be a string or list in the source JSON
        ride_type = (
            ride_type_raw[0] if isinstance(ride_type_raw, list) else ride_type_raw
        )

        const_name = _name_to_const(obj.name)

        # Handle duplicate names (e.g. two "Restroom" objects)
        if const_name in used_names:
            used_names[const_name] += 1
            const_name = f"{const_name}_{used_names[const_name]}"
        else:
            used_names[const_name] = 1

        # Join with descriptor for footprint data
        desc = descriptors.get(ride_type)

        # Format category for Python repr
        category = obj.properties.get("category", "unknown")
        category_repr = repr(category)

        results.append(
            _RideObjectTemplateData(
                const_name=const_name,
                identifier=obj.identifier,
                name=obj.name,
                ride_type=ride_type,
                category_repr=category_repr,
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

    # Build category mapping from the IR
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

    # Sort categories and their contents
    return {
        k: sorted(v, key=lambda o: o.const_name)
        for k, v in sorted(categories.items())
    }


_FILTERS = {
    "capitalize": str.capitalize,
}


def render_template(template_name: str, ir: ObjectsIR) -> str:
    """Render an objects codegen template with the given IR."""
    j2_file = _TEMPLATES_DIR / f"{template_name}.j2"
    if not j2_file.is_file():
        raise ValueError(
            f"Unknown template: {template_name!r} (no file at {j2_file})"
        )

    env = make_env(_TEMPLATES_DIR, _FILTERS)
    template = env.get_template(j2_file.name)

    ride_objects = _prepare_ride_objects(ir)
    categories = _group_by_category(ride_objects, ir)

    return template.render(
        generator_version=ir.generator_version,
        openrct2_version=ir.openrct2_version,
        objects_version=ir.objects_version,
        generated_at=ir.generated_at,
        objects=ride_objects,
        categories=categories,
        descriptors=ir.ride_type_descriptors,
    )
