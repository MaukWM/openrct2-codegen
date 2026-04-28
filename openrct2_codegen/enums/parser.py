"""Parse OpenRCT2 C++ source files to extract integer enum mappings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path

from openrct2_codegen.enums.ir import EnumDef, EnumValue, EnumsIR

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches the body of an enum class: enum class Foo : uint8_t { <body> };
_ENUM_BLOCK_RE = re.compile(
    r"enum\s+class\s+{name}\s*(?::\s*[\w:]+\s*)?\{{([^}}]*)\}}",
    # placeholder — compiled per enum name in parse_enum_class()
)

# Matches a single enum entry line.
# Groups: (1) name, (2) raw assignment if present (number, hex, or member name), or None
_VALUE_RE = re.compile(
    r"^\s*(\w+)\s*(?:=\s*([\w\-]+))?\s*,?",
    re.MULTILINE,
)

# Matches an entry in the kRideTypeDescriptors array.
# /* RIDE_TYPE_SPIRAL_ROLLER_COASTER */ SpiralRollerCoasterRTD,
# Array is positional — index is derived from match order.
_RTD_ENTRY_RE = re.compile(
    r"/\*\s*RIDE_TYPE_(\w+)\s*\*/\s*(\w+RTD)",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Name normalisers
# ---------------------------------------------------------------------------


def _to_camel(name: str) -> str:
    """PascalCase or lowerCamelCase → lowerCamelCase."""
    return name[0].lower() + name[1:] if name else name


def _screaming_snake_to_camel(name: str) -> str:
    """SCREAMING_SNAKE_CASE → lowerCamelCase."""
    parts = name.lower().split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


# ---------------------------------------------------------------------------
# Parse functions
# ---------------------------------------------------------------------------


def _extract_enum_body(source: str, cpp_name: str) -> str:
    """Find the brace-delimited body of ``enum class <cpp_name>`` in source."""
    pattern = re.compile(
        rf"enum\s+class\s+{re.escape(cpp_name)}\s*(?::\s*[\w:]+\s*)?\{{([^}}]*)\}}",
        re.DOTALL,
    )
    m = pattern.search(source)
    if m is None:
        raise ValueError(f"enum class '{cpp_name}' not found in source")
    return m.group(1)


def _parse_raw_entries(body: str) -> list[tuple[str, str | None]]:
    """Pass 1: extract (name, raw_assignment) pairs from enum body.

    raw_assignment is the string after ``=`` if present, else None.
    Examples: ("TrackColourMain", None), ("MazeStyle", "TrackColourSupports"), ("Foo", "0xFF").
    """
    return [(m.group(1), m.group(2)) for m in _VALUE_RE.finditer(body)]


def _resolve_values(
    raw_entries: list[tuple[str, str | None]], cpp_name: str
) -> list[EnumValue]:
    """Pass 2: resolve each entry to an integer value.

    Three cases:
    - No assignment: sequential counter (previous + 1, starting at 0)
    - Numeric literal (decimal or hex): use that value, counter follows from it
    - Member reference (another entry name): look up its already-resolved value
    """
    known: dict[str, int] = {}  # C++ name → resolved integer
    values: list[EnumValue] = []
    counter = 0

    for name, raw in raw_entries:
        if raw is None:
            # Implicit sequential
            pass
        elif raw.lstrip("-").isdigit():
            # Decimal literal
            counter = int(raw)
        elif raw.lower().startswith("0x"):
            # Hex literal
            counter = int(raw, 16)
        elif raw in known:
            # Member reference — reuse the same integer value
            counter = known[raw]
        else:
            raise ValueError(
                f"enum class '{cpp_name}': cannot resolve '{name} = {raw}'"
            )

        known[name] = counter
        values.append(EnumValue(name=_to_camel(name), value=counter))
        counter += 1

    return values


def parse_enum_class(source: str, cpp_name: str) -> list[EnumValue]:
    """Extract all values from a named C++ enum class in source text.

    Two-pass approach:
    1. Extract raw (name, assignment) pairs from the enum body
    2. Resolve each to an integer — numeric literals, sequential counting, or member references
    """
    body = _extract_enum_body(source, cpp_name)
    raw_entries = _parse_raw_entries(body)
    return _resolve_values(raw_entries, cpp_name)


def parse_ride_type_array(source: str) -> list[EnumValue]:
    """Extract RideType entries from the kRideTypeDescriptors array in RideData.cpp.

    The array is positional — integer value equals the entry's position in the array,
    including gaps left by skipped kDummyRTD entries.
    """
    values: list[EnumValue] = []
    for index, m in enumerate(_RTD_ENTRY_RE.finditer(source)):
        if m.group(2) == "kDummyRTD":
            continue
        values.append(
            EnumValue(
                name=_screaming_snake_to_camel(m.group(1)),
                value=index,  # positional index = integer ride type ID
            )
        )
    return values


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Target:
    file: str  # path relative to source_root
    cpp_name: str  # enum class name to search for (e.g. "Type" for Litter::Type)
    ir_name: str  # key in enums.json (e.g. "LitterType")
    mode: str  # "enum_class" or "array_index"


_ENUM_TARGETS: list[_Target] = [
    # ── entity/ ─────────────────────────────────────────────────────────────
    _Target(
        "src/openrct2/entity/Guest.h",
        "PeepThoughtType",
        "PeepThoughtType",
        "enum_class",
    ),
    _Target(
        "src/openrct2/entity/Guest.h",
        "PeepNauseaTolerance",
        "PeepNauseaTolerance",
        "enum_class",
    ),
    _Target("src/openrct2/entity/Peep.h", "PeepState", "PeepState", "enum_class"),
    _Target(
        "src/openrct2/entity/Peep.h", "PeepActionType", "PeepActionType", "enum_class"
    ),
    _Target(
        "src/openrct2/entity/Peep.h",
        "PeepAnimationType",
        "PeepAnimationType",
        "enum_class",
    ),
    _Target(
        "src/openrct2/entity/Peep.h",
        "PeepAnimationGroup",
        "PeepAnimationGroup",
        "enum_class",
    ),
    _Target("src/openrct2/entity/Litter.h", "Type", "LitterType", "enum_class"),
    _Target("src/openrct2/entity/Staff.h", "StaffType", "StaffType", "enum_class"),
    # ── ride/ ────────────────────────────────────────────────────────────────
    _Target("src/openrct2/ride/RideData.cpp", "RideType", "RideType", "array_index"),
    _Target("src/openrct2/ride/Ride.h", "RideMode", "RideMode", "enum_class"),
    _Target(
        "src/openrct2/ride/Ride.h", "RideInspection", "RideInspection", "enum_class"
    ),
    _Target("src/openrct2/ride/Ride.h", "RideStatus", "RideStatus", "enum_class"),
    _Target("src/openrct2/ride/ShopItem.h", "ShopItem", "ShopItem", "enum_class"),
    _Target(
        "src/openrct2/ride/ted/TrackElemType.h",
        "TrackElemType",
        "TrackElemType",
        "enum_class",
    ),
    _Target(
        "src/openrct2/ride/ted/PitchAndRoll.h", "TrackRoll", "TrackRoll", "enum_class"
    ),
    _Target(
        "src/openrct2/ride/ted/PitchAndRoll.h", "TrackPitch", "TrackPitch", "enum_class"
    ),
    _Target(
        "src/openrct2/ride/ted/TrackElementDescriptor.h",
        "TrackCurve",
        "TrackCurve",
        "enum_class",
    ),
    _Target(
        "src/openrct2/ride/ted/TrackGroup.h",
        "TrackGroup",
        "TrackGroup",
        "enum_class",
    ),
    # ── drawing/ ─────────────────────────────────────────────────────────────
    _Target("src/openrct2/drawing/Colour.h", "Colour", "Colour", "enum_class"),
    # ── root src/openrct2/ (included via cone-mode sparse checkout) ──────────
    _Target("src/openrct2/Cheats.h", "CheatType", "CheatType", "enum_class"),
    # ── actions/ ─────────────────────────────────────────────────────────────
    _Target(
        "src/openrct2/actions/ride/RideSetSettingAction.h",
        "RideSetSetting",
        "RideSetSetting",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/ride/RideSetAppearanceAction.h",
        "RideSetAppearanceType",
        "RideSetAppearanceType",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/ride/RideSetVehicleAction.h",
        "RideSetVehicleType",
        "RideSetVehicleType",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/ride/RideDemolishAction.h",
        "RideModifyType",
        "RideModifyType",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/ride/RideFreezeRatingAction.h",
        "RideRatingType",
        "RideRatingType",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/scenery/BannerSetStyleAction.h",
        "BannerSetStyleType",
        "BannerSetStyleType",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/park/LandBuyRightsAction.h",
        "LandBuyRightSetting",
        "LandBuyRightSetting",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/park/LandSetRightsAction.h",
        "LandSetRightSetting",
        "LandSetRightSetting",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/ride/MazeSetTrackAction.h",
        "MazeBuildMode",
        "MazeBuildMode",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/peep/PeepPickupAction.h",
        "PeepPickupType",
        "PeepPickupType",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/general/TileModifyAction.h",
        "TileModifyType",
        "TileModifyType",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/park/ParkSetParameterAction.h",
        "ParkParameter",
        "ParkParameter",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/general/ScenarioSetSettingAction.h",
        "ScenarioSetSetting",
        "ScenarioSetSetting",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/general/LoadOrQuitAction.h",
        "LoadOrQuitModes",
        "LoadOrQuitModes",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/peep/StaffSetPatrolAreaAction.h",
        "StaffSetPatrolAreaMode",
        "StaffSetPatrolAreaMode",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/network/NetworkModifyGroupAction.h",
        "ModifyGroupType",
        "ModifyGroupType",
        "enum_class",
    ),
    _Target(
        "src/openrct2/actions/network/NetworkModifyGroupAction.h",
        "PermissionState",
        "PermissionState",
        "enum_class",
    ),
    # ── world/ ───────────────────────────────────────────────────────────────
    _Target(
        "src/openrct2/world/MapSelection.h",
        "MapSelectType",
        "MapSelectType",
        "enum_class",
    ),
    _Target(
        "src/openrct2/world/Footpath.h",
        "FootpathSlopeType",
        "FootpathSlopeType",
        "enum_class",
    ),
    # ── interface/ ───────────────────────────────────────────────────────────
    _Target(
        "src/openrct2/interface/Window.h", "PromptMode", "PromptMode", "enum_class"
    ),
]


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def parse_enums(source_root: Path, version: str) -> EnumsIR:
    """Parse all enum targets and return the full EnumsIR."""
    enums: dict[str, EnumDef] = {}

    for target in _ENUM_TARGETS:
        path = source_root / target.file
        source = path.read_text(encoding="utf-8")

        if target.mode == "array_index":
            values = parse_ride_type_array(source)
        else:
            values = parse_enum_class(source, target.cpp_name)

        enums[target.ir_name] = EnumDef(source=target.file, values=values)

    # Synthetic enum: Direction is a uint8_t typedef (not an enum class), always 0-3.
    # Values from TileElementBase.h: TILE_ELEMENT_DIRECTION_{WEST,NORTH,EAST,SOUTH}
    # Note: kInvalidDirection (0xFF/255) is NOT included — it's a sentinel, not a
    # direction. It's exposed as INVALID_DIRECTION constant in the enums template.
    enums["Direction"] = EnumDef(
        source="synthetic",
        values=[
            EnumValue(name="west", value=0),
            EnumValue(name="north", value=1),
            EnumValue(name="east", value=2),
            EnumValue(name="south", value=3),
        ],
    )

    # Synthetic flags: bitflag types that are `using` typedefs with constexpr constants,
    # not `enum class` definitions. Too few and too inconsistent to justify a parser.

    # Footpath edge connectivity bitmask. Each bit indicates a connection in that
    # direction. Read from FootpathElement.edges, used by FootpathConnectEdges().
    # Note: bit order does NOT match Direction enum values.
    enums["EdgeBit"] = EnumDef(
        source="synthetic",
        kind="flags",
        values=[
            EnumValue(name="west", value=1),
            EnumValue(name="south", value=2),
            EnumValue(name="east", value=4),
            EnumValue(name="north", value=8),
        ],
    )

    # src/openrct2/actions/terraform/ClearAction.h
    enums["ClearableItems"] = EnumDef(
        source="synthetic",
        kind="flags",
        values=[
            EnumValue(name="scenerySmall", value=1),
            EnumValue(name="sceneryLarge", value=2),
            EnumValue(name="sceneryFootpath", value=4),
        ],
    )

    # src/openrct2/world/Footpath.h
    enums["PathConstructFlags"] = EnumDef(
        source="synthetic",
        kind="flags",
        values=[
            EnumValue(name="isQueue", value=1),
            EnumValue(name="isLegacyPathObject", value=2),
        ],
    )

    # src/openrct2/ride/RideConstruction.h — LiftHillAndInverted enum inside FlagHolder
    enums["SelectedLiftAndInverted"] = EnumDef(
        source="synthetic",
        kind="flags",
        values=[
            EnumValue(name="liftHill", value=1),
            EnumValue(name="inverted", value=2),
        ],
    )

    # Synthetic enums: old-style C enums (not `enum class`) that our parser can't handle.
    # If OpenRCT2 migrates these to `enum class` in a future release, they can be moved
    # to _ENUM_TARGETS and parsed automatically — remove the synthetic entry at that point.

    # Old C enum in src/openrct2/management/Marketing.h.
    # Migratable: if OpenRCT2 converts to `enum class AdvertisingCampaignType`, add to
    # _ENUM_TARGETS and remove this block.
    enums["AdvertisingCampaignType"] = EnumDef(
        source="synthetic",
        values=[
            EnumValue(name="parkEntryFree", value=0),
            EnumValue(name="rideFree", value=1),
            EnumValue(name="parkEntryHalfPrice", value=2),
            EnumValue(name="foodOrDrinkFree", value=3),
            EnumValue(name="park", value=4),
            EnumValue(name="ride", value=5),
        ],
    )

    # Old C enum in src/openrct2/management/Research.h.
    # Migratable: if OpenRCT2 converts to `enum class ResearchFundingLevel`, add to
    # _ENUM_TARGETS and remove this block.
    enums["ResearchFundingLevel"] = EnumDef(
        source="synthetic",
        values=[
            EnumValue(name="none", value=0),
            EnumValue(name="minimum", value=1),
            EnumValue(name="normal", value=2),
            EnumValue(name="maximum", value=3),
        ],
    )

    # No enum in C++ source — validated inline as 1..4 (1..8 with debug tools).
    # src/openrct2/actions/general/GameSetSpeedAction.cpp
    # Not migratable: no C++ enum exists, purely a range check.
    enums["GameSpeed"] = EnumDef(
        source="synthetic",
        values=[
            EnumValue(name="normal", value=1),
            EnumValue(name="fast", value=2),
            EnumValue(name="faster", value=3),
            EnumValue(name="fastest", value=4),
        ],
    )

    return EnumsIR(
        openrct2_version=version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator_version=pkg_version("openrct2-codegen"),
        enums=enums,
    )
