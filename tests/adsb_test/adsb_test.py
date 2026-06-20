#!/usr/bin/env python3

import json
import time

while True:
    try:
        with open("/run/readsb/aircraft.json", "r") as f:
            data = json.load(f)

        aircraft = data.get("aircraft", [])

        print(f"\nAircraft visible: {len(aircraft)}")
        print("=" * 80)

        for plane in aircraft:
            print(json.dumps(plane, indent=2, sort_keys=True))
            print("-" * 80)

    except Exception as e:
        print("Error:", e)

    time.sleep(1)