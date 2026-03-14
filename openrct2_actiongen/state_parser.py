"""Parse openrct2.d.ts to produce a StateIR."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path

from openrct2_actiongen.parser import parse_plugin_api_version
from openrct2_actiongen.state_ir import (
    ArrayProperty,
    EnumRefProperty,
    FlagsProperty,
    Interface,
    InterfaceProperty,
    Namespace,
    ScalarProperty,
    StateIR,
)

# ── Namespaces to include ─────────────────────────────────────────────
# Add new namespaces here as we expand coverage.

_NAMESPACES: list[Namespace] = [
    Namespace(name="park",     ts_interface="Park"),
    Namespace(name="cheats",   ts_interface="Cheats"),
    Namespace(name="date",     ts_interface="GameDate"),
    Namespace(name="scenario", ts_interface="Scenario"),
    Namespace(name="climate",  ts_interface="Climate"),
]

# Interfaces that are referenced but deferred to a future endpoint.
# The parser will include them as properties in the IR but not recurse into them.
_DEFERRED_INTERFACES = {"Research", "ParkMessage"}

_PRIMITIVES = {"number", "boolean", "string"}

# ── Regex patterns ────────────────────────────────────────────────────

# interface Foo {
_INTERFACE_RE = re.compile(r'\binterface\s+(\w+)\s*\{')

# type Foo = "a" | "b" | "c";
_TYPE_UNION_RE = re.compile(
    r'\btype\s+(\w+)\s*=\s*((?:"[^"]+"\s*\|?\s*)+)\s*;'
)

# Extract individual string values from a union
_UNION_VALUE_RE = re.compile(r'"([^"]+)"')

# Property line inside an interface body (not a method — no `(` before `:`)
# Handles: `cash: number;`, `readonly guests: number;`, `name?: string;`
_PROPERTY_RE = re.compile(
    r'^[ \t]*(?:readonly\s+)?(\w+)(\?)?\s*:\s*([^;(\n]+)\s*;?',
    re.MULTILINE,
)

# getFlag(flag: SomeUnion): boolean — detect flags pattern
_GET_FLAG_RE = re.compile(
    r'\bgetFlag\s*\(\s*\w+\s*:\s*(\w+)\s*\)\s*:\s*boolean'
)


# ── Interface body extraction ─────────────────────────────────────────

def _extract_interface_body(text: str, name: str) -> str | None:
    """Return the body text of `interface <name> { ... }` (without braces)."""
    pattern = re.compile(r'\binterface\s+' + re.escape(name) + r'\s*\{')
    match = pattern.search(text)
    if not match:
        return None

    start = match.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
        i += 1

    return text[start:i - 1]


# ── Type resolution ───────────────────────────────────────────────────

def _resolve_property(
    name: str,
    optional: bool,
    raw_type: str,
    known_interfaces: set[str],
    known_enums: set[str],
) -> ScalarProperty | ArrayProperty | InterfaceProperty | EnumRefProperty:
    """Resolve a raw TypeScript type string into a typed IR property."""
    ts_type = raw_type.strip()

    # Array: Award[] → ArrayProperty
    if ts_type.endswith("[]"):
        item = ts_type[:-2]
        return ArrayProperty(ir_type="array", name=name, ts_type=ts_type, item_interface=item)

    # Primitive
    if ts_type in _PRIMITIVES:
        return ScalarProperty(ir_type="scalar", name=name, ts_type=ts_type, optional=optional)

    # Known enum/union
    if ts_type in known_enums:
        return EnumRefProperty(ir_type="enum_ref", name=name, ts_type=ts_type, enum=ts_type, optional=optional)

    # Known interface
    if ts_type in known_interfaces:
        return InterfaceProperty(ir_type="interface", name=name, ts_type=ts_type, interface=ts_type, optional=optional)

    # Unknown type (e.g. nullable `T | null`) — scalar with raw ts_type, resolvable later
    return ScalarProperty(ir_type="scalar", name=name, ts_type=ts_type, optional=optional)


# ── Interface parsing ─────────────────────────────────────────────────

def _parse_interface(
    text: str,
    name: str,
    known_interfaces: set[str],
    known_enums: set[str],
) -> Interface | None:
    """Parse a single interface definition from the .d.ts text."""
    body = _extract_interface_body(text, name)
    if body is None:
        return None

    properties = []

    # Synthesize flags property from getFlag() method if present
    flag_match = _GET_FLAG_RE.search(body)
    if flag_match:
        flag_union = flag_match.group(1)
        properties.append(FlagsProperty(ir_type="flags", name="flags", flag_union=flag_union))

    # Extract all property declarations (skip method lines)
    for match in _PROPERTY_RE.finditer(body):
        prop_name = match.group(1)
        optional = match.group(2) == "?"
        raw_type = match.group(3)

        # Skip if this line is actually a method (has `(` in the matched region)
        if "(" in raw_type:
            continue

        properties.append(_resolve_property(prop_name, optional, raw_type, known_interfaces, known_enums))

    return Interface(name=name, properties=properties)


# ── Recursive interface collection ────────────────────────────────────

def _collect_interfaces(
    text: str,
    root_interfaces: list[str],
    known_interfaces: set[str],
    known_enums: set[str],
) -> dict[str, Interface]:
    """Parse all interfaces reachable from the root set, recursively."""
    result: dict[str, Interface] = {}
    queue = list(root_interfaces)

    while queue:
        name = queue.pop(0)
        if name in result:
            continue

        iface = _parse_interface(text, name, known_interfaces, known_enums)
        if iface is None:
            raise ValueError(f"Interface '{name}' not found in .d.ts — IR is incomplete")

        result[name] = iface

        # Queue any referenced interfaces we haven't parsed yet (skip deferred)
        for prop in iface.properties:
            if prop.ir_type == "array" and prop.item_interface not in result and prop.item_interface not in _DEFERRED_INTERFACES:
                queue.append(prop.item_interface)
            elif prop.ir_type == "interface" and prop.interface not in result and prop.interface not in _DEFERRED_INTERFACES:
                queue.append(prop.interface)

    return result


# ── Top-level parser ──────────────────────────────────────────────────

def parse_state(dts_path: Path, openrct2_version: str, source_root: Path) -> StateIR:
    """Parse openrct2.d.ts and return a complete StateIR."""
    text = dts_path.read_text(encoding="utf-8")

    # Pass 1: collect all interface names and enum/union names
    known_interfaces = set(_INTERFACE_RE.findall(text))
    enums: dict[str, list[str]] = {}
    for match in _TYPE_UNION_RE.finditer(text):
        union_name = match.group(1)
        values = _UNION_VALUE_RE.findall(match.group(2))
        enums[union_name] = values
    known_enums = set(enums.keys())

    # Pass 2: parse interfaces reachable from our namespace roots
    root_interfaces = [ns.ts_interface for ns in _NAMESPACES]
    interfaces = _collect_interfaces(text, root_interfaces, known_interfaces, known_enums)

    # Trim enums to only those actually referenced in the collected interfaces
    referenced_enums: set[str] = set()
    for iface in interfaces.values():
        for prop in iface.properties:
            if prop.ir_type == "enum_ref":
                referenced_enums.add(prop.enum)
            elif prop.ir_type == "flags":
                referenced_enums.add(prop.flag_union)
    enums = {k: v for k, v in enums.items() if k in referenced_enums}

    api_version = parse_plugin_api_version(source_root)

    return StateIR(
        openrct2_version=openrct2_version,
        api_version=api_version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator_version=pkg_version("openrct2-actiongen"),
        namespaces=_NAMESPACES,
        interfaces=interfaces,
        enums=enums,
    )


