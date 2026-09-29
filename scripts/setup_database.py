import argparse
import os
from pathlib import Path
import sys

import psycopg

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn",
        default=os.environ.get(
            "PLANE_TRACKER_DATABASE_URL", "dbname=planetracker user=przemek host=/var/run/postgresql"
        ),
    )
    args = parser.parse_args()
    try:
        with psycopg.connect(args.dsn, autocommit=True, connect_timeout=5) as conn:
            conn.execute((ROOT / "src/plane_tracker/web/schema.sql").read_text(encoding="utf-8"))
            for table in ("aircraft", "aircraft_positions", "performance_stats", "tracker_stats", "tracker_samples"):
                print(table + ": ready")
    except Exception as exc:
        print(f"Schema setup failed ({type(exc).__name__}). Check PostgreSQL and connection settings.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
