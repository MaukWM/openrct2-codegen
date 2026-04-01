"""Parse object definitions and ride type descriptors.

Sources:
  - OpenRCT2/objects repo: objects/rct2/**/*.json → full object catalog
  - OpenRCT2 C++ source: src/openrct2/ride/rtd/**/*.h → StartTrackPiece per ride type
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path

from openrct2_codegen.objects.ir import (
    ObjectDef,
    ObjectsIR,
    RideTypeDescriptor,
)

# Regex to extract StartTrackPiece from RTD headers.
# Matches: .StartTrackPiece = TrackElemType::flatTrack3x3,
_START_TRACK_RE = re.compile(r"\.StartTrackPiece\s*=\s*TrackElemType::(\w+)")

# Regex to extract .Name from RTD headers.
# Matches: .Name = "merry_go_round",
_NAME_RE = re.compile(r'\.Name\s*=\s*"([^"]+)"')

# Regex to extract footprint dimensions from flatTrack names.
# Matches: flatTrack3x3, flatTrack1x4A, flatTrack2x2, etc.
_FLAT_TRACK_RE = re.compile(r"flatTrack(\d+)x(\d+)([A-Z])?")

# Regex to extract Heights from RTD headers.
# Matches: .Heights = { 12, 64, 3, 2, },
# Groups: MaxHeight, ClearanceHeight, VehicleZOffset, PlatformHeight
_HEIGHTS_RE = re.compile(
    r"\.Heights\s*=\s*\{\s*(\w+)\s*,\s*(\w+)\s*,\s*(-?\w+)\s*,\s*(\w+)"
)

# Regex to parse height constants from RideData.h.
# Matches: constexpr uint8_t kDefaultFoodStallHeight = 8 * kCoordsZStep;
_HEIGHT_CONST_RE = re.compile(
    r"constexpr\s+\w+\s+(\w+)\s*=\s*(\d+)\s*\*\s*kCoordsZStep\s*;"
)

# kCoordsZStep is always 8 in OpenRCT2.
# Source: src/openrct2/world/MapLimits.h
_COORDS_Z_STEP = 8


def parse_objects(
    source_root: Path,
    objects_root: Path,
    version: str,
    objects_version: str,
) -> ObjectsIR:
    """Parse all objects and ride type descriptors into the objects IR.

    Args:
        source_root: Path to OpenRCT2 C++ source (for RTD headers).
        objects_root: Path to OpenRCT2 objects repo root (for object JSON files).
        version: OpenRCT2 version string.
        objects_version: OpenRCT2/objects repo version string.
    """
    all_objects = _parse_all_objects(objects_root)
    descriptors = _parse_rtd_footprints(source_root)

    return ObjectsIR(
        openrct2_version=version,
        objects_version=objects_version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator_version=pkg_version("openrct2-codegen"),
        objects=all_objects,
        ride_type_descriptors=descriptors,
    )


def _parse_all_objects(objects_root: Path) -> list[ObjectDef]:
    """Parse all object JSON files from the objects repo."""
    base_dir = objects_root / "objects" / "rct2"
    if not base_dir.is_dir():
        raise FileNotFoundError(f"Objects base directory not found: {base_dir}")

    results: list[ObjectDef] = []

    for type_dir in sorted(base_dir.iterdir()):
        if not type_dir.is_dir():
            continue
        obj_type = type_dir.name

        for json_path in sorted(type_dir.rglob("*.json")):
            obj = _parse_object_json(json_path, obj_type)
            if obj is not None:
                results.append(obj)

    return results


def _parse_object_json(json_path: Path, obj_type: str) -> ObjectDef | None:
    """Parse a single object JSON file."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"Warning: failed to parse {json_path}: {e}")
        return None

    obj_id = data.get("id")
    if not obj_id:
        print(f"Warning: no 'id' field in {json_path}")
        return None

    raw_properties = data.get("properties", {})
    strings = data.get("strings", {})

    # Extract English name, fallback to identifier
    name_strings = strings.get("name", {})
    name = name_strings.get("en-US") or name_strings.get("en-GB") or obj_id

    # Extract other English strings (description, capacity, etc.)
    extra_strings: dict[str, str] = {}
    for str_key, str_langs in strings.items():
        if str_key == "name":
            continue
        if not isinstance(str_langs, dict):
            print(f"Warning: unexpected string format for '{str_key}' in {obj_id}")
            continue
        val = str_langs.get("en-US") or str_langs.get("en-GB")
        if val:
            extra_strings[str_key] = val

    # Capture all non-complex properties (skip dicts like cars, nested objects)
    properties: dict = {}
    for key, value in raw_properties.items():
        if isinstance(value, (str, int, float, bool, list)):
            properties[key] = value

    # Merge extra strings into properties
    if extra_strings:
        properties["strings"] = extra_strings

    return ObjectDef(
        identifier=obj_id,
        object_type=obj_type,
        name=name,
        properties=properties,
    )


def _parse_height_constants(source_root: Path) -> dict[str, int]:
    """Parse height constants from RideData.h.

    Returns a dict mapping constant name → resolved integer value.
    e.g. {"kDefaultFoodStallHeight": 64, "kDefaultToiletHeight": 32, ...}
    """
    ride_data_h = source_root / "src" / "openrct2" / "ride" / "RideData.h"
    if not ride_data_h.exists():
        raise FileNotFoundError(f"RideData.h not found at {ride_data_h}")

    content = ride_data_h.read_text(encoding="utf-8", errors="replace")
    constants: dict[str, int] = {}
    for match in _HEIGHT_CONST_RE.finditer(content):
        name = match.group(1)
        multiplier = int(match.group(2))
        constants[name] = multiplier * _COORDS_Z_STEP
    return constants


def _parse_rtd_footprints(source_root: Path) -> dict[str, RideTypeDescriptor]:
    """Parse RTD headers for flat ride footprints.

    Scans src/openrct2/ride/rtd/**/*.h for .Name and .StartTrackPiece fields.
    Only includes ride types with flatTrack* start pieces.
    """
    rtd_dir = source_root / "src" / "openrct2" / "ride" / "rtd"
    if not rtd_dir.is_dir():
        raise FileNotFoundError(f"RTD directory not found: {rtd_dir}")

    height_constants = _parse_height_constants(source_root)
    footprints: dict[str, RideTypeDescriptor] = {}

    for header_path in sorted(rtd_dir.rglob("*.h")):
        content = header_path.read_text(encoding="utf-8", errors="replace")

        name_match = _NAME_RE.search(content)
        track_match = _START_TRACK_RE.search(content)

        if not name_match or not track_match:
            continue

        ride_type_name = name_match.group(1)
        track_elem = track_match.group(1)

        # Only include flat track types
        flat_match = _FLAT_TRACK_RE.match(track_elem)
        if not flat_match:
            continue

        tiles_x = int(flat_match.group(1))
        tiles_y = int(flat_match.group(2))

        # Extract ClearanceHeight from .Heights = { MaxHeight, ClearanceHeight, ... }
        heights_match = _HEIGHTS_RE.search(content)
        if not heights_match:
            print(
                f"Warning: no .Heights found in {header_path.name} for {ride_type_name}"
            )
            continue

        raw = heights_match.group(2)
        if raw.isdigit():
            clearance_height = int(raw)
        elif raw in height_constants:
            clearance_height = height_constants[raw]
        else:
            print(
                f"Warning: unknown height constant '{raw}' in {header_path.name} for {ride_type_name}"
            )
            continue

        footprints[ride_type_name] = RideTypeDescriptor(
            track_elem=track_elem,
            tiles_x=tiles_x,
            tiles_y=tiles_y,
            clearance_height=clearance_height,
        )

    return footprints
