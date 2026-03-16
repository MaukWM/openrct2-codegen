"""Probe: does OpenRCT2 return a distinguishable error for out-of-range enum values?

All tests use raw game.execute() to bypass Pydantic validation on the Python side.
We want to see what the GAME ENGINE does with bad values.

Tests per action:
  - Valid enum value → expect success
  - Max enum value + 1 → does game reject or silently accept?
  - Absurdly large value → expect game_error
"""

from pyrct2.client import RCT2

SCENARIO = "/Users/maukmuller/Documents/rct2/Scenarios/Crazy Castle.SC6"


def probe(game: RCT2) -> None:
    print("=" * 60)
    print("PROBE: Does OpenRCT2 reject out-of-range enum values?")
    print("=" * 60)

    # --- Create a ride first (needed for ride_set_status tests) ---
    print("\n[setup] Creating a ride via raw execute...")
    result = game.execute("ridecreate", {
        "rideType": 1, "rideObject": 0, "entranceObject": 0,
        "colour1": 0, "colour2": 0, "inspectionInterval": 0,
    })
    print(f"    {result}")
    ride_id = result.get("payload", {}).get("ride") if result.get("success") else None
    print(f"    ride_id={ride_id}")

    # --- ride_set_status: RideStatus enum (Closed=0, Open=1, Testing=2) ---
    if ride_id is not None:
        print("\n--- ride_set_status (RideStatus: 0=Closed, 1=Open, 2=Testing) ---")
        for label, status in [("valid=1 (Open)", 1), ("one-past-max=3", 3), ("absurd=99", 99)]:
            r = game.execute("ridesetstatus", {"ride": ride_id, "status": status})
            ok = "OK" if r.get("success") else "ERR"
            print(f"  [{ok}] status={status:3d} ({label:20s}) → {r}")

    # --- setcheat: CheatType enum (0..~55) ---
    print("\n--- setcheat (CheatType: 0=SandboxMode, max≈55) ---")
    for label, cheat_type in [("valid=0 (SandboxMode)", 0), ("valid=1 (DisableSupportLimits)", 1),
                               ("one-past-max=60", 60), ("absurd=999", 999)]:
        r = game.execute("setcheat", {"type": cheat_type, "param1": 1, "param2": 0})
        ok = "OK" if r.get("success") else "ERR"
        print(f"  [{ok}] type={cheat_type:3d} ({label:35s}) → {r}")

    # --- parksetparameter: ParkParameter (Close=0, Open=1, SamePriceInPark=2) ---
    print("\n--- parksetparameter (ParkParameter: 0=Close, 1=Open, 2=SamePriceInPark) ---")
    for label, param in [("valid=1 (Open)", 1), ("one-past-max=3", 3), ("absurd=99", 99)]:
        r = game.execute("parksetparameter", {"parameter": param, "value": 1})
        ok = "OK" if r.get("success") else "ERR"
        print(f"  [{ok}] parameter={param:3d} ({label:20s}) → {r}")

    # --- gamesetspeed: GameSpeed (1=normal, 2=fast, 3=faster, 4=fastest) ---
    print("\n--- gamesetspeed (GameSpeed: 1-4 valid range) ---")
    for label, speed in [("valid=1 (normal)", 1), ("one-past-max=5", 5), ("absurd=99", 99)]:
        r = game.execute("gamesetspeed", {"speed": speed})
        ok = "OK" if r.get("success") else "ERR"
        print(f"  [{ok}] speed={speed:3d} ({label:20s}) → {r}")
    # Reset to normal
    game.execute("gamesetspeed", {"speed": 1})

    # --- ridecreate: RideType (0..~90) ---
    print("\n--- ridecreate (RideType: 0..~90) ---")
    for label, rt in [("valid=0", 0), ("valid=1", 1), ("one-past-max=100", 100), ("absurd=999", 999)]:
        r = game.execute("ridecreate", {
            "rideType": rt, "rideObject": 0, "entranceObject": 0,
            "colour1": 0, "colour2": 0, "inspectionInterval": 0,
        })
        ok = "OK" if r.get("success") else "ERR"
        print(f"  [{ok}] rideType={rt:3d} ({label:20s}) → {r}")

    # --- scenariosetsetting: ScenarioSetSetting (0..~10) ---
    print("\n--- scenariosetsetting (ScenarioSetSetting enum) ---")
    for label, setting in [("valid=0", 0), ("valid=1", 1), ("one-past-max=20", 20), ("absurd=999", 999)]:
        r = game.execute("scenariosetsetting", {"setting": setting, "value": 0})
        ok = "OK" if r.get("success") else "ERR"
        print(f"  [{ok}] setting={setting:3d} ({label:20s}) → {r}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("Look for pattern: do invalid values return success:false with")
    print("error='game_error', or do they silently succeed?")


if __name__ == "__main__":
    try:
        game = RCT2.connect()
        print("Connected to existing instance.")
    except Exception:
        print("No existing instance, launching...")
        game = RCT2.launch(SCENARIO).__enter__()

    try:
        print(f"Version: {game.get_version()}")
        print(f"Status:  {game.get_status()}")
        probe(game)
    finally:
        game.close()
