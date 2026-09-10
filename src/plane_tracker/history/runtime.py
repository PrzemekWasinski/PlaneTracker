import multiprocessing
import threading
from concurrent.futures import ProcessPoolExecutor


def convert_distance_from_km(distance_km, unit):
    if distance_km in (None, '-'):
        return None
    value = float(distance_km)
    if unit == 'NM':
        return value / 1.852
    if unit == 'KM':
        return value
    return value / 1.609344


def format_distance(distance_km, unit, decimals=1):
    converted = convert_distance_from_km(distance_km, unit)
    if converted is None:
        return 'Unknown'
    suffix = unit.lower()
    return f"{round(converted, decimals)}{suffix}"


def convert_distance_to_km(distance_value, unit):
    value = float(distance_value)
    if unit == 'NM':
        return value * 1.852
    if unit == 'KM':
        return value
    return value * 1.609344


def clamp_altitude_threshold(value):
    return int(max(0, min(50000, round(value))))


def clamp_distance_threshold(distance_km):
    return max(0.0, min(1000.0, float(distance_km)))


_flight_stats_cache = {
    'total': 0,
    'top_model': {'name': None, 'count': 0},
    'top_manufacturer': {'name': None, 'count': 0},
    'top_aircraft': {'name': None, 'count': 0},
    'top_airline': {'name': None, 'count': 0},
    'manufacturer_breakdown': {},
    'furthest_detected': None,
    'highest_detected': None,
    'unique_airlines': 0,
    'unique_models': 0,
    'unique_manufacturers': 0,
    'emergencies_count': 0,
    'avg_altitude': None,
    'avg_speed': None,
    'max_speed': None,
    'max_hits': None,
    'avg_mach': None,
    'last_updated': None,
}
_flight_stats_lock = threading.Lock()
FLIGHT_STATS_REFRESH_SECONDS = 5 * 60


_flight_stats_pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))


def _update_flight_stats_cache(new_stats):
    global _flight_stats_cache
    if not new_stats or new_stats.get('total', 0) <= 0:
        return False

    with _flight_stats_lock:



        for key in ('top_model', 'top_manufacturer', 'top_aircraft', 'top_airline'):
            if not new_stats.get(key, {}).get('name') and _flight_stats_cache.get(key, {}).get('name'):
                new_stats[key] = dict(_flight_stats_cache[key])
        for key in ('unique_airlines', 'unique_models', 'unique_manufacturers'):
            if not new_stats.get(key) and _flight_stats_cache.get(key):
                new_stats[key] = _flight_stats_cache[key]
        if not new_stats.get('manufacturer_breakdown') and _flight_stats_cache.get('manufacturer_breakdown'):
            new_stats['manufacturer_breakdown'] = dict(_flight_stats_cache['manufacturer_breakdown'])
        for key in ('furthest_detected', 'furthest_plane', 'highest_detected', 'avg_altitude', 'avg_speed', 'max_speed', 'max_hits', 'avg_mach'):
            if new_stats.get(key) is None and _flight_stats_cache.get(key) is not None:
                new_stats[key] = _flight_stats_cache[key]
        _flight_stats_cache = new_stats
    return True


def _load_flight_stats():
    try:
        new_stats = _flight_stats_pool.submit(
            functions.get_stats, _config['myLat'], _config['myLon'],
            flight_history_dir=FLIGHT_HISTORY_DIR,
        ).result()
        if not _update_flight_stats_cache(new_stats):
            log.warning(f"Flight stats: get_stats returned empty (total={new_stats.get('total') if new_stats else None})")
    except Exception as e:
        log.warning(f"Flight stats refresh error: {e}", exc_info=True)


def flight_stats_refresh_thread():


    _load_flight_stats()
    while tracker_running:
        time.sleep(FLIGHT_STATS_REFRESH_SECONDS)
        _load_flight_stats()

