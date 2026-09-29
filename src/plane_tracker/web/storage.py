"""PostgreSQL persistence. Writes are queued, transactional and safe to replay."""

from collections import deque
from datetime import datetime, timezone
import threading
import time

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def instant(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc)


class PostgresStore:
    def __init__(self, dsn, capacity=100000):
        self.dsn = dsn
        self.capacity = capacity
        self.pending = deque()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.report = lambda message, level: None
        self.available = True
        self.dropped = 0
        self.ids = {}

    def connect(self):
        return psycopg.connect(
            self.dsn, connect_timeout=5, row_factory=dict_row, options="-c statement_timeout=15000 -c lock_timeout=5000"
        )

    def enqueue(self, kind, payload):
        with self.lock:
            if len(self.pending) >= self.capacity:
                # Preserve already accepted records; explicitly report rejected new events.
                self.dropped += 1
                if self.dropped == 1 or self.dropped % 1000 == 0:
                    self.report("Database write buffer full; new records are being lost", "warning")
                return False
            self.pending.append((kind, payload))
        return True

    def status(self):
        with self.lock:
            return {"available": self.available, "pending": len(self.pending), "dropped": self.dropped}

    def _aircraft_id(self, cur, icao, epoch):
        if icao not in self.ids:
            cur.execute(
                """INSERT INTO aircraft(icao,first_seen,last_seen) VALUES(%s,%s,%s)
                ON CONFLICT(icao) DO UPDATE SET icao=EXCLUDED.icao RETURNING id""",
                (icao, instant(epoch), instant(epoch)),
            )
            self.ids[icao] = cur.fetchone()["id"]
        return self.ids[icao]

    def write(self, events):
        try:
            with self.connect() as conn:
                with conn.cursor() as cur:
                    for kind, p in events:
                        if kind == "aircraft":
                            ident = self._aircraft_id(cur, p["icao"], p["time"])
                            row, meta = p["row"], p["metadata"]
                            cur.execute(
                                """UPDATE aircraft SET
                                last_seen=GREATEST(last_seen,%s),
                                last_position_at=GREATEST(last_position_at,%s),
                                manufacturer=COALESCE(%s,manufacturer),model=COALESCE(%s,model),
                                owner=COALESCE(%s,owner),registration=COALESCE(%s,registration),
                                callsign=%s,latitude=%s,longitude=%s,altitude_ft=%s,speed_kt=%s,
                                latest=%s,stats_date=%s,daily=%s,metadata_retry_at=%s WHERE id=%s""",
                                (
                                    instant(p["time"]),
                                    instant(row["lastPositionTime"]) if row.get("lastPositionTime") else None,
                                    meta.get("manufacturer"),
                                    meta.get("model"),
                                    meta.get("owner"),
                                    meta.get("registration"),
                                    row.get("flight"),
                                    row.get("lat"),
                                    row.get("lon"),
                                    p["latest"].get("altitude"),
                                    p["latest"].get("speed"),
                                    Jsonb(p["latest"]),
                                    p["day"],
                                    Jsonb(row),
                                    instant(p["retry"]) if p.get("retry") else None,
                                    ident,
                                ),
                            )
                        elif kind == "position":
                            ident = self._aircraft_id(cur, p["icao"], p["received"])
                            cur.execute(
                                """WITH inserted AS (INSERT INTO aircraft_positions
                                (aircraft_id,observed_at,received_at,latitude,longitude,altitude_ft,
                                 speed_kt,distance_km,bearing_deg,details)
                                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                ON CONFLICT(aircraft_id,observed_at) DO NOTHING
                                RETURNING aircraft_id,received_at,observed_at)
                                UPDATE aircraft a SET position_messages=a.position_messages+1,
                                first_seen=LEAST(a.first_seen,i.received_at),
                                last_seen=GREATEST(a.last_seen,i.received_at),
                                last_position_at=GREATEST(a.last_position_at,i.observed_at)
                                FROM inserted i WHERE a.id=i.aircraft_id""",
                                (
                                    ident,
                                    instant(p["position_time"]),
                                    instant(p["received"]),
                                    p["lat"],
                                    p["lon"],
                                    p.get("altitude"),
                                    p.get("speed"),
                                    p.get("distance"),
                                    p.get("bearing"),
                                    Jsonb(p),
                                ),
                            )
                        elif kind == "sample":
                            cur.execute(
                                """INSERT INTO tracker_samples VALUES(%s,%s,%s,%s,%s)
                                ON CONFLICT(sampled_at) DO NOTHING""",
                                (instant(p["timestamp"]), p["active"], p["total"], p["status"], Jsonb(p)),
                            )
                        elif kind == "performance":
                            cur.execute(
                                """INSERT INTO performance_stats VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                ON CONFLICT(sampled_at) DO NOTHING""",
                                (
                                    instant(p["timestamp"]),
                                    p.get("cpu"),
                                    p.get("memory"),
                                    p.get("diskUsed"),
                                    p.get("temperature"),
                                    p["apiCalls"],
                                    p["receiver"],
                                    p["api"],
                                    p["firebase"],
                                ),
                            )
                        elif kind == "daily":
                            s = p["summary"]
                            cur.execute(
                                """INSERT INTO tracker_stats VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                                ON CONFLICT(day) DO UPDATE SET updated_at=EXCLUDED.updated_at,
                                total_aircraft=EXCLUDED.total_aircraft,active_aircraft=EXCLUDED.active_aircraft,
                                top_airline=EXCLUDED.top_airline,top_aircraft=EXCLUDED.top_aircraft,
                                top_manufacturer=EXCLUDED.top_manufacturer,summary=EXCLUDED.summary
                                WHERE tracker_stats.updated_at <= EXCLUDED.updated_at""",
                                (
                                    p["day"],
                                    instant(p["timestamp"]),
                                    s["total"],
                                    p["active"],
                                    s["topAirline"],
                                    s["topAircraft"],
                                    s["topManufacturer"],
                                    Jsonb(s),
                                ),
                            )
                        else:
                            raise ValueError("Unknown persistence event")
        except Exception:
            # IDs created in a rolled-back transaction no longer exist.
            self.ids.clear()
            raise

    def flush(self):
        with self.lock:
            batch = list(self.pending)[:2000]
        if not batch:
            return
        try:
            self.write(batch)
        except Exception:
            if self.available:
                self.report("PostgreSQL unavailable; buffering writes and retrying", "warning")
            self.available = False
            return
        with self.lock:
            for _ in batch:
                self.pending.popleft()
        if not self.available:
            self.report("PostgreSQL connection restored", "info")
        self.available = True

    def start(self, report):
        self.report = report

        def run():
            while not self.stop_event.wait(5):
                self.flush()

        self.thread = threading.Thread(target=run, name="postgres-writer", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=25)
            if self.thread.is_alive():
                self.report("Database writer still stopping; pending RAM records may be lost", "warning")
                return
        deadline = time.monotonic() + 20
        while self.pending and time.monotonic() < deadline:
            self.flush()
            if not self.available:
                break
        if self.pending:
            self.report("Shutdown with unsaved database records in RAM", "warning")

    def restore(self, state, now):
        """Run before workers start. Never overwrite live state on reconnect."""
        from .state import local_day

        with self.connect() as conn:
            for table in ("aircraft", "aircraft_positions", "performance_stats", "tracker_stats", "tracker_samples"):
                if conn.execute("SELECT to_regclass(%s) AS table_name", (table,)).fetchone()["table_name"] is None:
                    raise RuntimeError("Run scripts/setup_database.py before starting PlaneTracker")
            for row in conn.execute("SELECT * FROM aircraft"):
                icao = row["icao"]
                self.ids[icao] = row["id"]
                state.metadata[icao] = {k: row[k] for k in ("manufacturer", "model", "owner", "registration") if row[k]}
                if row["last_position_at"]:
                    state.position_samples[icao] = row["last_position_at"].timestamp()
                if row["metadata_retry_at"]:
                    state.lookup_after[icao] = row["metadata_retry_at"].timestamp()
                if row["stats_date"] == local_day(now):
                    state.daily[icao] = row["daily"]
            # Stream the last day, rather than loading an unbounded result into memory.
            with conn.cursor(name="position_restore") as cur:
                cur.execute(
                    """SELECT a.icao,p.* FROM aircraft_positions p JOIN aircraft a ON a.id=p.aircraft_id
                    WHERE p.received_at >= %s ORDER BY p.received_at,p.id""",
                    (instant(now - 86460),),
                )
                for row in cur:
                    p = row["details"]
                    p["icao"] = row["icao"]
                    state.restore_position(p, now)
            for row in conn.execute(
                "SELECT details FROM tracker_samples WHERE sampled_at >= %s ORDER BY sampled_at",
                (instant(now - 86400),),
            ):
                state.series.append(row["details"])
        state.history_available = True
