"""IR schema for enums.json — integer-to-name mappings for OpenRCT2 numeric enums."""

from typing import Literal

from pydantic import BaseModel


class EnumValue(BaseModel):
    """A single named integer value within an enum."""

    name: str  # camelCase name, e.g. "spiralRollerCoaster"
    value: int  # integer value, e.g. 0


class EnumDef(BaseModel):
    """All active values for one enum type."""

    source: str  # relative path to the C++ source file, e.g. "src/openrct2/ride/RideData.cpp"
    kind: Literal["enum", "flags"] = "enum"  # "enum" → IntEnum, "flags" → IntFlag
    values: list[EnumValue]  # ordered by integer value


class EnumsIR(BaseModel):
    """Top-level IR: the full enums.json schema."""

    openrct2_version: str
    generated_at: str
    generator_version: str
    enums: dict[str, EnumDef]  # e.g. "RideType" → EnumDef
