#!/usr/bin/env python3

import json
import pprint
from datetime import datetime

READSB_JSON_PATH = "/run/readsb/aircraft.json"
OUTPUT_FILE = "/home/przemek/PlaneTracker/tests/readsb_test/readsb_test_output.txt"


def run(label, fn, f):
    separator = "=" * 60
    f.write(f"\n{separator}\n")
    f.write(f"TEST: {label}\n")
    f.write(f"{separator}\n")
    print(f"\n>>> {label}")
    try:
        result = fn()
        f.write(result + "\n")
        print(result)
    except Exception as e:
        msg = f"ERROR: {e}"
        f.write(msg + "\n")
        print(msg)


def main():
    with open(OUTPUT_FILE, "w") as f:
        f.write(f"readsb diagnostic — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Source: {READSB_JSON_PATH}\n")

        try:
            with open(READSB_JSON_PATH, "r") as jf:
                data = json.load(jf)
        except Exception as e:
            msg = f"FATAL: could not read {READSB_JSON_PATH}: {e}"
            f.write(msg + "\n")
            print(msg)
            return

        aircraft = data.get("aircraft", [])

        # ── Test 1: top-level keys in the JSON ────────────────────────────────
        def t1():
            return f"Top-level keys: {list(data.keys())}\nAircraft count: {len(aircraft)}"
        run("Top-level JSON structure", t1, f)

        # ── Test 2: all keys that appear across every aircraft entry ──────────
        def t2():
            all_keys = set()
            for a in aircraft:
                all_keys.update(a.keys())
            return "All keys seen across all aircraft:\n  " + "\n  ".join(sorted(all_keys))
        run("All aircraft keys", t2, f)

        # ── Test 3: flight / callsign field presence per aircraft ─────────────
        def t3():
            lines = []
            for a in aircraft:
                hex_code = a.get("hex", "?")
                flight = a.get("flight", "<missing>")
                callsign = a.get("callsign", "<missing>")
                lines.append(f"  {hex_code:8s}  flight={repr(flight):20s}  callsign={repr(callsign)}")
            return "\n".join(lines) if lines else "No aircraft in feed."
        run("flight / callsign field per aircraft", t3, f)

        # ── Test 4: raw dump of first 5 aircraft ──────────────────────────────
        def t4():
            out = []
            for a in aircraft[:5]:
                out.append(pprint.pformat(a))
                out.append("---")
            return "\n".join(out) if out else "No aircraft in feed."
        run("Raw dump of first 5 aircraft", t4, f)

        # ── Test 5: aircraft that have a non-empty flight field ───────────────
        def t5():
            with_flight = [a for a in aircraft if a.get("flight", "").strip()]
            lines = [f"  {a['hex']:8s}  flight={repr(a['flight'])}" for a in with_flight]
            header = f"{len(with_flight)}/{len(aircraft)} aircraft have a non-empty 'flight' field."
            return header + ("\n" + "\n".join(lines) if lines else "")
        run("Aircraft with non-empty 'flight' field", t5, f)

        f.write(f"\n{'=' * 60}\nDone.\n")

    print(f"\nOutput written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
