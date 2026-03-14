# openrct2-codegen

Parses OpenRCT2 source to generate action and state bindings for the `openrct2-bridge` plugin and `pyrct2` Python client.

**Two IRs, one command:**
- `actions.json` — parsed from OpenRCT2 C++ source (all 81 game actions with parameter signatures)
- `state.json` — parsed from `openrct2.d.ts` (all readable game state interfaces, enums, and unions)

Both feed Jinja2 templates that generate TypeScript plugin handlers and Python Pydantic models.

## Usage

### 1. Generate IRs

```bash
openrct2-codegen generate --openrct2-version v0.4.32
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

### Actions (`actions.json`)

Works with OpenRCT2 **v0.3.5.1+** (Nov 2021 onwards, 78–81 actions depending on version).

Versions before v0.2.6 have no plugin scripting system. Versions v0.3.0–v0.3.5 have scripting but use an older C-style enum format (`GAME_COMMAND_*`) that the parser doesn't support — v0.3.5.1 switched to `GameCommand::*` scoped enums which is what we parse.

### State (`state.json`)

Requires OpenRCT2 **v0.4.25+**. Interfaces were added incrementally:

```
v0.3.0  (2020-08-15): Park, Cheats, GameDate, ParkMessage
v0.3.1  (2020-09-27): + Scenario
v0.3.4  (2021-07-19): + Climate
v0.4.5  (2023-05-08): + Research, ResearchItem (park.research)
v0.4.20 (2025-02-25): ClimateState → WeatherState rename
v0.4.25 (2025-08-03): + Award, AwardType (park.awards)  ← minimum for full IR
```

Current target: **v0.4.32** (Plugin API v110).
