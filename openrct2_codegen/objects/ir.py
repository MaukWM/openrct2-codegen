"""IR schema for objects.json — full object catalog and ride type descriptors."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ObjectDef(BaseModel):
    """A single object definition from the OpenRCT2 objects repo.

    All object types (ride, scenery, wall, footpath, etc.) share this model.
    Type-specific fields live in the properties dict, straight from the source JSON.

    Ride objects will have: properties.ride_type, properties.category
    Scenery objects will have: properties.price, properties.height, etc.
    """

    identifier: str  # e.g. "rct2.ride.mgr1", "rct2.scenery_small.jbean1"
    object_type: str  # e.g. "ride", "scenery_small", "scenery_wall"
    name: str  # e.g. "Merry-Go-Round" (en-US)
    properties: dict[str, Any]  # type-specific fields from the source JSON


class RideTypeDescriptor(BaseModel):
    """Per-ride-type data derived from C++ RideTypeDescriptor (RTD headers).

    Mirrors the C++ RideTypeDescriptor struct from src/openrct2/ride/RideData.h.
    Only includes flat ride types (those with flatTrack* StartTrackPiece).
    Extensible — more fields from the C++ struct can be added as needed.
    """

    track_elem: str  # e.g. "flatTrack3x3" (TrackElemType name)
    track_elem_value: int  # resolved TrackElemType enum integer, e.g. 266
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
    objects: list[ObjectDef]  # all objects, all types
    ride_type_descriptors: dict[
        str, RideTypeDescriptor
    ]  # ride_type name → descriptor (flat rides only)
