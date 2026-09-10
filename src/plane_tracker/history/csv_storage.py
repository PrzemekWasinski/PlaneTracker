import ast
import csv
import os
import time
from datetime import datetime


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

                    previous = existing.get(icao, {})

                    #Preserve metadata during API outages
                    def durable_value(field):
                        value = plane.get(field, '-')
                        if value is None or str(value).strip() in ('', '-', 'none', 'None'):
                            old_value = previous.get(field, '-')
                            if old_value is not None and str(old_value).strip() not in ('', '-', 'none', 'None'):
                                return old_value
                        return value

                    existing[icao] = {
                        'icao': icao,
                        'flight': plane.get('flight', '-'),
                        'squawk': plane.get('squawk', '-'),
                        'category': plane.get('category', '-'),
                        'emergency': plane.get('emergency', '-'),


                        'manufacturer': durable_value('manufacturer'),
                        'registration': durable_value('registration'),
                        'model': durable_value('model'),
                        'owner': durable_value('owner'),
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
