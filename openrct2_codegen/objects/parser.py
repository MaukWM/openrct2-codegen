"""Parse object definitions and ride type descriptors.

Sources:
  - OpenRCT2/objects repo: objects/rct2/**/*.json → full object catalog
  - OpenRCT2 C++ source: src/openrct2/ride/rtd/**/*.h → RTD per ride type
  - OpenRCT2 C++ source: src/openrct2/ride/TrackData.cpp + ted/TED.*.h → element→group
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

# ---------------------------------------------------------------------------
# Regex patterns — RTD headers
# ---------------------------------------------------------------------------

# Matches: .StartTrackPiece = TrackElemType::flatTrack3x3,
_START_TRACK_RE = re.compile(r"\.StartTrackPiece\s*=\s*TrackElemType::(\w+)")

# Matches: .Name = "merry_go_round",
_NAME_RE = re.compile(r'\.Name\s*=\s*"([^"]+)"')

# Matches: flatTrack3x3, flatTrack1x4A, flatTrack2x2, etc.
_FLAT_TRACK_RE = re.compile(r"flatTrack(\d+)x(\d+)([A-Z])?")

# Matches: .Heights = { 12, 64, 3, 2, },
_HEIGHTS_RE = re.compile(
    r"\.Heights\s*=\s*\{\s*(\w+)\s*,\s*(\w+)\s*,\s*(-?\w+)\s*,\s*(\w+)"
)

# Matches: constexpr uint8_t kDefaultFoodStallHeight = 8 * kCoordsZStep;
_HEIGHT_CONST_RE = re.compile(
    r"constexpr\s+\w+\s+(\w+)\s*=\s*(\d+)\s*\*\s*kCoordsZStep\s*;"
)

# Matches: constexpr RideTypeDescriptor FlyingRollerCoasterRTD =
_RTD_DECL_RE = re.compile(
    r"constexpr\s+RideTypeDescriptor\s+(\w+)\s*="
)

# Matches: .enabledTrackGroups = { TrackGroup::flat, ... }
# or:      .enabledTrackGroups = {  }  (empty)
_ENABLED_GROUPS_RE = re.compile(
    r"\.enabledTrackGroups\s*=\s*\{([^}]*)\}"
)

# Matches: .extraTrackGroups = { TrackGroup::liftHillSteep, ... }
_EXTRA_GROUPS_RE = re.compile(
    r"\.extraTrackGroups\s*=\s*\{([^}]*)\}"
)

# Matches: TrackGroup::flatRollBanking
_TRACK_GROUP_REF_RE = re.compile(r"TrackGroup::(\w+)")

# kCoordsZStep is always 8 in OpenRCT2.
_COORDS_Z_STEP = 8

# ---------------------------------------------------------------------------
# Regex patterns — TrackData.cpp / TED element descriptors
# ---------------------------------------------------------------------------

# Matches entries in the kTrackElementDescriptors array: kTEDFlat, kTEDUp25, etc.
_TED_REF_RE = re.compile(r"\b(kTED\w+)\b")

# Matches a TED definition and extracts its TrackGroup from .definition.
# .definition = { TrackGroup::slope, TrackPitch::..., ... }
_TED_DEF_RE = re.compile(
    r"constexpr\s+auto\s+(kTED\w+)\s*=\s*TrackElementDescriptor\s*\{"
    r".*?\.definition\s*=\s*\{\s*TrackGroup::(\w+)",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def parse_objects(
    source_root: Path,
    objects_root: Path,
    version: str,
    objects_version: str,
    track_elem_values: dict[str, int],
) -> ObjectsIR:
    """Parse all objects and ride type descriptors into the objects IR.

    Args:
        source_root: Path to OpenRCT2 C++ source (for RTD headers).
        objects_root: Path to OpenRCT2 objects repo root (for object JSON files).
        version: OpenRCT2 version string.
        objects_version: OpenRCT2/objects repo version string.
        track_elem_values: TrackElemType enum name → int value mapping
            (from enums IR). Used to resolve track_elem_value on descriptors.
    """
    all_objects = _parse_all_objects(objects_root)
    descriptors = _parse_rtd_headers(source_root, track_elem_values)
    track_element_groups = _parse_track_element_groups(source_root, track_elem_values)

    return ObjectsIR(
        openrct2_version=version,
        objects_version=objects_version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator_version=pkg_version("openrct2-codegen"),
        objects=all_objects,
        ride_type_descriptors=descriptors,
        track_element_groups=track_element_groups,
    )


# ---------------------------------------------------------------------------
# Object JSON parsing (unchanged)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Height constants
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# RTD header parsing — track groups + flat ride footprints
# ---------------------------------------------------------------------------


def _extract_track_groups(body: str) -> list[str]:
    """Extract TrackGroup names from a brace-delimited list body.

    Input: " TrackGroup::flat, TrackGroup::straight, TrackGroup::slope "
    Output: ["flat", "straight", "slope"]
    """
    return [m.group(1) for m in _TRACK_GROUP_REF_RE.finditer(body)]


def _parse_rtd_headers(
    source_root: Path, track_elem_values: dict[str, int]
) -> dict[str, RideTypeDescriptor]:
    """Parse all RTD headers for track group data and flat ride footprints.

    Scans src/openrct2/ride/rtd/**/*.h for all RideTypeDescriptor structs.
    Extracts enabledTrackGroups/extraTrackGroups for all ride types, and
    additionally extracts flat ride footprint data for flatTrack* types.
    """
    rtd_dir = source_root / "src" / "openrct2" / "ride" / "rtd"
    if not rtd_dir.is_dir():
        raise FileNotFoundError(f"RTD directory not found: {rtd_dir}")

    height_constants = _parse_height_constants(source_root)
    descriptors: dict[str, RideTypeDescriptor] = {}

    for header_path in sorted(rtd_dir.rglob("*.h")):
        content = header_path.read_text(encoding="utf-8", errors="replace")

        # Find all RTD declarations in this file (most files have 1, a few have 2)
        rtd_starts = list(_RTD_DECL_RE.finditer(content))
        if not rtd_starts:
            continue

        for i, decl_match in enumerate(rtd_starts):
            # Extract the region for this RTD (up to next RTD or end of file)
            start = decl_match.start()
            end = (
                rtd_starts[i + 1].start()
                if i + 1 < len(rtd_starts)
                else len(content)
            )
            block = content[start:end]

            # .Name is required — skip RTD blocks without it
            name_match = _NAME_RE.search(block)
            if not name_match:
                continue
            ride_type_name = name_match.group(1)

            # Extract track groups from the first occurrence in the block
            # (which is inside .TrackPaintFunctions, before .InvertedTrackPaintFunctions)
            enabled_match = _ENABLED_GROUPS_RE.search(block)
            enabled = (
                _extract_track_groups(enabled_match.group(1))
                if enabled_match
                else []
            )
            extra_match = _EXTRA_GROUPS_RE.search(block)
            extra = (
                _extract_track_groups(extra_match.group(1)) if extra_match else []
            )

            # Check for flat ride footprint data
            track_match = _START_TRACK_RE.search(block)
            track_elem = track_match.group(1) if track_match else None
            flat_match = _FLAT_TRACK_RE.match(track_elem) if track_elem else None

            track_elem_str: str | None = None
            track_elem_value: int | None = None
            tiles_x: int | None = None
            tiles_y: int | None = None
            clearance_height: int | None = None

            if flat_match:
                track_elem_str = track_elem
                tiles_x = int(flat_match.group(1))
                tiles_y = int(flat_match.group(2))

                heights_match = _HEIGHTS_RE.search(block)
                if heights_match:
                    raw = heights_match.group(2)
                    if raw.isdigit():
                        clearance_height = int(raw)
                    elif raw in height_constants:
                        clearance_height = height_constants[raw]
                    else:
                        print(
                            f"Warning: unknown height constant '{raw}' "
                            f"in {header_path.name} for {ride_type_name}"
                        )

                track_elem_value = track_elem_values.get(track_elem)  # type: ignore[arg-type]
                if track_elem_value is None:
                    print(
                        f"Warning: TrackElemType '{track_elem}' not found in enums "
                        f"for ride type '{ride_type_name}'"
                    )

            descriptors[ride_type_name] = RideTypeDescriptor(
                enabled_track_groups=enabled,
                extra_track_groups=extra,
                track_elem=track_elem_str,
                track_elem_value=track_elem_value,
                tiles_x=tiles_x,
                tiles_y=tiles_y,
                clearance_height=clearance_height,
            )

    return descriptors


# ---------------------------------------------------------------------------
# TrackData.cpp parsing — TrackElemType → TrackGroup mapping
# ---------------------------------------------------------------------------


def _parse_track_element_groups(
    source_root: Path, track_elem_values: dict[str, int]
) -> list[str]:
    """Parse TrackData.cpp + TED.*.h to build TrackElemType → TrackGroup mapping.

    Returns a list where index = TrackElemType int value, value = TrackGroup name
    (camelCase, matching the enum IR names).

    Approach:
    1. Read kTrackElementDescriptors array from TrackData.cpp → ordered kTED* names
    2. Read all TED source files → map kTED* name → TrackGroup from .definition
    3. Combine: array position (= TrackElemType value) → TrackGroup name
    """
    track_data_path = source_root / "src" / "openrct2" / "ride" / "TrackData.cpp"
    ted_dir = source_root / "src" / "openrct2" / "ride" / "ted"

    if not track_data_path.exists():
        raise FileNotFoundError(f"TrackData.cpp not found: {track_data_path}")

    track_data_src = track_data_path.read_text(encoding="utf-8", errors="replace")

    # Step 1: Extract the ordered kTED* names from kTrackElementDescriptors array
    array_match = re.search(
        r"kTrackElementDescriptors\s*=\s*std::to_array<TrackElementDescriptor>\(\{(.*?)\}\);",
        track_data_src,
        re.DOTALL,
    )
    if not array_match:
        raise ValueError("kTrackElementDescriptors array not found in TrackData.cpp")

    array_body = array_match.group(1)
    ordered_teds = _TED_REF_RE.findall(array_body)

    # Step 2: Build kTED* name → TrackGroup mapping from all source files
    # Concatenate TrackData.cpp + all TED.*.h files
    all_ted_source = track_data_src
    if ted_dir.is_dir():
        for ted_file in sorted(ted_dir.glob("TED.*.h")):
            all_ted_source += "\n" + ted_file.read_text(
                encoding="utf-8", errors="replace"
            )

    ted_to_group: dict[str, str] = {}
    for m in _TED_DEF_RE.finditer(all_ted_source):
        ted_name = m.group(1)
        group_name = m.group(2)
        ted_to_group[ted_name] = group_name

    # Step 3: Map array position → TrackGroup name
    result: list[str] = []
    for ted_name in ordered_teds:
        group = ted_to_group.get(ted_name)
        if group is None:
            print(f"Warning: no .definition found for {ted_name}")
            result.append("")
        else:
            result.append(group)

    expected = len(track_elem_values)
    if len(result) != expected:
        print(
            f"Warning: parsed {len(result)} track element groups, "
            f"expected {expected} (TrackElemType count)"
        )

    return result
