"""IR schema for state.json — the output of the state parser."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel


# ── Properties ────────────────────────────────────────────────────────
#
# A property is one entry inside an interface definition.
# Six kinds:
#   scalar    — a primitive value: number, boolean, string
#   array     — a list of items (interface or enum); item_kind disambiguates
#   interface — a single nested interface (not an array)
#   flags     — synthesized from getFlag(flag: SomeUnion): boolean
#   enum_ref  — a field whose type is a string union enum
#   union     — a discriminated union of interfaces (e.g. ResearchItem);
#               is_array=True for ResearchItem[]


class ScalarProperty(BaseModel):
    ir_type: Literal["scalar"]
    name: str
    ts_type: str  # "number", "boolean", "string", or raw unknown
    optional: bool = False


class ArrayProperty(BaseModel):
    ir_type: Literal["array"]
    name: str
    ts_type: str  # e.g. "Award[]"
    item_type: str  # e.g. "Award" or "ResearchCategory"
    item_kind: Literal["interface", "enum"]  # what item_type refers to


class InterfaceProperty(BaseModel):
    ir_type: Literal["interface"]
    name: str
    ts_type: str  # e.g. "ScenarioObjective"
    interface: str  # e.g. "ScenarioObjective"
    optional: bool = False


class FlagsProperty(BaseModel):
    ir_type: Literal["flags"]
    name: str  # always "flags"
    flag_union: str  # e.g. "ParkFlags"


class EnumRefProperty(BaseModel):
    ir_type: Literal["enum_ref"]
    name: str
    ts_type: str  # e.g. "AwardType"
    enum: str  # e.g. "AwardType"
    optional: bool = False


class UnionProperty(BaseModel):
    ir_type: Literal["union"]
    name: str
    ts_type: str  # original TS type string, e.g. "ResearchItem[]"
    union_name: str  # the type alias, e.g. "ResearchItem"
    variants: list[
        str
    ]  # interface names, e.g. ["RideResearchItem", "SceneryResearchItem"]
    discriminator: str | None  # discriminating field name if detected, e.g. "type"
    is_array: bool = False  # True for ResearchItem[]
    optional: bool = False  # True for ResearchItem | null


Property = Annotated[
    Union[
        ScalarProperty,
        ArrayProperty,
        InterfaceProperty,
        FlagsProperty,
        EnumRefProperty,
        UnionProperty,
    ],
    ...,
]


# ── Interface ─────────────────────────────────────────────────────────


class Interface(BaseModel):
    """A TypeScript interface definition with all its readable properties."""

    name: str
    properties: list[Property]


# ── Namespace ─────────────────────────────────────────────────────────


class Namespace(BaseModel):
    """A top-level global variable exposed by the OpenRCT2 plugin API.

    e.g. `var park: Park` → name="park", ts_interface="Park"
    The bridge endpoint name is always the global var name.
    """

    name: str  # global var name: "park", "cheats", "date"
    ts_interface: str  # interface it implements: "Park", "Cheats", "GameDate"


# ── Entity Collection ─────────────────────────────────────────────────


class EntityCollection(BaseModel):
    """An array of game entities accessed via map.rides or map.getAllEntities().

    Unlike Namespaces (scalar global variables), entity collections are arrays
    of objects that need to be iterated and serialized individually.
    """

    name: str  # endpoint name: "rides", "staff", "guests"
    access: str  # JS access expression: "map.rides", 'map.getAllEntities("staff")'
    single_access: str  # JS function for single entity: "map.getRide", "map.getEntity"
    ts_interface: str  # root interface: "Ride", "Guest", or union type alias: "Staff"
    is_union: bool = False  # True when ts_interface is a union (e.g. Staff = Handyman | Mechanic | ...)


# ── Top-level IR ──────────────────────────────────────────────────────


class StateIR(BaseModel):
    """Top-level IR: the full state.json schema."""

    openrct2_version: str
    api_version: int
    generated_at: str
    generator_version: str
    namespaces: list[Namespace]
    entity_collections: list[EntityCollection]
    interfaces: dict[str, Interface]  # keyed by interface name
    enums: dict[str, list[str]]  # string union types → list of values
    interface_unions: dict[
        str, list[str]
    ]  # e.g. "ResearchItem" → ["RideResearchItem", "SceneryResearchItem"]
