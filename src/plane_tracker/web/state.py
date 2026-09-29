"""Read receiver data, enrich aircraft metadata, and aggregate dashboard statistics."""

from collections import Counter, deque
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import math
import re
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen

import psutil

from ..adsb.parser import parse_aircraft
from ..core.geometry import calculate_distance, calculate_bearing
from ..services.network import fetch_plane_info

POSITION_TTL = 30
SOURCE_TTL = 15
TRAIL_TTL = 1800
MAX_TRAIL_POINTS = 360
LONDON = ZoneInfo("Europe/London")
HISTORY_SECONDS = 86400


def local_day(epoch=None):
    return datetime.fromtimestamp(time.time() if epoch is None else epoch, LONDON).date()


def chart_points(points, limit=1500):
    # Keep first/last and bucket extrema; full-resolution records remain in PostgreSQL.
    values = list(points)
    if len(values) <= limit:
        return values
    size = math.ceil(len(values) / (limit // 4))
    result = []
    for i in range(0, len(values), size):
        bucket = values[i : i + size]
        candidates = [bucket[0], bucket[-1]]
        for field in ("altitude", "hits", "active", "total"):
            valid = [p for p in bucket if number(p.get(field)) is not None]
            if valid:
                candidates.extend((min(valid, key=lambda p: p[field]), max(valid, key=lambda p: p[field])))
        result.extend(sorted({p["timestamp"]: p for p in candidates}.values(), key=lambda p: p["timestamp"]))
    return result


MAX_SOURCE_BYTES = 20 * 1024 * 1024


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def text(value):
    if value is None or str(value).strip().lower() in {"", "-", "none", "nan", "unknown", "n/a", "null"}:
        return None
    return str(value).strip()


def read_source(source):
    if source.startswith(("http://", "https://")):
        request = Request(source, headers={"Accept": "application/json", "User-Agent": "PlaneTracker/1"})
        with urlopen(request, timeout=4) as response:
            raw = response.read(MAX_SOURCE_BYTES + 1)
        fallback_timestamp = None
    else:
        path = Path(source)
        with path.open("rb") as handle:
            raw = handle.read(MAX_SOURCE_BYTES + 1)
        fallback_timestamp = path.stat().st_mtime
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("Receiver response is too large")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("aircraft"), list):
        raise ValueError("Invalid receiver response")
    timestamp = number(payload.get("now", fallback_timestamp))
    if timestamp is None:
        raise ValueError("Receiver response has no valid timestamp")
    return payload, timestamp


class LiveState:
    def __init__(self, source, home, map_style, metadata_enabled=True, store=None):
        self.store = store
        self.dirty = set()
        self.last_performance_save = 0
        self.metadata_enabled = metadata_enabled
        self.metadata_thread = None
        self.lookup_after = {}
        self.api_calls = deque()
        self.api_pause_until = 0
        self.api_available = False
        self.firebase_available = False
        self.position_samples = {}
        self.series = deque()
        self.observed_hours = set()
        self.aircraft_history = {}
        self.aircraft_hits = {}
        self.polar_samples = deque()
        self.polar_totals = [0] * 36
        self.last_polar_timestamp = None
        self.source = str(source)
        self.home = tuple(home)
        self.map_style = map_style
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.tracks = {}
        self.daily = {}
        self.history = {}
        self.metadata = {}
        self.day = local_day()
        self.source_time = None
        self.received_at = None
        self.status = "waiting"
        self.events = deque(maxlen=150)
        self.event_id = 0
        self.message_rate = None
        self.previous_timestamp = None
        self.system = {"cpu": None, "memory": None, "temperature": None, "diskUsed": None}
        self.history_available = False
        self.history_error = None
        if self.store:
            self.store.restore(self, time.time())
        self._event("Waiting for receiver")

    def _event(self, message, level="info"):
        self.event_id += 1
        self.events.appendleft({"id": self.event_id, "time": time.time(), "level": level, "message": message})

    def _roll_day(self, day):
        if self.day != day:
            self.save_daily()
            self.day = day
            self.daily = {}
            self.history = {}
            self.dirty.clear()
            self.observed_hours.clear()

    def save_daily(self):
        if not self.store:
            return
        with self.lock:
            for icao in list(self.dirty):
                row = self.daily.get(icao)
                if row is None:
                    continue
                latest = {k: v for k, v in self.tracks.get(icao, row).items() if k != "trail"}
                payload = {
                    "icao": icao,
                    "time": latest.get("position_time", time.time()),
                    "row": dict(row),
                    "latest": latest,
                    "day": self.day.isoformat(),
                    "metadata": dict(self.metadata.get(icao, {})),
                    "retry": self.lookup_after.get(icao),
                }
                for key in ("manufacturer", "model", "owner", "registration"):
                    if text(row.get(key)) and not text(payload["metadata"].get(key)):
                        payload["metadata"][key] = text(row[key])
                if self.store.enqueue("aircraft", payload):
                    self.dirty.discard(icao)
            self.store.enqueue(
                "daily",
                {
                    "day": self.day.isoformat(),
                    "timestamp": time.time(),
                    "active": sum(time.time() - p["position_time"] <= POSITION_TTL for p in self.tracks.values()),
                    "summary": self._summary(),
                },
            )

    def reload_history(self, now=None):
        # Compatibility for old callers; runtime persistence no longer reads CSV or JSON.
        with self.lock:
            self._roll_day(local_day(now.timestamp() if now else None))

    def restore_position(self, p, now):
        icao, timestamp = p["icao"], p["received"]
        self.position_samples[icao] = max(self.position_samples.get(icao, 0), p["position_time"])
        if local_day(timestamp) == self.day:
            row = self.daily.setdefault(icao, {})
            # Recover positions committed just before a crash, before the periodic aircraft upsert.
            if p["position_time"] > (number(row.get("lastPositionTime")) or 0):
                previous = dict(row)
                row.update({k: v for k, v in p.items() if k not in ("received", "bearing")})
                row["positionHits"] = int(number(previous.get("positionHits")) or 0) + int(
                    local_day(p["position_time"]) == self.day
                )
                row["lastPositionTime"] = p["position_time"]
                row.setdefault("nearHours", [])
                for key in ("altitude", "speed", "distance"):
                    vals = [v for v in (number(previous.get(key)), number(p.get(key))) if v is not None]
                    row[key] = max(vals) if vals else None
                row.update(self.metadata.get(icao, {}))
                self.dirty.add(icao)
        recent = self.aircraft_hits.setdefault(icao, deque())
        recent.append(timestamp)
        while recent and timestamp - recent[0] >= 60:
            recent.popleft()
        if timestamp >= now - HISTORY_SECONDS:
            self.aircraft_history.setdefault(icao, deque()).append(
                {"timestamp": timestamp, "altitude": p.get("altitude"), "hits": len(recent)}
            )
            bins = [0] * 36
            if p.get("bearing") is not None:
                bins[int((p["bearing"] + 5) // 10) % 36] = 1
            self._append_polar(timestamp, bins)
        if now - p["position_time"] <= TRAIL_TTL:
            track = dict(p)
            track.update(self.metadata.get(icao, {}))
            for key in ("manufacturer", "model", "owner", "registration", "flight", "track", "baro_rate", "squawk"):
                track.setdefault(key, None)
            old = self.tracks.get(icao, {})
            trail = old.get("trail", deque(maxlen=MAX_TRAIL_POINTS))
            trail.append((p["position_time"], p["lon"], p["lat"]))
            track["trail"] = trail
            self.tracks[icao] = track

    def _prune(self, now):
        while self.series and now - self.series[0]["timestamp"] > HISTORY_SECONDS:
            self.series.popleft()
        for icao in list(self.aircraft_history):
            samples = self.aircraft_history[icao]
            while samples and now - samples[0]["timestamp"] > HISTORY_SECONDS:
                samples.popleft()
            if not samples:
                del self.aircraft_history[icao]
                self.aircraft_hits.pop(icao, None)

    def _record_sample(self, timestamp, active, status):
        total = len(set(self.daily) | set(self.history))
        if (
            not self.series
            or timestamp - self.series[-1]["timestamp"] >= 60
            or active != self.series[-1]["active"]
            or total != self.series[-1]["total"]
        ):
            sample = {
                "timestamp": timestamp,
                "active": active,
                "total": total,
                "status": status,
                "altitude": max(
                    (
                        number(p["altitude"])
                        for p in self.tracks.values()
                        if timestamp - p["position_time"] <= POSITION_TTL and number(p["altitude"]) is not None
                    ),
                    default=None,
                ),
                "hits": sum(sum(bins) for ts, bins in self.polar_samples if timestamp - ts < 60),
            }
            self.series.append(sample)
            if self.store:
                self.store.enqueue("sample", dict(sample))

    def ingest(self, payload, timestamp, now=None):
        now = time.time() if now is None else now
        if timestamp > now + 30:
            raise ValueError("Receiver timestamp is in the future")
        with self.lock:
            day = local_day(now)
            self._roll_day(day)
            self.source_time = timestamp
            self.received_at = now
            if now - timestamp > SOURCE_TTL:
                if self.status != "stale":
                    self._event("Receiver data is stale", "warning")
                self.status = "stale"
                self.message_rate = None
                return
            if self.status != "live":
                self._event("Receiver connected")
            self.status = "live"
            if self.previous_timestamp is not None and timestamp <= self.previous_timestamp:
                return
            elapsed = timestamp - self.previous_timestamp if self.previous_timestamp is not None else None
            self.previous_timestamp = timestamp
            self.observed_hours.add(
                datetime.fromtimestamp(now, LONDON).replace(minute=0, second=0, microsecond=0).timestamp()
            )
            hit_bins = [0] * 36
            hit_count = 0
            for raw in payload["aircraft"]:
                if not isinstance(raw, dict):
                    continue
                parsed = parse_aircraft(raw)
                if not parsed:
                    continue
                lat, lon = number(parsed["lat"]), number(parsed["lon"])
                seen = number(parsed.get("seen_pos"))
                if (
                    lat is None
                    or lon is None
                    or not (-90 <= lat <= 90 and -180 <= lon <= 180)
                    or seen is None
                    or seen < 0
                ):
                    continue
                position_time = timestamp - seen
                if now - position_time > POSITION_TTL:
                    continue
                icao = parsed["icao"]
                old = self.tracks.get(icao)
                if old and position_time < old["position_time"]:
                    continue
                previous_daily = self.daily.get(icao, {})
                last_position = self.position_samples.get(icao, number(previous_daily.get("lastPositionTime")))
                # readsb rounds seen_pos; tolerate sub-0.1s timestamp jitter.
                new_hit = last_position is None or position_time - last_position >= 0.1 - 1e-6
                today_position = local_day(position_time) == self.day
                hits = int(number(previous_daily.get("positionHits")) or 0)
                if new_hit:
                    self.position_samples[icao] = position_time
                    if today_position:
                        hits += 1
                    hit_count += 1
                    self.aircraft_hits.setdefault(icao, deque()).append(timestamp)
                    if (lat, lon) != self.home:
                        bearing = calculate_bearing(*self.home, lat, lon)
                        hit_bins[int((bearing + 5) // 10) % 36] += 1
                metadata = {k: v for k, v in self.history.get(icao, {}).items() if text(v)}
                metadata.update({k: v for k, v in self.metadata.get(icao, {}).items() if text(v)})
                for field, raw_key in (("registration", "r"), ("model", "t")):
                    if text(raw.get(raw_key)) and not text(metadata.get(field)):
                        metadata[field] = raw[raw_key]
                plane = {
                    **parsed,
                    "lat": lat,
                    "lon": lon,
                    "distance": calculate_distance(self.home[0], self.home[1], lat, lon),
                    "position_time": position_time,
                }
                for key in ("altitude", "speed", "track", "baro_rate"):
                    plane[key] = number(plane.get(key))
                for key in ("manufacturer", "model", "owner", "registration"):
                    plane[key] = text(metadata.get(key))
                trail = old["trail"] if old else deque(maxlen=MAX_TRAIL_POINTS)
                if not trail or ((lon, lat) != tuple(trail[-1][1:]) and position_time > trail[-1][0]):
                    trail.append((position_time, lon, lat))
                while trail and now - trail[0][0] > TRAIL_TTL:
                    trail.popleft()
                plane["trail"] = trail
                plane["positionHits"] = hits
                plane["lastPositionTime"] = self.position_samples.get(icao, position_time)
                self.tracks[icao] = plane
                self.dirty.add(icao)
                if new_hit and self.store:
                    position = {
                        k: plane.get(k)
                        for k in (
                            "icao",
                            "flight",
                            "lat",
                            "lon",
                            "altitude",
                            "speed",
                            "track",
                            "baro_rate",
                            "squawk",
                            "distance",
                            "position_time",
                        )
                    }
                    for key in ("altitude", "speed", "track", "baro_rate"):
                        position[key] = number(position.get(key))
                    position.update(
                        icao=icao,
                        received=timestamp,
                        bearing=calculate_bearing(*self.home, lat, lon) if (lat, lon) != self.home else None,
                    )
                    self.store.enqueue("position", position)
                recent_hits = self.aircraft_hits.setdefault(icao, deque())
                while recent_hits and timestamp - recent_hits[0] >= 60:
                    recent_hits.popleft()
                samples = self.aircraft_history.setdefault(icao, deque())
                while samples and timestamp - samples[0]["timestamp"] > HISTORY_SECONDS:
                    samples.popleft()
                if (
                    not samples
                    or number(plane["altitude"]) != samples[-1]["altitude"]
                    or len(recent_hits) != samples[-1]["hits"]
                    or timestamp - samples[-1]["timestamp"] >= 60
                ):
                    samples.append(
                        {"timestamp": timestamp, "altitude": number(plane["altitude"]), "hits": len(recent_hits)}
                    )
                if icao not in self.daily and icao not in self.history:
                    self._event(f"{text(plane['flight']) or icao} detected", "new")
                previous = self.daily.get(icao, self.history.get(icao, {}))
                daily = {k: v for k, v in plane.items() if k != "trail"}
                for key in ("altitude", "speed", "distance"):
                    values = [
                        value for value in (number(previous.get(key)), number(plane.get(key))) if value is not None
                    ]
                    daily[key] = max(values) if values else None
                hours = set(previous.get("nearHours") or [])
                angular = (
                    math.sin(math.radians(lat - self.home[0]) / 2) ** 2
                    + math.cos(math.radians(lat))
                    * math.cos(math.radians(self.home[0]))
                    * math.sin(math.radians(lon - self.home[1]) / 2) ** 2
                )
                nearby = 6371 * 2 * math.asin(math.sqrt(min(1, angular))) <= 16.09344
                if nearby and today_position:
                    hours.add(
                        datetime.fromtimestamp(now, LONDON).replace(minute=0, second=0, microsecond=0).timestamp()
                    )
                daily["nearHours"] = sorted(hours)
                self.daily[icao] = daily
            self.tracks = {icao: p for icao, p in self.tracks.items() if now - p["position_time"] < TRAIL_TTL}
            self._prune(now)
            self.message_rate = round(hit_count / elapsed, 2) if elapsed and elapsed <= SOURCE_TTL else None
            self._append_polar(timestamp, hit_bins)
            self._polar(now)
            self._record_sample(
                timestamp, sum(now - p["position_time"] <= POSITION_TTL for p in self.tracks.values()), "live"
            )

    def _append_polar(self, timestamp, bins):
        if self.polar_samples and self.polar_samples[-1][0] == timestamp:
            current = self.polar_samples[-1][1]
            for i, value in enumerate(bins):
                current[i] += value
        else:
            self.polar_samples.append((timestamp, list(bins)))
        for i, value in enumerate(bins):
            self.polar_totals[i] += value

    def _polar(self, now):
        while self.polar_samples and now - self.polar_samples[0][0] >= HISTORY_SECONDS:
            _, bins = self.polar_samples.popleft()
            for i, value in enumerate(bins):
                self.polar_totals[i] -= value
        return {
            "bins": list(self.polar_totals),
            "sectorDegrees": 10,
            "windowSeconds": HISTORY_SECONDS,
            "total": sum(self.polar_totals),
        }

    def _metadata_once(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            if now < self.api_pause_until:
                return
            candidates = [
                icao
                for icao, plane in self.tracks.items()
                if now - plane["position_time"] <= POSITION_TTL
                and re.fullmatch(r"[0-9A-F]{6}", icao)
                and self.lookup_after.get(icao, 0) <= now
                and any(
                    not (text(self.metadata.get(icao, {}).get(k)) or text(plane.get(k)))
                    for k in ("model", "owner", "manufacturer", "registration")
                )
            ]
            if not candidates:
                return
            icao = min(candidates, key=lambda code: self.lookup_after.get(code, 0))
            self.lookup_after[icao] = now + 60
            self.dirty.add(icao)
            while self.api_calls and now - self.api_calls[0] >= 600:
                self.api_calls.popleft()
            self.api_calls.append(now)
        result = fetch_plane_info(icao)
        with self.lock:
            self.api_available = result is None or not result.get("last_api_error")
            if result is None:
                self.lookup_after[icao] = now + 60
                return
            if result.get("last_api_error"):
                self.api_pause_until = now + 60
                self._event("Aircraft metadata lookup failed; retrying later", "warning")
                return
            fields = {
                k: text(result.get(k))
                for k in ("manufacturer", "model", "owner", "registration")
                if text(result.get(k))
            }
            self.metadata.setdefault(icao, {}).update(fields)
            for store in (self.tracks, self.daily, self.history):
                if icao in store:
                    store[icao].update(fields)
            complete = all(text(self.metadata[icao].get(k)) for k in ("manufacturer", "model", "owner", "registration"))
            self.lookup_after[icao] = now + (86400 if complete else 60)
            self.dirty.add(icao)

    def _metadata_run(self):
        # One worker, at most one request per second; receiver polling never waits on the API.
        while not self.stop_event.is_set():
            try:
                self._metadata_once()
            except Exception:
                with self.lock:
                    self.api_available = False
                    self._event("Aircraft metadata lookup unavailable", "warning")
            self.stop_event.wait(1)

    def fail(self, message="Receiver unavailable"):
        with self.lock:
            if self.status != "unavailable":
                self._event(message, "warning")
            self.status = "unavailable"
            self.message_rate = None

    def _rows(self):
        # Merge by ICAO so history and current observations cannot double-count aircraft.
        rows = {k: dict(v) for k, v in self.history.items()}
        for icao, plane in self.daily.items():
            previous = rows.get(icao, {})
            merged = {**previous, **{k: v for k, v in plane.items() if text(v)}}
            for key in ("altitude", "speed", "distance"):
                values = [v for v in (number(previous.get(key)), number(plane.get(key))) if v is not None]
                merged[key] = max(values) if values else None
            rows[icao] = merged
        for icao, row in rows.items():
            row.update({k: v for k, v in self.metadata.get(icao, {}).items() if text(v)})
        return rows

    def _summary(self):
        rows = self._rows()
        values = list(rows.values())

        def known(key):
            return [text(row.get(key)) for row in values if text(row.get(key))]

        def top(key):
            counts = Counter(known(key))
            return min(counts, key=lambda value: (-counts[value], value.casefold())) if counts else None

        def maximum(key):
            vals = [number(row.get(key)) for row in values]
            return max((v for v in vals if v is not None), default=None)

        distances = []
        for row in values:
            distance = number(row.get("distance"))
            if distance is None:
                lat, lon = number(row.get("lat")), number(row.get("lon"))
                if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
                    distance = calculate_distance(self.home[0], self.home[1], lat, lon)
            if distance is not None:
                distances.append(distance)
        return {
            "total": len(rows),
            "airlines": len({v.casefold() for v in known("owner")}),
            "models": len({v.casefold() for v in known("model")}),
            "unknownOperators": sum(not text(row.get("owner")) for row in values),
            "unknownModels": sum(not text(row.get("model")) for row in values),
            "furthest": max(distances, default=None),
            "highest": maximum("altitude"),
            "maxSpeed": maximum("speed"),
            "maxHits": maximum("positionHits"),
            "topAirline": top("owner"),
            "topAircraft": top("model"),
            "topManufacturer": top("manufacturer"),
            "date": self.day.isoformat(),
            "historyAvailable": self.history_available,
            "historyError": bool(self.history_error),
        }

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self._roll_day(local_day(now))
            while self.api_calls and now - self.api_calls[0] >= 600:
                self.api_calls.popleft()
            status = self.status
            if status == "live" and (self.source_time is None or now - self.source_time > SOURCE_TTL):
                status = "stale"
            self._prune(now)
            planes = []
            if status == "live":
                for icao, p in self.tracks.items():
                    if now - p["position_time"] > POSITION_TTL:
                        continue
                    planes.append(
                        {
                            "icao": icao,
                            "callsign": text(p["flight"]) or icao,
                            "lat": p["lat"],
                            "lon": p["lon"],
                            "altitude": number(p["altitude"]),
                            "speed": number(p["speed"]),
                            "heading": number(p["track"]),
                            "verticalRate": number(p["baro_rate"]),
                            "squawk": text(p["squawk"]),
                            "positionHits": int(number(self.daily.get(icao, {}).get("positionHits")) or 0),
                            "distanceKm": p["distance"],
                            "registration": p["registration"],
                            "model": p["model"],
                            "airline": p["owner"],
                            "history": chart_points(self.aircraft_history.get(icao, [])),
                            "manufacturer": p["manufacturer"],
                            "updatedAt": p["position_time"],
                            "trail": [[lon, lat] for ts, lon, lat in p["trail"] if now - ts <= TRAIL_TTL],
                        }
                    )
            return {
                "timestamp": now,
                "receiver": {
                    "status": status,
                    "updatedAt": self.source_time,
                    "home": {"lat": self.home[0], "lon": self.home[1]},
                    "hitRate": self.message_rate if status == "live" else None,
                },
                "aircraft": planes,
                "stats": {
                    **self._summary(),
                    "metadataEnabled": self.metadata_enabled,
                    "apiAvailable": self.metadata_enabled and self.api_available,
                    "firebaseAvailable": self.firebase_available,
                    "apiCalls10Min": len(self.api_calls),
                },
                "polar": self._polar(now),
                "history": chart_points(self.series),
                "nearbyHourly": self._nearby_hourly(),
                "storage": self.store.status() if self.store else None,
                "system": dict(self.system),
                "logs": list(self.events),
            }

    def _nearby_hourly(self):
        counts = Counter(hour for row in self.daily.values() for hour in set(row.get("nearHours") or []))
        return [{"timestamp": hour, "nearby": counts[hour]} for hour in sorted(set(counts) | self.observed_hours)]

    def _health(self):
        temperature = None
        try:
            for name in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
                entries = psutil.sensors_temperatures().get(name, [])
                if entries:
                    temperature = number(entries[0].current)
                    break
        except (AttributeError, OSError):
            pass
        try:
            disk = psutil.disk_usage(str(Path.cwd().anchor))
            used = disk.percent
        except OSError:
            used = None
        with self.lock:
            self.system = {
                "cpu": psutil.cpu_percent(),
                "memory": psutil.virtual_memory().percent,
                "temperature": temperature,
                "diskUsed": used,
            }
            now = time.time()
            if self.store and now - self.last_performance_save >= 30:
                self.store.enqueue(
                    "performance",
                    {
                        **self.system,
                        "timestamp": now,
                        "apiCalls": sum(t > now - 600 for t in self.api_calls),
                        "receiver": self.status,
                        "api": self.api_available,
                        "firebase": self.firebase_available,
                    },
                )
                self.last_performance_save = now

    def _run(self):
        last_health = last_save = 0
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                payload, timestamp = read_source(self.source)
                self.ingest(payload, timestamp)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self.fail("Receiver unavailable" if isinstance(exc, OSError) else "Invalid receiver data")
            with self.lock:
                self._roll_day(local_day())
                live = (
                    self.status == "live"
                    and self.source_time is not None
                    and time.time() - self.source_time <= SOURCE_TTL
                )
                self._record_sample(
                    time.time(),
                    sum(time.time() - p["position_time"] <= POSITION_TTL for p in self.tracks.values())
                    if live
                    else None,
                    "live" if live else self.status,
                )
            now = time.monotonic()
            if now - last_save >= 5:
                with self.lock:
                    self._roll_day(local_day())
                self.save_daily()
                last_save = now
            if now - last_health >= 5:
                try:
                    self._health()
                except (OSError, RuntimeError):
                    pass
                last_health = now
            self.stop_event.wait(max(0.05, 1 - (time.monotonic() - started)))

    def start(self):
        if self.store:
            # Log callback must not acquire the state lock while holding the queue lock.
            self.store.start(lambda message, level: self._event(message, level))
        self.thread = threading.Thread(target=self._run, name="web-receiver", daemon=True)
        self.thread.start()
        if self.metadata_enabled:
            self.metadata_thread = threading.Thread(target=self._metadata_run, name="web-metadata", daemon=True)
            self.metadata_thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=6)
        if self.metadata_thread is not None:
            self.metadata_thread.join(timeout=6)
        with self.lock:
            self._roll_day(local_day())
        self.save_daily()
        if self.store:
            self.store.stop()
