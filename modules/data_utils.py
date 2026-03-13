import ast
import csv
import os
import time
from collections import Counter
from datetime import datetime
from time import localtime, strftime

from .core_utils import calculate_distance, clean_string


def split_message(message):
    plane_info = message.split(',')

    if len(plane_info) < 15 or plane_info[0] != 'MSG':
        return None

    try:
        lat = float(plane_info[14])
        lon = float(plane_info[15])
    except (ValueError, IndexError):
        lat = '-'
        lon = '-'

    try:
        altitude = int(plane_info[11])
    except (ValueError, IndexError):
        altitude = '-'

    try:
        speed = float(plane_info[12])
    except (ValueError, IndexError):
        speed = '-'

    try:
        track = float(plane_info[13])
    except (ValueError, IndexError):
        track = '-'

    return {
        'icao': plane_info[4] or '-',
        'altitude': altitude,
        'speed': speed,
        'track': track,
        'lat': lat,
        'lon': lon,
        'manufacturer': '-',
        'registration': '-',
        'icao_type_code': '-',
        'code_mode_s': '-',
        'operator_flag': '-',
        'owner': '-',
        'model': '-',
        'spotted_at': datetime.now().strftime('%H:%M:%S') or '-',
        'last_update_time': time.time(),
    }


def get_stats(home_lat=None, home_lon=None):
    today = datetime.today().strftime('%Y-%m-%d')
    csv_path = os.path.join('./stats_history', f'{today}.csv')

    default_stats = {
        'total': 0,
        'top_model': {'name': None, 'count': 0},
        'top_manufacturer': {'name': None, 'count': 0},
        'top_airline': {'name': None, 'count': 0},
        'manufacturer_breakdown': {},
        'furthest_detected': None,
        'highest_detected': None,
        'last_updated': strftime('%H:%M:%S', localtime()),
    }

    if not os.path.exists(csv_path):
        return default_stats

    try:
        lock_path = csv_path + '.lock'
        with open(lock_path, 'w') as lock_file:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)

            try:
                with open(csv_path, 'r', newline='', encoding='utf-8') as file:
                    reader = csv.DictReader(file)
                    planes = []

                    highest_detected = None
                    furthest_detected = None

                    for row in reader:
                        altitude_raw = row.get('altitude', '').strip()
                        try:
                            altitude_value = int(altitude_raw)
                            if highest_detected is None or altitude_value > highest_detected:
                                highest_detected = altitude_value
                        except (TypeError, ValueError, AttributeError):
                            pass

                        icao = row.get('icao', '-') or '-'
                        history_raw = row.get('location_history', '{}')
                        if home_lat is not None and home_lon is not None and history_raw and history_raw != '{}':
                            try:
                                location_history = ast.literal_eval(history_raw)
                                for coords in location_history.values():
                                    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                                        continue
                                    distance_km = calculate_distance(float(home_lat), float(home_lon), float(coords[0]), float(coords[1]))
                                    if furthest_detected is None or distance_km > furthest_detected:
                                        furthest_detected = distance_km
                            except (ValueError, SyntaxError, TypeError):
                                pass

                        if not row.get('icao'):
                            continue

                        manufacturer = row.get('manufacturer', '').strip()
                        model = row.get('model', '').strip()
                        airline = row.get('airline', '').strip()

                        if not manufacturer or not model or not airline or manufacturer == '-' or model == '-' or airline == '-':
                            continue

                        planes.append({
                            'manufacturer': manufacturer,
                            'model': model,
                            'airline': airline,
                        })
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

        if not planes:
            default_stats['furthest_detected'] = furthest_detected
            default_stats['highest_detected'] = highest_detected
            return default_stats

        model_counter = Counter(p['model'] for p in planes)
        manufacturer_counter = Counter(p['manufacturer'] for p in planes)
        airline_counter = Counter(p['airline'] for p in planes)

        top_model = model_counter.most_common(1)[0] if model_counter else (None, 0)
        top_manufacturer = manufacturer_counter.most_common(1)[0] if manufacturer_counter else (None, 0)
        top_airline = airline_counter.most_common(1)[0] if airline_counter else (None, 0)

        clean_manufacturer_breakdown = {
            clean_string(key): value for key, value in manufacturer_counter.items()
        }

        return {
            'total': len(planes),
            'top_model': {'name': top_model[0], 'count': top_model[1]},
            'top_manufacturer': {'name': top_manufacturer[0], 'count': top_manufacturer[1]},
            'top_airline': {'name': top_airline[0], 'count': top_airline[1]},
            'manufacturer_breakdown': clean_manufacturer_breakdown,
            'furthest_detected': furthest_detected,
            'highest_detected': highest_detected,
            'last_updated': strftime('%H:%M:%S', localtime()),
        }

    except (FileNotFoundError, PermissionError, csv.Error, UnicodeDecodeError) as e:
        print(f"Error reading stats file: {e}")
        return default_stats
    except Exception as e:
        print(f"Unexpected error getting stats: {e}")
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


def load_today_heatmap_hits(history_dir='./stats_history', now=None):
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
    now = datetime.fromtimestamp(now or time.time())
    return os.path.join(history_dir, f"graph_history_{now.strftime('%Y-%m-%d')}.csv")


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


def save_plane_to_csv(icao, plane_data):
    try:
        manufacturer = plane_data.get('manufacturer', '-')
        model = plane_data.get('model', '-')
        owner = plane_data.get('owner', '-')
        registration = plane_data.get('registration', '-')

        if manufacturer == '-' or model == '-' or owner == '-' or registration == '-':
            return

        today = datetime.today().strftime('%Y-%m-%d')
        stats_dir = './stats_history'
        csv_path = os.path.join(stats_dir, f'{today}.csv')
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
