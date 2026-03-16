"""Comprehensive enum boundary stress test.

For every action with enum-typed parameters:
1. Send max valid enum value → expect success (or known game-state error)
2. Send max+1 → expect game_error rejection

This is exploratory — finding where OpenRCT2 does/doesn't validate.
Not a CI test.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pyrct2.client import RCT2

SCENARIO = "/Users/maukmuller/Documents/rct2/Scenarios/Crazy Castle.SC6"
IR_DIR = Path("/Users/maukmuller/Workspace/TycoonBench/openrct2-codegen/generated")


# ---------------------------------------------------------------------------
# Load IR
# ---------------------------------------------------------------------------

def load_ir():
    with open(IR_DIR / "actions.json") as f:
        actions_ir = json.load(f)
    with open(IR_DIR / "enums.json") as f:
        enums_ir = json.load(f)
    return actions_ir, enums_ir


# ---------------------------------------------------------------------------
# Build default params for each action (all zeros / empty strings)
# ---------------------------------------------------------------------------

_TYPE_DEFAULTS = {"number": 0, "boolean": False, "string": "test"}


def default_params(action: dict) -> dict:
    """Build a minimal params dict with camelCase keys and zero/false/empty defaults."""
    params = {}
    for p in action["parameters"]:
        params[p["name"]] = _TYPE_DEFAULTS[p["type"]]
    return params


# ---------------------------------------------------------------------------
# Results tracking
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    action: str
    param: str
    enum_type: str
    value: int
    label: str  # "max_valid" or "max_plus_1"
    success: bool
    error: str = ""
    title: str = ""
    message: str = ""


@dataclass
class StressResults:
    results: list[TestResult] = field(default_factory=list)

    def add(self, r: TestResult):
        self.results.append(r)

    def summary(self):
        # Group by (action, param)
        pairs: dict[tuple[str, str], list[TestResult]] = {}
        for r in self.results:
            key = (r.action, r.param)
            pairs.setdefault(key, []).append(r)

        ok = []
        problems = []
        unclear = []

        for (action, param), tests in pairs.items():
            by_label = {t.label: t for t in tests}
            mv = by_label.get("max_valid")
            mp = by_label.get("max_plus_1")

            if mp and mp.success:
                # max+1 succeeded — game didn't validate!
                problems.append((action, param, mv, mp))
            elif mv and not mv.success and mp and not mp.success:
                # Both failed — can't distinguish enum validation from game-state errors
                # Check if error messages differ
                if mv.message == mp.message and mv.title == mp.title:
                    unclear.append((action, param, mv, mp))
                else:
                    ok.append((action, param, mv, mp))
            else:
                ok.append((action, param, mv, mp))

        return ok, problems, unclear


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------

def run_stress_test(game: RCT2):
    actions_ir, enums_ir = load_ir()
    results = StressResults()

    # Pre-setup: enable sandbox mode so money/permissions don't interfere
    game.execute("cheatset", {"type": 0, "param1": 1, "param2": 0})  # SandboxMode
    # Create a ride we can reference
    r = game.execute("ridecreate", {
        "rideType": 1, "rideObject": 0, "entranceObject": 0,
        "colour1": 0, "colour2": 0, "inspectionInterval": 0,
    })
    test_ride_id = r.get("payload", {}).get("ride", 0) if r.get("success") else 0
    # Hire a staff member
    r = game.execute("staffhire", {"staffType": 0})
    test_staff_id = r.get("payload", {}).get("entityId", 0) if r.get("success") else 0

    print(f"Setup: ride_id={test_ride_id}, staff_id={test_staff_id}")
    print(f"Testing {len(actions_ir['actions'])} actions...\n")

    for action in actions_ir["actions"]:
        enum_params = [p for p in action["parameters"] if p["enum_type"]]
        if not enum_params:
            continue

        js_name = action["js_name"]

        for ep in enum_params:
            enum_name = ep["enum_type"]
            enum_def = enums_ir["enums"].get(enum_name)
            if not enum_def:
                print(f"  SKIP {js_name}.{ep['name']}: enum {enum_name} not in enums.json")
                continue

            max_val = max(v["value"] for v in enum_def["values"])

            # For flags, max valid is the OR of all flags
            if enum_def["kind"] == "flags":
                all_flags = 0
                for v in enum_def["values"]:
                    all_flags |= v["value"]
                max_val = all_flags
                oob_val = all_flags + 1  # one bit beyond
            else:
                oob_val = max_val + 1

            for test_val, label in [(max_val, "max_valid"), (oob_val, "max_plus_1")]:
                params = default_params(action)
                params[ep["name"]] = test_val

                # Inject known-good entity refs where needed
                if "ride" in params:
                    params["ride"] = test_ride_id
                if "id" in params and js_name in ("staffsetpatrolarea", "peeppickup"):
                    params["id"] = test_staff_id

                resp = game.execute(js_name, params)
                success = resp.get("success", False)
                tr = TestResult(
                    action=js_name,
                    param=ep["name"],
                    enum_type=enum_name,
                    value=test_val,
                    label=label,
                    success=success,
                    error=resp.get("error", ""),
                    title=resp.get("title", ""),
                    message=resp.get("message", ""),
                )
                results.add(tr)

                tag = "OK" if success else "ERR"
                print(f"  [{tag}] {js_name:35s} {ep['name']:20s} = {test_val:6d} ({label:12s}) "
                      f"{tr.title} {tr.message}")

    # --- Summary ---
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    ok, problems, unclear = results.summary()

    if problems:
        print(f"\n## VALIDATION GAPS ({len(problems)}) — max+1 was ACCEPTED ##")
        for action, param, mv, mp in problems:
            print(f"  {action:35s} {param:20s} {mp.enum_type:25s} "
                  f"val={mp.value} accepted!")
    else:
        print("\nNo validation gaps found — all max+1 values were rejected!")

    if unclear:
        print(f"\n## UNCLEAR ({len(unclear)}) — both max_valid and max+1 failed with same error ##")
        for action, param, mv, mp in unclear:
            print(f"  {action:35s} {param:20s} {mv.enum_type:25s} "
                  f"both failed: {mv.title!r} / {mv.message!r}")

    print(f"\n## CLEAN ({len(ok)}) — validation works as expected ##")
    # Just count, don't dump all

    print(f"\nTotals: {len(ok)} clean, {len(problems)} gaps, {len(unclear)} unclear")


if __name__ == "__main__":
    try:
        game = RCT2.connect()
        print("Connected to existing instance.")
    except Exception:
        print("No existing instance, launching...")
        game = RCT2.launch(SCENARIO).__enter__()

    try:
        print(f"Version: {game.get_version()}")
        run_stress_test(game)
    finally:
        game.close()
