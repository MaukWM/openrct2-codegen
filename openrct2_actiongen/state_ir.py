"""IR schema for state.json — the output of the state parser."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel


# ── Properties ────────────────────────────────────────────────────────
#
# A property is one entry inside an interface definition.
# Four kinds:
#   scalar    — a primitive value: number, boolean, string
#   array     — a list of items belonging to another interface
#   interface — a single nested interface (not an array)
#   flags     — synthesized from getFlag(flag: SomeUnion): boolean
#   enum_ref  — a field whose type is a string union enum


class ScalarProperty(BaseModel):
    ir_type: Literal["scalar"]
    name: str
    ts_type: str                 # "number", "boolean", "string", or raw unknown
    optional: bool = False


class ArrayProperty(BaseModel):
    ir_type: Literal["array"]
    name: str
    ts_type: str                 # e.g. "Award[]"
    item_interface: str          # e.g. "Award"


class InterfaceProperty(BaseModel):
    ir_type: Literal["interface"]
    name: str
    ts_type: str                 # e.g. "ScenarioObjective"
    interface: str               # e.g. "ScenarioObjective"
    optional: bool = False


class FlagsProperty(BaseModel):
    ir_type: Literal["flags"]
    name: str              # always "flags"
    flag_union: str        # e.g. "ParkFlags"


class EnumRefProperty(BaseModel):
    ir_type: Literal["enum_ref"]
    name: str
    ts_type: str                 # e.g. "AwardType"
    enum: str                    # e.g. "AwardType"
    optional: bool = False


Property = Annotated[
    Union[ScalarProperty, ArrayProperty, InterfaceProperty, FlagsProperty, EnumRefProperty],
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

    name: str            # global var name: "park", "cheats", "date"
    ts_interface: str    # interface it implements: "Park", "Cheats", "GameDate"


# ── Top-level IR ──────────────────────────────────────────────────────

class StateIR(BaseModel):
    """Top-level IR: the full state.json schema."""

    openrct2_version: str
    api_version: int
    generated_at: str
    generator_version: str
    namespaces: list[Namespace]
    interfaces: dict[str, Interface]   # keyed by interface name
    enums: dict[str, list[str]]        # keyed by enum/union name → list of values
