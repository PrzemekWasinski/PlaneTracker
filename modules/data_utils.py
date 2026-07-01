import ast
import csv
import os
import time
from collections import Counter
from datetime import datetime
from time import localtime, strftime

from .core_utils import calculate_distance, clean_string


def parse_aircraft(aircraft):
    hex_code = aircraft.get("hex", "").upper().strip()
    if not hex_code:
        return None

    lat = aircraft.get("lat")
    lon = aircraft.get("lon")
    if lat is None or lon is None:
        lat = "-"
        lon = "-"
    else:
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            lat = "-"
            lon = "-"

    altitude = aircraft.get("alt_baro")
    if altitude is None:
        altitude = aircraft.get("alt_geom")
    if altitude is not None:
        try:
            altitude = int(altitude)
        except (TypeError, ValueError):
            altitude = "-"
    else:
        altitude = "-"

    speed = aircraft.get("gs")
    if speed is not None:
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            speed = "-"
    else:
        speed = "-"

    track = aircraft.get("track")
    if track is not None:
        try:
            track = float(track)
        except (TypeError, ValueError):
            track = "-"
    else:
        track = "-"

    flight = aircraft.get("flight", "-")
    if flight is not None:
        flight = str(flight).strip() or "-"
    else:
        flight = "-"

    baro_rate = aircraft.get("baro_rate")
    if baro_rate is not None:
        try:
            baro_rate = int(baro_rate)
        except (TypeError, ValueError):
            baro_rate = "-"
    else:
        baro_rate = "-"

    def _num(val, cast=float):
        if val is None:
            return "-"
        try:
            return cast(val)
        except (TypeError, ValueError):
            return "-"

    return {
        'icao': hex_code,
        'flight': flight,
        'squawk': aircraft.get('squawk') or '-',
        'category': aircraft.get('category') or '-',
        'emergency': aircraft.get('emergency') or '-',
        'altitude': altitude,
        'alt_geom': _num(aircraft.get('alt_geom'), int),
        'baro_rate': baro_rate,
        'geom_rate': _num(aircraft.get('geom_rate'), int),
        'speed': speed,
        'ias': _num(aircraft.get('ias'), int),
        'tas': _num(aircraft.get('tas'), int),
        'mach': _num(aircraft.get('mach')),
        'track': track,
        'track_rate': _num(aircraft.get('track_rate')),
        'mag_heading': _num(aircraft.get('mag_heading')),
        'true_heading': _num(aircraft.get('true_heading')),
        'nav_heading': _num(aircraft.get('nav_heading')),
        'nav_altitude_fms': _num(aircraft.get('nav_altitude_fms'), int),
        'nav_altitude_mcp': _num(aircraft.get('nav_altitude_mcp'), int),
        'nav_qnh': _num(aircraft.get('nav_qnh')),
        'nav_modes': str(aircraft.get('nav_modes') or '-'),
        'roll': _num(aircraft.get('roll')),
        'oat': _num(aircraft.get('oat'), int),
        'tat': _num(aircraft.get('tat'), int),
        'wd': _num(aircraft.get('wd'), int),
        'ws': _num(aircraft.get('ws'), int),
        'rssi': _num(aircraft.get('rssi')),
        'seen': _num(aircraft.get('seen')),
        'seen_pos': _num(aircraft.get('seen_pos')),
        'messages': _num(aircraft.get('messages'), int),
        'lat': lat,
        'lon': lon,
        'manufacturer': '-',
        'registration': '-',
        'owner': '-',
        'model': '-',
        'icao_type_code': '-',
        'code_mode_s': '-',
        'operator_flag': '-',
        'spotted_at': datetime.now().strftime('%H:%M:%S'),
        'last_update_time': time.time(),
    }


_STATS_NUMERIC_COLS = [
    "altitude", "alt_geom", "speed", "mach", "baro_rate", "geom_rate",
    "ias", "tas", "lat", "lon", "messages", "rssi", "roll", "oat", "tat",
]


def get_stats(home_lat=None, home_lon=None, flight_history_dir='./flight_history'):
    import pandas as pd
    import glob as _glob

    today = datetime.today().strftime('%Y-%m-%d')
    csv_path_today = os.path.join(flight_history_dir, f'{today}.csv')

    default_stats = {
        'total': 0,
        'top_model': {'name': None, 'count': 0},
        'top_manufacturer': {'name': None, 'count': 0},
        'top_aircraft': {'name': None, 'count': 0},
        'top_airline': {'name': None, 'count': 0},
        'manufacturer_breakdown': {},
        'furthest_detected': None,
        'furthest_plane': None,
        'highest_detected': None,
        'unique_airlines': 0,
        'unique_models': 0,
        'unique_manufacturers': 0,
        'emergencies_count': 0,
        'avg_altitude': None,
        'avg_speed': None,
        'max_speed': None,
        'avg_mach': None,
        'last_updated': strftime('%H:%M:%S', localtime()),
    }

    if os.path.exists(csv_path_today):
        csv_path = csv_path_today
    else:
        all_files = sorted(_glob.glob(os.path.join(flight_history_dir, '????-??-??.csv')))
        if not all_files:
            return default_stats
        csv_path = all_files[-1]

    try:
        df = pd.read_csv(csv_path, low_memory=False)

        # Coerce numeric columns exactly as stats.py does
        for col in _STATS_NUMERIC_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].replace("-", pd.NA), errors="coerce")

        # Parse timestamps exactly as stats.py does
        for col in ("first_seen", "last_seen"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

        # Clean string columns exactly as stats.py does
        for col in ("owner", "manufacturer", "model", "category", "emergency", "registration"):
            if col in df.columns:
                df[col] = df[col].replace(["-", "none", "None", ""], pd.NA)

        # Deduplicate exactly as stats.py does
        if "icao" in df.columns and "first_seen" in df.columns:
            df = df.drop_duplicates(subset=["icao", "first_seen"])

        total = len(df)

        def _top(series):
            counts = series.dropna().value_counts()
            if counts.empty:
                return None, 0
            return counts.index[0], int(counts.iloc[0])

        top_model_name, top_model_count = _top(df['model']) if 'model' in df.columns else (None, 0)
        top_mfr_name, top_mfr_count = _top(df['manufacturer']) if 'manufacturer' in df.columns else (None, 0)
        top_airline_name, top_airline_count = _top(df['owner']) if 'owner' in df.columns else (None, 0)

        # Find the manufacturer for the top model from a matching row, so the
        # top aircraft is a real manufacturer/model pairing rather than two
        # independently-computed tops
        top_aircraft_name, top_aircraft_count = (None, 0)
        if top_model_name is not None and 'manufacturer' in df.columns:
            matching_rows = df.loc[df['model'] == top_model_name, 'manufacturer'].dropna()
            if not matching_rows.empty:
                top_aircraft_name = f"{matching_rows.iloc[0]} {top_model_name}"
                top_aircraft_count = top_model_count

        mfr_breakdown = {}
        if 'manufacturer' in df.columns:
            mfr_breakdown = {
                clean_string(str(k)): int(v)
                for k, v in df['manufacturer'].dropna().value_counts().items()
            }

        unique_airlines = int(df['owner'].nunique()) if 'owner' in df.columns else 0
        unique_models = int(df['model'].nunique()) if 'model' in df.columns else 0
        unique_manufacturers = int(df['manufacturer'].nunique()) if 'manufacturer' in df.columns else 0
        emergencies_count = int(df['emergency'].notna().sum()) if 'emergency' in df.columns else 0

        avg_altitude = None
        highest = None
        if 'altitude' in df.columns:
            val = df['altitude'].mean()
            if pd.notna(val):
                avg_altitude = int(round(float(val)))
            alt_max = df['altitude'].max()
            if pd.notna(alt_max):
                highest = int(alt_max)

        avg_speed = None
        max_speed = None
        if 'speed' in df.columns:
            val = df['speed'].mean()
            if pd.notna(val):
                avg_speed = int(round(float(val)))
            val = df['speed'].max()
            if pd.notna(val):
                max_speed = int(round(float(val)))

        avg_mach = None
        if 'mach' in df.columns:
            val = df['mach'].mean()
            if pd.notna(val):
                avg_mach = round(float(val), 3)

        furthest = None
        furthest_plane = None
        if home_lat is not None and home_lon is not None and 'lat' in df.columns and 'lon' in df.columns:
            valid = df[df['lat'].notna() & df['lon'].notna()]
            best = 0.0
            best_row = None
            for _, row in valid.iterrows():
                try:
                    d = calculate_distance(float(home_lat), float(home_lon), row['lat'], row['lon'])
                    if d > best:
                        best = d
                        best_row = row
                except (ValueError, TypeError):
                    pass
            if best > 0:
                furthest = best
                if best_row is not None:
                    furthest_plane = {
                        'icao': str(best_row.get('icao', '-')),
                        'flight': str(best_row.get('flight', '-')),
                        'model': str(best_row.get('model', '-')),
                        'airline': str(best_row.get('owner', '-')),
                        'distance_km': round(best, 2),
                    }

        return {
            'total': total,
            'top_model': {'name': top_model_name, 'count': top_model_count},
            'top_manufacturer': {'name': top_mfr_name, 'count': top_mfr_count},
            'top_aircraft': {'name': top_aircraft_name, 'count': top_aircraft_count},
            'top_airline': {'name': top_airline_name, 'count': top_airline_count},
            'manufacturer_breakdown': mfr_breakdown,
            'furthest_detected': furthest,
            'furthest_plane': furthest_plane,
            'highest_detected': highest,
            'unique_airlines': unique_airlines,
            'unique_models': unique_models,
            'unique_manufacturers': unique_manufacturers,
            'emergencies_count': emergencies_count,
            'avg_altitude': avg_altitude,
            'avg_speed': avg_speed,
            'max_speed': max_speed,
            'avg_mach': avg_mach,
            'last_updated': strftime('%H:%M:%S', localtime()),
        }

    except Exception as e:
        print(f"Error reading stats: {e}")
        return default_stats


def prune_history(history, max_age_seconds, now=None):
    now = now or time.time()
    cutoff = now - max_age_seconds
    while history and history[0][0] < cutoff:
        history.popleft()


def append_sample(history, value, sample_interval, now=None):
    now = now or time.time()
    if sample_interval <= 0:
        history.append((now, value))
        return

    bucket_time = int(now // sample_interval) * sample_interval
    if history and history[-1][0] == bucket_time:
        history[-1] = (bucket_time, value)
    else:
        history.append((bucket_time, value))


def append_directional_hit(history, bearing_deg, sample_interval, sector_count, now=None):
    now = now or time.time()
    sector_width = 360.0 / max(1, sector_count)
    bucket_time = int(now // sample_interval) * sample_interval if sample_interval > 0 else now
    sector_index = int((bearing_deg % 360) // sector_width) % sector_count

    if history and history[-1][0] == bucket_time:
        counts = history[-1][1]
    else:
        counts = [0] * sector_count
        history.append((bucket_time, counts))

    counts[sector_index] += 1


def aggregate_directional_hits(history, sector_count, now=None, time_window_seconds=24 * 60 * 60):
    now = now or time.time()
    cutoff = now - time_window_seconds
    totals = [0] * sector_count

    for timestamp, counts in history:
        if timestamp < cutoff:
            continue
        for index, count in enumerate(counts[:sector_count]):
            totals[index] += count

    return totals


def load_today_heatmap_hits(history_dir='./flight_history', now=None):
    now = now or time.time()
    today = datetime.fromtimestamp(now).strftime('%Y-%m-%d')
    csv_path = os.path.join(history_dir, f'{today}.csv')
    heatmap_hits = []

    if not os.path.exists(csv_path):
        return heatmap_hits

    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                history_raw = row.get('location_history', '{}')
                if not history_raw or history_raw == '{}':
                    continue

                try:
                    location_history = ast.literal_eval(history_raw)
                except (ValueError, SyntaxError, TypeError):
                    continue

                if not isinstance(location_history, dict):
                    continue

                for time_key, coords in location_history.items():
                    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                        continue

                    try:
                        key_text = str(time_key)
                        if key_text.replace('.', '', 1).isdigit():
                            sample_epoch = float(key_text)
                        else:
                            sample_time = datetime.strptime(key_text, '%H:%M:%S').time()
                            sample_dt = datetime.combine(datetime.fromtimestamp(now).date(), sample_time)
                            sample_epoch = sample_dt.timestamp()
                        heatmap_hits.append((sample_epoch, float(coords[0]), float(coords[1])))
                    except (ValueError, TypeError):
                        continue
    except (FileNotFoundError, PermissionError, OSError, csv.Error, UnicodeDecodeError):
        return heatmap_hits

    heatmap_hits.sort(key=lambda item: item[0])
    return heatmap_hits


def load_recent_heatmap_history(history_dir='./stats_history', history_seconds=24 * 60 * 60, now=None):
    now = now or time.time()
    cutoff = now - history_seconds
    heatmap_history = []

    if not os.path.isdir(history_dir):
        return heatmap_history

    for entry_name in sorted(os.listdir(history_dir)):
        if not entry_name.endswith('.csv'):
            continue
        if entry_name.startswith('graph_history_'):
            continue

        file_stem = os.path.splitext(entry_name)[0]
        try:
            file_day = datetime.strptime(file_stem, '%Y-%m-%d')
        except ValueError:
            continue

        day_start = file_day.timestamp()
        day_end = day_start + (24 * 60 * 60)
        if day_end < cutoff or day_start > now:
            continue

        csv_path = os.path.join(history_dir, entry_name)
        try:
            with open(csv_path, 'r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    icao = row.get('icao', '-') or '-'
                    history_raw = row.get('location_history', '{}')
                    if not history_raw or history_raw == '{}':
                        continue

                    try:
                        location_history = ast.literal_eval(history_raw)
                    except (ValueError, SyntaxError, TypeError):
                        continue

                    if not isinstance(location_history, dict):
                        continue

                    for time_key, coords in location_history.items():
                        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                            continue

                        try:
                            key_text = str(time_key)
                            if key_text.replace('.', '', 1).isdigit():
                                sample_epoch = float(key_text)
                            else:
                                sample_time = datetime.strptime(key_text, '%H:%M:%S').time()
                                sample_dt = datetime.combine(file_day.date(), sample_time)
                                sample_epoch = sample_dt.timestamp()
                            if sample_epoch < cutoff or sample_epoch > now:
                                continue
                            heatmap_history.append((sample_epoch, icao, float(coords[0]), float(coords[1])))
                        except (ValueError, TypeError):
                            continue
        except (FileNotFoundError, PermissionError, OSError, csv.Error, UnicodeDecodeError):
            continue

    heatmap_history.sort(key=lambda item: item[0])
    return heatmap_history


def get_top_graph_history_path(history_dir, now=None):
    return os.path.join(history_dir, 'graph_history.csv')


def load_top_graph_history(active_count_history, total_seen_history, history_dir, history_seconds, now=None):
    now = now or time.time()
    cutoff = now - history_seconds
    history_path = get_top_graph_history_path(history_dir, now)
    active_count_history.clear()
    total_seen_history.clear()
    top_graph_last_bucket = None

    if not os.path.exists(history_path):
        return top_graph_last_bucket

    try:
        with open(history_path, 'r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                try:
                    bucket_time = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S').timestamp()
                    active_value = int(row['active_count'])
                    total_value = int(row['total_seen'])
                except (KeyError, TypeError, ValueError):
                    continue

                if bucket_time < cutoff:
                    continue

                active_count_history.append((bucket_time, active_value))
                total_seen_history.append((bucket_time, total_value))

        if active_count_history:
            top_graph_last_bucket = active_count_history[-1][0]
    except (FileNotFoundError, PermissionError, OSError, csv.Error):
        pass

    prune_history(active_count_history, history_seconds, now)
    prune_history(total_seen_history, history_seconds, now)
    return top_graph_last_bucket


def clear_top_graph_history(history_dir, now=None):
    history_path = get_top_graph_history_path(history_dir, now)
    lock_path = history_path + '.lock'

    try:
        if os.path.exists(history_path):
            os.remove(history_path)
        if os.path.exists(lock_path):
            os.remove(lock_path)
        return True
    except OSError:
        return False


def persist_top_graph_sample(active_count_history, total_seen_history, active_count, total_seen, history_dir, top_graph_last_bucket, sample_interval, history_seconds, now=None):
    now = now or time.time()
    bucket_time = int(now // sample_interval) * sample_interval
    history_path = get_top_graph_history_path(history_dir, now)

    append_sample(active_count_history, active_count, sample_interval, now)
    prune_history(active_count_history, history_seconds, now)
    append_sample(total_seen_history, total_seen, sample_interval, now)
    prune_history(total_seen_history, history_seconds, now)

    if top_graph_last_bucket == bucket_time:
        return top_graph_last_bucket

    try:
        os.makedirs(history_dir, exist_ok=True)
        file_exists = os.path.exists(history_path)

        with open(history_path, 'a', newline='', encoding='utf-8') as file:
            fieldnames = ['timestamp', 'active_count', 'total_seen']
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                'timestamp': datetime.fromtimestamp(bucket_time).strftime('%Y-%m-%d %H:%M:%S'),
                'active_count': int(active_count),
                'total_seen': int(total_seen),
            })
    except (PermissionError, OSError, csv.Error):
        return top_graph_last_bucket

    return bucket_time


FLIGHT_HISTORY_FIELDS = [
    'icao', 'flight', 'squawk', 'category', 'emergency',
    'manufacturer', 'registration', 'model', 'owner', 'rating',
    'altitude', 'alt_geom', 'baro_rate', 'geom_rate',
    'speed', 'ias', 'tas', 'mach',
    'track', 'track_rate', 'mag_heading', 'true_heading', 'nav_heading',
    'nav_altitude_fms', 'nav_altitude_mcp', 'nav_qnh', 'nav_modes',
    'roll', 'oat', 'tat', 'wd', 'ws',
    'rssi', 'seen', 'seen_pos', 'messages',
    'lat', 'lon',
    'location_history',
    'first_seen', 'last_seen',
]

FLIGHT_HISTORY_DIR = './flight_history'


def save_flight_history(planes_dict, history_dir=FLIGHT_HISTORY_DIR, on_error=None):
    if not planes_dict:
        return

    today = datetime.today().strftime('%Y-%m-%d')
    csv_path = os.path.join(history_dir, f'{today}.csv')
    temp_path = csv_path + '.tmp'
    lock_path = csv_path + '.lock'
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        csv.field_size_limit(10 * 1024 * 1024)
        os.makedirs(history_dir, exist_ok=True)
        with open(lock_path, 'w') as lock_file:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                existing = {}
                if os.path.exists(csv_path):
                    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            if row.get('icao'):
                                existing[row['icao']] = row

                for icao, plane in planes_dict.items():

                    merged_history = {}
                    if icao in existing:
                        raw = existing[icao].get('location_history', '{}')
                        if raw and raw != '{}':
                            try:
                                merged_history = ast.literal_eval(raw)
                            except Exception:
                                pass

                    plane_history = plane.get('location_history', {})
                    if isinstance(plane_history, dict):
                        merged_history.update(plane_history)

                    first_seen = existing.get(icao, {}).get('first_seen') or now_str

                    existing[icao] = {
                        'icao': icao,
                        'flight': plane.get('flight', '-'),
                        'squawk': plane.get('squawk', '-'),
                        'category': plane.get('category', '-'),
                        'emergency': plane.get('emergency', '-'),
                        'manufacturer': plane.get('manufacturer', '-'),
                        'registration': plane.get('registration', '-'),
                        'model': plane.get('model', '-'),
                        'owner': plane.get('owner', '-'),
                        'rating': plane.get('rating', '-'),
                        'altitude': plane.get('altitude', '-'),
                        'alt_geom': plane.get('alt_geom', '-'),
                        'baro_rate': plane.get('baro_rate', '-'),
                        'geom_rate': plane.get('geom_rate', '-'),
                        'speed': plane.get('speed', '-'),
                        'ias': plane.get('ias', '-'),
                        'tas': plane.get('tas', '-'),
                        'mach': plane.get('mach', '-'),
                        'track': plane.get('track', '-'),
                        'track_rate': plane.get('track_rate', '-'),
                        'mag_heading': plane.get('mag_heading', '-'),
                        'true_heading': plane.get('true_heading', '-'),
                        'nav_heading': plane.get('nav_heading', '-'),
                        'nav_altitude_fms': plane.get('nav_altitude_fms', '-'),
                        'nav_altitude_mcp': plane.get('nav_altitude_mcp', '-'),
                        'nav_qnh': plane.get('nav_qnh', '-'),
                        'nav_modes': plane.get('nav_modes', '-'),
                        'roll': plane.get('roll', '-'),
                        'oat': plane.get('oat', '-'),
                        'tat': plane.get('tat', '-'),
                        'wd': plane.get('wd', '-'),
                        'ws': plane.get('ws', '-'),
                        'rssi': plane.get('rssi', '-'),
                        'seen': plane.get('seen', '-'),
                        'seen_pos': plane.get('seen_pos', '-'),
                        'messages': plane.get('messages', '-'),
                        'lat': plane.get('last_lat', plane.get('lat', '-')),
                        'lon': plane.get('last_lon', plane.get('lon', '-')),
                        'location_history': str(merged_history),
                        'first_seen': first_seen,
                        'last_seen': now_str,
                    }

                with open(temp_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=FLIGHT_HISTORY_FIELDS, extrasaction='ignore')
                    writer.writeheader()
                    for row in existing.values():
                        writer.writerow(row)
                os.replace(temp_path, csv_path)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        msg = f"Flight history save error: {e}"
        print(msg)
        if on_error:
            on_error(msg)
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def save_plane_to_csv(icao, plane_data):
    try:
        manufacturer = plane_data.get('manufacturer', '-')
        model = plane_data.get('model', '-')
        owner = plane_data.get('owner', '-')
        registration = plane_data.get('registration', '-')

        if manufacturer == '-' or model == '-' or owner == '-' or registration == '-':
            return

        stats_dir = './stats_history'
        csv_path = os.path.join(stats_dir, 'stats.csv')
        os.makedirs(stats_dir, exist_ok=True)

        lock_path = csv_path + '.lock'
        with open(lock_path, 'w') as lock_file:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

            try:
                existing_planes = {}
                if os.path.exists(csv_path):
                    with open(csv_path, 'r', newline='', encoding='utf-8') as file:
                        reader = csv.DictReader(file)
                        for row in reader:
                            if row.get('icao'):
                                existing_planes[row['icao']] = row

                full_model = f"{manufacturer} {model}".strip()
                location_history = {}
                if icao in existing_planes:
                    existing_history = existing_planes[icao].get('location_history', '{}')
                    if existing_history and existing_history != '{}':
                        try:
                            location_history = ast.literal_eval(existing_history)
                        except Exception:
                            pass

                plane_history = plane_data.get('location_history', {})
                if isinstance(plane_history, dict) and plane_history:
                    location_history.update(plane_history)
                elif plane_data['lat'] != '-' and plane_data['lon'] != '-':
                    history_key = str(plane_data.get('history_timestamp', plane_data.get('spotted_at', time.time())))
                    location_history[history_key] = [plane_data['lat'], plane_data['lon']]

                row_data = {
                    'icao': icao,
                    'manufacturer': manufacturer,
                    'model': model,
                    'full_model': full_model,
                    'airline': owner.strip(),
                    'location_history': str(location_history),
                    'altitude': plane_data.get('altitude'),
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                }

                existing_planes[icao] = row_data
                temp_path = csv_path + '.tmp'
                with open(temp_path, 'w', newline='', encoding='utf-8') as file:
                    fieldnames = ['icao', 'manufacturer', 'model', 'full_model', 'airline', 'location_history', 'altitude', 'timestamp']
                    writer = csv.DictWriter(file, fieldnames=fieldnames)
                    writer.writeheader()
                    for plane in existing_planes.values():
                        writer.writerow(plane)

                os.replace(temp_path, csv_path)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        print(f"CSV error: {e}")
        temp_path = csv_path + '.tmp' if 'csv_path' in locals() else None
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
