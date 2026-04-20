"""Parse openrct2.d.ts to produce a StateIR."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path

from openrct2_codegen.actions.parser import parse_plugin_api_version
from openrct2_codegen.state.ir import (
    ArrayProperty,
    EntityCollection,
    EnumRefProperty,
    FlagsProperty,
    Interface,
    InterfaceProperty,
    Namespace,
    Property,
    ScalarProperty,
    StateIR,
    UnionProperty,
)

# ── Namespaces to include ─────────────────────────────────────────────
# Add new namespaces here as we expand coverage.

_NAMESPACES: list[Namespace] = [
    Namespace(name="park", ts_interface="Park"),
    Namespace(name="cheats", ts_interface="Cheats"),
    Namespace(name="date", ts_interface="GameDate"),
    Namespace(name="scenario", ts_interface="Scenario"),
    Namespace(name="climate", ts_interface="Climate"),
]

# ── Entity collections to include ────────────────────────────────────
# Arrays of game entities accessed via map properties or getAllEntities().
# Interfaces are parsed with inheritance flattening.

_ENTITY_COLLECTIONS: list[EntityCollection] = [
    EntityCollection(
        name="rides",
        access="map.rides",
        single_access="map.getRide",
        ts_interface="Ride",
    ),
    EntityCollection(
        name="staff",
        access='map.getAllEntities("staff")',
        single_access="map.getEntity",
        ts_interface="Staff",
        is_union=True,
    ),
    EntityCollection(
        name="guests",
        access='map.getAllEntities("guest")',
        single_access="map.getEntity",
        ts_interface="Guest",
    ),
]

# ── Standalone flattened interfaces ──────────────────────────────────
# TileElement variants (SurfaceElement, FootpathElement, etc.) from:
# https://github.com/OpenRCT2/OpenRCT2/blob/develop/distribution/openrct2.d.ts
#
# These extend BaseTileElement and form the TileElement discriminated union.
# They're not a namespace (like park/cheats) or an entity collection
# (like rides/staff) — nothing in the plugin API exposes them as a
# top-level array.  Instead, they live inside Tile.elements which is
# accessed via map.getTile(x, y).  The bridge's hand-written get_tile
# endpoint uses the generated serializers to send them over TCP.

_STANDALONE_FLATTENED: list[str] = [
    "SurfaceElement",
    "FootpathElement",
    "TrackElement",
    "SmallSceneryElement",
    "WallElement",
    "EntranceElement",
    "LargeSceneryElement",
    "BannerElement",
]

_PRIMITIVES = {"number", "boolean", "string"}

# ── d.ts nullability overrides ───────────────────────────────────────
# Fields that are typed as non-nullable in the d.ts but are null at runtime.
# Maps "InterfaceName.fieldName" → True (force optional).
# See docs/openrct2-api-bugs.md for details on each.

_FORCE_OPTIONAL: set[str] = {
    # Bug #1: ScenarioObjective fields omitted based on objective type
    "ScenarioObjective.guests",
    "ScenarioObjective.year",
    "ScenarioObjective.length",
    "ScenarioObjective.excitement",
    "ScenarioObjective.parkValue",
    "ScenarioObjective.monthlyIncome",
    # Bug #7: RideStation fields null for stalls (no station)
    "RideStation.start",
    "RideStation.entrance",
    "RideStation.exit",
    # Bug #7 (cont): Ride.value null for unrated rides/stalls
    "Ride.value",
    # Bug #7 (cont): InstalledObject.version absent for RCT2-era objects
    "InstalledObject.version",
}

# ── Regex patterns ────────────────────────────────────────────────────

# interface Foo { OR interface Foo extends Bar {
_INTERFACE_RE = re.compile(r"\binterface\s+(\w+)(?:\s+extends\s+\w+)?\s*\{")

# type Foo = "a" | "b" | "c";  — pure string literal union
_STRING_UNION_RE = re.compile(r'\btype\s+(\w+)\s*=\s*((?:"[^"]+"\s*\|?\s*)+)\s*;')

# Extract individual quoted values from a union
_UNION_VALUE_RE = re.compile(r'"([^"]+)"')

# type Foo = BarType | "literal";  — mixed union (identifiers and/or string literals)
# Matches when there is at least one uppercase identifier (interface/enum name).
_MIXED_UNION_RE = re.compile(
    r'\btype\s+(\w+)\s*=\s*((?:(?:"[^"]+"|[A-Z]\w*)\s*\|?\s*)+)\s*;'
)

# Extract individual parts from a mixed union (identifier or quoted string)
_MIXED_PART_RE = re.compile(r'"([^"]+)"|([A-Z]\w*)')

# type Foo = InterfaceA | InterfaceB;  — interface union (all parts are uppercase identifiers)
_IFACE_UNION_RE = re.compile(
    r"\btype\s+(\w+)\s*=\s*([A-Z]\w*(?:\s*\|\s*[A-Z]\w*)+)\s*;"
)

# Extract uppercase identifiers from an interface union
_IFACE_PART_RE = re.compile(r"[A-Z]\w*")

# Property line inside an interface body (not a method — no `(` before `:`)
# Handles: `cash: number;`, `readonly guests: number;`, `name?: string;`
_PROPERTY_RE = re.compile(
    r"^[ \t]*(?:readonly\s+)?(\w+)(\?)?\s*:\s*([^;(\n]+)\s*;?",
    re.MULTILINE,
)

# getFlag(flag: SomeUnion): boolean — detect flags pattern
_GET_FLAG_RE = re.compile(r"\bgetFlag\s*\(\s*\w+\s*:\s*(\w+)\s*\)\s*:\s*boolean")

# Literal type field: `readonly type: "ride";` — used for discriminator detection
_LITERAL_FIELD_RE = re.compile(
    r'^\s*(?:readonly\s+)?(\w+)\s*:\s*"([^"]+)"\s*;',
    re.MULTILINE,
)


# ── Interface body extraction ─────────────────────────────────────────

# interface Foo extends Bar {
_EXTENDS_RE = re.compile(r"\binterface\s+(\w+)\s+extends\s+(\w+)\s*\{")


def _extract_interface_body(text: str, name: str) -> str | None:
    """Return the body text of `interface <name> { ... }` (without braces)."""
    pattern = re.compile(
        r"\binterface\s+" + re.escape(name) + r"(?:\s+extends\s+\w+)?\s*\{"
    )
    match = pattern.search(text)
    if not match:
        return None

    start = match.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1

    return text[start : i - 1]


def _get_parent(text: str, name: str) -> str | None:
    """Return the parent interface name if `interface <name> extends <parent>`, else None."""
    pattern = re.compile(
        r"\binterface\s+" + re.escape(name) + r"\s+extends\s+(\w+)\s*\{"
    )
    match = pattern.search(text)
    return match.group(1) if match else None


def _get_inheritance_chain(text: str, name: str) -> list[str]:
    """Return the full inheritance chain, from most-ancestral to the named interface.

    e.g. _get_inheritance_chain(text, "Guest") → ["Entity", "Peep", "Guest"]
    """
    chain = [name]
    current = name
    while True:
        parent = _get_parent(text, current)
        if parent is None:
            break
        chain.append(parent)
        current = parent
    chain.reverse()
    return chain


# ── Discriminator detection ───────────────────────────────────────────


def _find_discriminator(text: str, variants: list[str]) -> str | None:
    """Find the discriminator field for a union of interfaces.

    A discriminator is a field present in every variant with a unique
    string literal type (e.g. `readonly type: "ride"`).
    """
    variant_literals: list[dict[str, str]] = []

    for variant in variants:
        body = _extract_interface_body(text, variant)
        if body is None:
            return None
        literals: dict[str, str] = {}
        for m in _LITERAL_FIELD_RE.finditer(body):
            literals[m.group(1)] = m.group(2)
        variant_literals.append(literals)

    if not variant_literals:
        return None

    # Fields present in every variant
    common_fields = set(variant_literals[0].keys())
    for vl in variant_literals[1:]:
        common_fields &= set(vl.keys())

    # Discriminator: common field whose values are all distinct
    for field in common_fields:
        values = [vl[field] for vl in variant_literals]
        if len(set(values)) == len(variants):
            return field

    return None


# ── Mixed enum resolution ─────────────────────────────────────────────


def _resolve_mixed_enums(
    text: str,
    known_string_enums: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Resolve mixed unions like `type X = KnownEnum | "literal"` into flat string lists.

    Only resolves unions where every identifier part is a known string enum.
    Returns a new dict of additional enum entries to merge into known_string_enums.
    """
    resolved: dict[str, list[str]] = {}

    for match in _MIXED_UNION_RE.finditer(text):
        union_name = match.group(1)
        if union_name in known_string_enums:
            continue  # already parsed as pure string union

        parts_raw = match.group(2)
        values: list[str] = []
        ok = True

        for m in _MIXED_PART_RE.finditer(parts_raw):
            quoted_val = m.group(1)
            identifier = m.group(2)

            if quoted_val is not None:
                values.append(quoted_val)
            elif identifier is not None:
                if identifier in known_string_enums:
                    values.extend(known_string_enums[identifier])
                else:
                    ok = False
                    break

        if ok and values:
            resolved[union_name] = values

    return resolved


# ── Type resolution ───────────────────────────────────────────────────


def _resolve_property(
    name: str,
    optional: bool,
    raw_type: str,
    known_interfaces: set[str],
    known_enums: set[str],
    interface_unions: dict[str, list[str]],
    union_discriminators: dict[str, str | None],
) -> (
    ScalarProperty | ArrayProperty | InterfaceProperty | EnumRefProperty | UnionProperty
):
    """Resolve a raw TypeScript type string into a typed IR property."""
    ts_type = raw_type.strip()

    # Handle nullable: T | null → strip null, mark optional
    if re.search(r"\|\s*null$", ts_type):
        ts_type = re.sub(r"\s*\|\s*null$", "", ts_type).strip()
        optional = True

    # Array: Foo[] → ArrayProperty or UnionProperty(is_array=True)
    if ts_type.endswith("[]"):
        item = ts_type[:-2]
        if item in interface_unions:
            return UnionProperty(
                ir_type="union",
                name=name,
                ts_type=raw_type.strip(),
                union_name=item,
                variants=interface_unions[item],
                discriminator=union_discriminators.get(item),
                is_array=True,
                optional=optional,
            )
        if item in known_enums:
            return ArrayProperty(
                ir_type="array",
                name=name,
                ts_type=raw_type.strip(),
                item_type=item,
                item_kind="enum",
            )
        if item in _PRIMITIVES:
            return ScalarProperty(
                ir_type="scalar", name=name, ts_type=raw_type.strip(), optional=optional
            )
        return ArrayProperty(
            ir_type="array",
            name=name,
            ts_type=raw_type.strip(),
            item_type=item,
            item_kind="interface",
        )

    # Primitive
    if ts_type in _PRIMITIVES:
        return ScalarProperty(
            ir_type="scalar", name=name, ts_type=ts_type, optional=optional
        )

    # Known enum/union
    if ts_type in known_enums:
        return EnumRefProperty(
            ir_type="enum_ref",
            name=name,
            ts_type=ts_type,
            enum=ts_type,
            optional=optional,
        )

    # Interface union (non-array, e.g. ResearchItem | null already handled above)
    if ts_type in interface_unions:
        return UnionProperty(
            ir_type="union",
            name=name,
            ts_type=raw_type.strip(),
            union_name=ts_type,
            variants=interface_unions[ts_type],
            discriminator=union_discriminators.get(ts_type),
            is_array=False,
            optional=optional,
        )

    # Known interface
    if ts_type in known_interfaces:
        return InterfaceProperty(
            ir_type="interface",
            name=name,
            ts_type=ts_type,
            interface=ts_type,
            optional=optional,
        )

    # Unknown type — scalar with raw ts_type
    return ScalarProperty(
        ir_type="scalar", name=name, ts_type=ts_type, optional=optional
    )


# ── Interface parsing ─────────────────────────────────────────────────


def _parse_interface(
    text: str,
    name: str,
    known_interfaces: set[str],
    known_enums: set[str],
    interface_unions: dict[str, list[str]],
    union_discriminators: dict[str, str | None],
) -> Interface | None:
    """Parse a single interface definition from the .d.ts text."""
    body = _extract_interface_body(text, name)
    if body is None:
        return None

    properties: list[Property] = []

    # Synthesize flags property from getFlag() method if present
    flag_match = _GET_FLAG_RE.search(body)
    if flag_match:
        flag_union = flag_match.group(1)
        properties.append(
            FlagsProperty(ir_type="flags", name="flags", flag_union=flag_union)
        )

    # Extract all property declarations (skip method lines)
    for match in _PROPERTY_RE.finditer(body):
        prop_name = match.group(1)
        optional = match.group(2) == "?"
        raw_type = match.group(3)

        # Skip if this line is actually a method (has `(` in the matched region)
        if "(" in raw_type:
            continue

        # Apply d.ts nullability overrides (see docs/openrct2-api-bugs.md)
        if f"{name}.{prop_name}" in _FORCE_OPTIONAL:
            optional = True

        properties.append(
            _resolve_property(
                prop_name,
                optional,
                raw_type,
                known_interfaces,
                known_enums,
                interface_unions,
                union_discriminators,
            )
        )

    return Interface(name=name, properties=properties)


def _parse_interface_flattened(
    text: str,
    name: str,
    known_interfaces: set[str],
    known_enums: set[str],
    interface_unions: dict[str, list[str]],
    union_discriminators: dict[str, str | None],
) -> Interface | None:
    """Parse an interface with all inherited properties flattened in.

    Walks the extends chain (e.g. Guest → Peep → Entity) and concatenates
    properties from ancestors first, then the interface's own properties.
    """
    chain = _get_inheritance_chain(text, name)
    props_by_name: dict[str, Property] = {}
    ordered_names: list[str] = []

    for iface_name in chain:
        parsed = _parse_interface(
            text,
            iface_name,
            known_interfaces,
            known_enums,
            interface_unions,
            union_discriminators,
        )
        if parsed is None:
            return None
        for prop in parsed.properties:
            if prop.name not in props_by_name:
                ordered_names.append(prop.name)
            props_by_name[prop.name] = prop  # child overrides parent

    return Interface(name=name, properties=[props_by_name[n] for n in ordered_names])


# ── Recursive interface collection ────────────────────────────────────


def _collect_interfaces(
    text: str,
    root_interfaces: list[str],
    known_interfaces: set[str],
    known_enums: set[str],
    interface_unions: dict[str, list[str]],
    union_discriminators: dict[str, str | None],
) -> dict[str, Interface]:
    """Parse all interfaces reachable from the root set, recursively."""
    result: dict[str, Interface] = {}
    queue = list(root_interfaces)

    while queue:
        name = queue.pop(0)
        if name in result:
            continue

        iface = _parse_interface_flattened(
            text,
            name,
            known_interfaces,
            known_enums,
            interface_unions,
            union_discriminators,
        )
        if iface is None:
            raise ValueError(
                f"Interface '{name}' not found in .d.ts — IR is incomplete"
            )

        result[name] = iface

        # Queue any referenced interfaces we haven't parsed yet
        for prop in iface.properties:
            if (
                prop.ir_type == "array"
                and prop.item_kind == "interface"
                and prop.item_type not in result
            ):
                queue.append(prop.item_type)
            elif prop.ir_type == "interface" and prop.interface not in result:
                queue.append(prop.interface)
            elif prop.ir_type == "union":
                for variant in prop.variants:
                    if variant not in result:
                        queue.append(variant)

    return result


# ── Top-level parser ──────────────────────────────────────────────────


def parse_state(dts_path: Path, openrct2_version: str, source_root: Path) -> StateIR:
    """Parse openrct2.d.ts and return a complete StateIR."""
    text = dts_path.read_text(encoding="utf-8")

    # Pass 1: collect all interface names
    known_interfaces = set(_INTERFACE_RE.findall(text))

    # Pass 1b: collect string union enums (pure string literal unions)
    enums: dict[str, list[str]] = {}
    for match in _STRING_UNION_RE.finditer(text):
        union_name = match.group(1)
        values = _UNION_VALUE_RE.findall(match.group(2))
        enums[union_name] = values

    # Pass 1c: resolve mixed enums (e.g. KnownEnum | "literal")
    enums.update(_resolve_mixed_enums(text, enums))
    known_enums = set(enums.keys())

    # Pass 1d: collect interface unions (e.g. ResearchItem = RideResearchItem | SceneryResearchItem)
    interface_unions: dict[str, list[str]] = {}
    for match in _IFACE_UNION_RE.finditer(text):
        union_name = match.group(1)
        variants = _IFACE_PART_RE.findall(match.group(2))
        # Only treat as interface union if all variants are known interfaces
        # (filters out false positives from the regex)
        if all(v in known_interfaces for v in variants):
            interface_unions[union_name] = variants

    # Precompute discriminators for all interface unions
    union_discriminators: dict[str, str | None] = {
        name: _find_discriminator(text, variants)
        for name, variants in sorted(interface_unions.items())
    }

    # Pass 2: parse interfaces reachable from our namespace roots
    root_interfaces = [ns.ts_interface for ns in _NAMESPACES]
    interfaces = _collect_interfaces(
        text,
        root_interfaces,
        known_interfaces,
        known_enums,
        interface_unions,
        union_discriminators,
    )

    # Pass 3: parse entity collection interfaces (with inheritance flattening)
    for ec in _ENTITY_COLLECTIONS:
        if ec.is_union:
            # Union type (e.g. Staff = Handyman | Mechanic | ...) —
            # parse each variant with flattening
            variants = interface_unions.get(ec.ts_interface, [])
            for variant in variants:
                if variant not in interfaces:
                    iface = _parse_interface_flattened(
                        text,
                        variant,
                        known_interfaces,
                        known_enums,
                        interface_unions,
                        union_discriminators,
                    )
                    if iface is None:
                        raise ValueError(
                            f"Entity variant '{variant}' not found in .d.ts"
                        )
                    interfaces[iface.name] = iface
        else:
            # Concrete type (e.g. Ride, Guest) — parse with flattening
            if ec.ts_interface not in interfaces:
                iface = _parse_interface_flattened(
                    text,
                    ec.ts_interface,
                    known_interfaces,
                    known_enums,
                    interface_unions,
                    union_discriminators,
                )
                if iface is None:
                    raise ValueError(
                        f"Entity interface '{ec.ts_interface}' not found in .d.ts"
                    )
                interfaces[iface.name] = iface

        # Collect nested interfaces referenced by entity properties (from flattened interfaces)
        entity_iface_names = (
            [ec.ts_interface]
            if not ec.is_union
            else interface_unions.get(ec.ts_interface, [])
        )
        nested_roots: list[str] = []
        for ename in entity_iface_names:
            if ename in interfaces:
                for prop in interfaces[ename].properties:
                    if (
                        prop.ir_type == "array"
                        and prop.item_kind == "interface"
                        and prop.item_type not in interfaces
                    ):
                        nested_roots.append(prop.item_type)
                    elif (
                        prop.ir_type == "interface" and prop.interface not in interfaces
                    ):
                        nested_roots.append(prop.interface)
                    elif prop.ir_type == "union":
                        for variant in prop.variants:
                            if variant not in interfaces:
                                nested_roots.append(variant)
        if nested_roots:
            nested = _collect_interfaces(
                text,
                nested_roots,
                known_interfaces,
                known_enums,
                interface_unions,
                union_discriminators,
            )
            for k, v in nested.items():
                if k not in interfaces:
                    interfaces[k] = v

    # Pass 3b: parse standalone flattened interfaces (e.g. tile elements)
    for iface_name in _STANDALONE_FLATTENED:
        if iface_name not in interfaces:
            iface = _parse_interface_flattened(
                text,
                iface_name,
                known_interfaces,
                known_enums,
                interface_unions,
                union_discriminators,
            )
            if iface is None:
                raise ValueError(
                    f"Standalone interface '{iface_name}' not found in .d.ts"
                )
            interfaces[iface.name] = iface

    # Trim enums to only those actually referenced in the collected interfaces
    referenced_enums: set[str] = set()
    for iface in interfaces.values():
        for prop in iface.properties:
            if prop.ir_type == "enum_ref":
                referenced_enums.add(prop.enum)
            elif prop.ir_type == "flags":
                referenced_enums.add(prop.flag_union)
            elif prop.ir_type == "array" and prop.item_kind == "enum":
                referenced_enums.add(prop.item_type)
    enums = {k: v for k, v in sorted(enums.items()) if k in referenced_enums}

    # Trim interface_unions to only those referenced
    referenced_unions: set[str] = set()
    for iface in interfaces.values():
        for prop in iface.properties:
            if prop.ir_type == "union":
                referenced_unions.add(prop.union_name)
    # Also include unions used by entity collections
    for ec in _ENTITY_COLLECTIONS:
        if ec.is_union:
            referenced_unions.add(ec.ts_interface)
    # Include unions whose variants are all in standalone flattened set
    standalone_set = set(_STANDALONE_FLATTENED)
    for union_name, variants in sorted(interface_unions.items()):
        if all(v in standalone_set for v in variants):
            referenced_unions.add(union_name)
    interface_unions = {
        k: v for k, v in sorted(interface_unions.items()) if k in referenced_unions
    }

    api_version = parse_plugin_api_version(source_root)

    return StateIR(
        openrct2_version=openrct2_version,
        api_version=api_version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator_version=pkg_version("openrct2-codegen"),
        namespaces=_NAMESPACES,
        entity_collections=_ENTITY_COLLECTIONS,
        interfaces=interfaces,
        enums=enums,
        interface_unions=interface_unions,
    )
