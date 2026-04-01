"""IR schema for objects.json — ride object catalog and ride type descriptors."""

from __future__ import annotations

from pydantic import BaseModel


class RideObjectDef(BaseModel):
    """A single ride object definition from the OpenRCT2 objects repo."""

    identifier: str  # e.g. "rct2.ride.mgr1"
    name: str  # e.g. "Merry-Go-Round" (en-US)
    ride_type: str  # e.g. "merry_go_round" (matches RTD .Name)
    category: str | list[str]  # e.g. "gentle", "shop", or ["water", "thrill"]


class RideTypeDescriptor(BaseModel):
    """Per-ride-type data derived from C++ RideTypeDescriptor (RTD headers).

    Mirrors the C++ RideTypeDescriptor struct from src/openrct2/ride/RideData.h.
    Only includes flat ride types (those with flatTrack* StartTrackPiece).
    Extensible — more fields from the C++ struct can be added as needed.
    """

    track_elem: str  # e.g. "flatTrack3x3" (TrackElemType name)
    tiles_x: int  # footprint width in tiles, e.g. 3
    tiles_y: int  # footprint depth in tiles, e.g. 3
    clearance_height: (
        int  # vertical clearance in z-units (from RideHeights.ClearanceHeight)
    )


class ObjectsIR(BaseModel):
    """Top-level IR: the full objects.json schema."""

    openrct2_version: str
    objects_version: str
    generated_at: str
    generator_version: str
    ride_objects: list[RideObjectDef]
    ride_type_descriptors: dict[
        str, RideTypeDescriptor
    ]  # ride_type name → descriptor (flat rides only)
