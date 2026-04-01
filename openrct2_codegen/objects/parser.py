"""Parse ride object definitions and ride type descriptors.

Sources:
  - OpenRCT2/objects repo: objects/rct2/ride/*.json → ride object catalog
  - OpenRCT2 C++ source: src/openrct2/ride/rtd/**/*.h → StartTrackPiece per ride type
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path

from openrct2_codegen.objects.ir import ObjectsIR, RideObjectDef, RideTypeDescriptor

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
) -> ObjectsIR:
    """Parse ride objects and footprints into the objects IR.

    Args:
        source_root: Path to OpenRCT2 C++ source (for RTD headers).
        objects_root: Path to OpenRCT2 objects repo root (for ride JSON files).
        version: OpenRCT2 version string.
    """
    ride_objects = _parse_ride_object_jsons(objects_root)
    footprints = _parse_rtd_footprints(source_root)

    return ObjectsIR(
        openrct2_version=version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator_version=pkg_version("openrct2-codegen"),
        ride_objects=ride_objects,
        ride_type_descriptors=footprints,
    )


def _parse_ride_object_jsons(objects_root: Path) -> list[RideObjectDef]:
    """Parse all ride object JSON files from the objects repo.

    Expected path: objects_root/objects/rct2/ride/*.json
    """
    ride_dir = objects_root / "objects" / "rct2" / "ride"
    if not ride_dir.is_dir():
        raise FileNotFoundError(f"Ride objects directory not found: {ride_dir}")

    results: list[RideObjectDef] = []

    for json_path in sorted(ride_dir.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        obj_id = data.get("id")
        properties = data.get("properties", {})
        strings = data.get("strings", {})

        ride_type_raw = properties.get("type")
        if not obj_id or not ride_type_raw:
            continue

        # ride_type can be a string or list — normalize to string (first entry)
        if isinstance(ride_type_raw, list):
            ride_type = ride_type_raw[0]
        else:
            ride_type = ride_type_raw

        # Extract English name, fallback to identifier
        name_strings = strings.get("name", {})
        name = name_strings.get("en-US") or name_strings.get("en-GB") or obj_id

        # category can be a string or list — keep as-is
        category = properties.get("category", "unknown")

        results.append(
            RideObjectDef(
                identifier=obj_id,
                name=name,
                ride_type=ride_type,
                category=category,
            )
        )

    return results


def _parse_height_constants(source_root: Path) -> dict[str, int]:
    """Parse height constants from RideData.h.

    Returns a dict mapping constant name → resolved integer value.
    e.g. {"kDefaultFoodStallHeight": 64, "kDefaultToiletHeight": 32, ...}
    """
    ride_data_h = source_root / "src" / "openrct2" / "ride" / "RideData.h"
    if not ride_data_h.exists():
        return {}

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
        clearance_height = 0
        if heights_match:
            raw = heights_match.group(2)
            if raw.isdigit():
                clearance_height = int(raw)
            elif raw in height_constants:
                clearance_height = height_constants[raw]

        footprints[ride_type_name] = RideTypeDescriptor(
            track_elem=track_elem,
            tiles_x=tiles_x,
            tiles_y=tiles_y,
            clearance_height=clearance_height,
        )

    return footprints
