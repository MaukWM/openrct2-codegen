"""Probe v2: test with values past the REAL C++ enum Count sentinels.

Findings from C++ source:
- RideType: RIDE_TYPE_COUNT = 104 (indices 0-103)
- ScenarioSetSetting: Count = 23 (indices 0-22)
- ParkParameter: Count = 3 (indices 0-2)
- GameSpeed: valid range 1-4 (or 1-8 with debug tools)
"""

from pyrct2.client import RCT2


def probe(game: RCT2) -> None:
    def test(label: str, endpoint: str, params: dict) -> dict:
        r = game.execute(endpoint, params)
        ok = "OK" if r.get("success") else "ERR"
        status = r.get("status", "")
        title = r.get("title", "")
        msg = r.get("message", "")
        detail = f"status={status} title={title!r} msg={msg!r}" if not r.get("success") else ""
        print(f"  [{ok}] {label:45s} {detail}")
        return r

    print("=" * 70)
    print("PROBE v2: Testing at REAL enum boundaries from C++ source")
    print("=" * 70)

    # --- RideType: RIDE_TYPE_COUNT = 104 ---
    print("\n--- ridecreate: RIDE_TYPE_COUNT=104 ---")
    base = {"rideObject": 0, "entranceObject": 0, "colour1": 0, "colour2": 0, "inspectionInterval": 0}
    test("rideType=0 (valid)",           "ridecreate", {**base, "rideType": 0})
    test("rideType=103 (last valid)",    "ridecreate", {**base, "rideType": 103})
    test("rideType=104 (==Count, OOB)",  "ridecreate", {**base, "rideType": 104})
    test("rideType=105 (>Count)",        "ridecreate", {**base, "rideType": 105})
    test("rideType=255 (max uint8)",     "ridecreate", {**base, "rideType": 255})

    # --- ScenarioSetSetting: Count = 23 ---
    print("\n--- scenariosetsetting: Count=23 ---")
    test("setting=0 (valid)",           "scenariosetsetting", {"setting": 0, "value": 0})
    test("setting=22 (last valid)",     "scenariosetsetting", {"setting": 22, "value": 0})
    test("setting=23 (==Count, OOB)",   "scenariosetsetting", {"setting": 23, "value": 0})
    test("setting=24 (>Count)",         "scenariosetsetting", {"setting": 24, "value": 0})
    test("setting=255",                 "scenariosetsetting", {"setting": 255, "value": 0})

    # --- ParkParameter: Count = 3 ---
    print("\n--- parksetparameter: Count=3 ---")
    test("parameter=0 (valid Close)",    "parksetparameter", {"parameter": 0, "value": 1})
    test("parameter=2 (last valid)",     "parksetparameter", {"parameter": 2, "value": 1})
    test("parameter=3 (==Count, OOB)",   "parksetparameter", {"parameter": 3, "value": 1})

    # --- GameSpeed: valid 1-4 ---
    print("\n--- gamesetspeed: valid 1-4 ---")
    test("speed=1 (valid normal)",       "gamesetspeed", {"speed": 1})
    test("speed=4 (last valid)",         "gamesetspeed", {"speed": 4})
    test("speed=5 (OOB)",               "gamesetspeed", {"speed": 5})
    game.execute("gamesetspeed", {"speed": 1})  # reset

    # --- RideSetSetting: test the enum itself ---
    # RideSetSetting enum has ~15 values
    # Need a ride first
    r = game.execute("ridecreate", {**base, "rideType": 1})
    ride_id = r.get("payload", {}).get("ride")
    if ride_id is not None:
        print(f"\n--- ridesetsetting: ride={ride_id} ---")
        test("setting=0, value=0 (valid)",  "ridesetsetting", {"ride": ride_id, "setting": 0, "value": 0})
        test("setting=50 (OOB)",            "ridesetsetting", {"ride": ride_id, "setting": 50, "value": 0})
        test("setting=255 (OOB)",           "ridesetsetting", {"ride": ride_id, "setting": 255, "value": 0})

    # --- RideSetAppearance ---
    if ride_id is not None:
        print(f"\n--- ridesetappearance: ride={ride_id} ---")
        test("type=0, value=0, index=0",    "ridesetappearance", {"ride": ride_id, "type": 0, "value": 0, "index": 0})
        test("type=50 (OOB)",               "ridesetappearance", {"ride": ride_id, "type": 50, "value": 0, "index": 0})

    # --- StaffSetPatrolArea ---
    print("\n--- staffsetpatrolarea: StaffSetPatrolAreaMode ---")
    test("mode=0 (valid)",               "staffsetpatrolarea", {"id": 0, "mode": 0, "x1": 0, "y1": 0, "x2": 32, "y2": 32})
    test("mode=50 (OOB)",               "staffsetpatrolarea", {"id": 0, "mode": 50, "x1": 0, "y1": 0, "x2": 32, "y2": 32})

    print("\n" + "=" * 70)
    print("KEY QUESTION: Do all actions return ERR for values >= Count?")
    print("=" * 70)


if __name__ == "__main__":
    try:
        game = RCT2.connect()
        print("Connected to existing instance.")
    except Exception:
        game = RCT2.launch(
            "/Users/maukmuller/Documents/rct2/Scenarios/Crazy Castle.SC6"
        ).__enter__()

    try:
        print(f"Version: {game.get_version()}")
        probe(game)
    finally:
        game.close()
