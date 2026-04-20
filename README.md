# openrct2-codegen

Parses OpenRCT2 source to generate action and state bindings for the `openrct2-bridge` plugin and `pyrct2` Python client.

**Three IRs, one command:**
- `actions.json` — parsed from OpenRCT2 C++ source (all 81 game actions with parameter signatures)
- `state.json` — parsed from `openrct2.d.ts` (all readable game state interfaces, enums, and unions)
- `enums.json` — parsed from OpenRCT2 C++ headers (integer→name mappings for ~30 numeric enum types)

All three feed Jinja2 templates that generate TypeScript plugin handlers and Python Pydantic models.

## Usage

### 1. Generate IRs

```bash
openrct2-codegen generate --openrct2-version v0.5.0
# → generated/actions.json
# → generated/state.json
```

Downloads the OpenRCT2 source for the given version (sparse clone, cached at `~/.cache/openrct2-codegen/`). Pass `--openrct2-source /path/to/OpenRCT2` to use a local checkout instead.

### 2. Render templates

```bash
# Render to generated/ for inspection
openrct2-codegen render --template actions.ts
openrct2-codegen render --template actions.py

# Render directly to target repo
openrct2-codegen render --template actions.ts --out ../openrct2-bridge/src/actions.ts
openrct2-codegen render --template actions.py --out ../pyrct2/pyrct2/_generated/actions.py
```

`--ir` defaults to `generated/actions.json`. All output defaults to `generated/<template>`.


## Version compatibility

Codegen targets a single OpenRCT2 version at a time. Currently: **v0.5.0** (Plugin API v111).

You can pass older version tags to `--openrct2-version`, but no support is offered — file paths and enum definitions move between releases, so the parser may fail or produce incomplete output.
