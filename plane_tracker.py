import json
import sys
from pathlib import Path

# Allow both ``python -m modules.gui`` and ``python modules/gui.py``.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import socket
import time
import io
import logging
import logging.handlers
from datetime import datetime
import pygame
from pygame.locals import *
from time import localtime, strftime
import psutil
import os
import threading
import math
import multiprocessing

try:
    import fcntl
except ImportError:
    fcntl = None
    
import subprocess
from collections import deque
from concurrent.futures import ProcessPoolExecutor

PROJECT_ROOT = Path(__file__).resolve().parent
IS_WINDOWS = sys.platform.startswith("win")

# When launched as a script, expose this module under its importable name so
# modules.gui shares this exact backend state instead of importing a copy.
if __name__ == "__main__":
    sys.modules.setdefault("plane_tracker", sys.modules[__name__])
DIRECT_PREVIEW = __name__ == "__main__"
DEFAULT_PREVIEW = IS_WINDOWS or DIRECT_PREVIEW or os.environ.get("PLANE_TRACKER_DEV_GUI") == "1"
os.chdir(PROJECT_ROOT)

runtime_mode = "preview" if DEFAULT_PREVIEW else "production"
_stats_uploader = None
_background_services_started = False

_log_dir = PROJECT_ROOT / "logs"
if not DEFAULT_PREVIEW:
    _log_dir.mkdir(exist_ok=True)
log = logging.getLogger("plane_tracker")
log.setLevel(logging.INFO)
_log_handler = (
    logging.NullHandler()
    if DEFAULT_PREVIEW
    else logging.handlers.RotatingFileHandler(
        _log_dir / "plane_tracker.log", maxBytes=2 * 1024 * 1024, backupCount=3
    )
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
log.addHandler(_log_handler)

from modules import draw_text, functions, airport_db
from modules.data_utils import append_directional_hit, append_sample, clear_top_graph_history, load_top_graph_history, persist_top_graph_sample, prune_history, save_plane_to_csv, save_flight_history
from modules.network_utils import can_retry_plane_api, check_network, fetch_plane_info
from modules.rarity import build_model_counts, compute_ratings, get_rarity_colour, get_rarity_rating
from modules.ui_utils import draw_altitude_filter, draw_filter_action_buttons, draw_line_graph, draw_polar_coverage_plot, draw_rarity_filter, plane_matches_altitude_filter, plane_matches_distance_filter

def _read_cpu_temp():
    try:
        sensors = psutil.sensors_temperatures()
        for key in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"):
            entries = sensors.get(key, [])
            if entries:
                pkg = next((e for e in entries if "package" in e.label.lower() or e.label == ""), entries[0])
                return pkg.current
    except (AttributeError, Exception):
        pass
    for zone_dir in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        try:
            zone_type = (zone_dir / "type").read_text().strip()
            if any(t in zone_type for t in ("pkg", "cpu", "core", "x86", "k10temp")):
                return int((zone_dir / "temp").read_text()) / 1000
        except OSError:
            continue
    try:
        return int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    except OSError:
        return 0

RARITY_TIERS = [
    (10, (255, 0, 255), "LGND"),
    (8,  (255, 0, 0),   "RARE"),
    (6,  (0, 255, 0),   "UCMN"),
    (4,  (255, 255, 0), "CMMN"),
    (1,  (255, 255, 255), "STND"),
]

#Load config
_config = functions.load_config()
_config.setdefault('screenWidth', 1920)
_config.setdefault('screenHeight', 1080)
_config.setdefault('cameraHost', '192.168.0.157')
_config.setdefault('cameraPort', 12345)
_config.setdefault('flightHistoryDir', './flight_history')

FLIGHT_HISTORY_DIR = _config['flightHistoryDir']
model_counts = build_model_counts(FLIGHT_HISTORY_DIR)
model_ratings = compute_ratings(model_counts)

CAMERA_SERVER = (_config['cameraHost'], int(_config['cameraPort']))
READSB_JSON_PATH = "/run/readsb/aircraft.json"

#Global variables
offline = _config['offlineMode']
active_planes = {}
displayed_planes = {}
is_receiving = False
is_processing = False
network_available = True
message_queue = []
tracker_running = True
display_duration = 30
fade_duration = 10

#Per-plane API retry tracking
PLANE_API_RETRY_DELAY = 60  #Wait 60 seconds before retrying a failed plane
ACTIVE_PLANE_RETENTION_SECONDS = 30 * 60
TRACKER_PHOTO_CACHE_LIMIT = 24
TRACKER_PREDICTION_SECONDS = 1.2
TRACKER_MAX_EXTRAPOLATION_SECONDS = 2.0
TRACKER_MAX_SAMPLE_AGE_SECONDS = 5.0

#Thread lock for shared data
data_lock = threading.Lock()
tracker_request_lock = threading.Lock()

#Graph history settings
TOP_GRAPH_HISTORY_SECONDS = 24 * 60 * 60
PLANE_GRAPH_HISTORY_SECONDS = 30 * 60
GRAPH_SAMPLE_INTERVAL = 60
PLANE_ALTITUDE_SAMPLE_INTERVAL = 0
PLANE_HIT_SAMPLE_INTERVAL = 60
DIRECTIONAL_HISTORY_SECONDS = 24 * 60 * 60
DIRECTIONAL_SECTOR_COUNT = 8
TOP_GRAPH_HISTORY_DIR = "stats_history"
TRACKER_IMAGE_DIR = Path("images")
#Rolling graph data
active_count_history = deque()
total_seen_history = deque()
directional_hit_history = deque()

#Activity spectrogram state
ACTIVITY_SPECTRUM_SECONDS = 120
ACTIVITY_SPECTRUM_BINS = 96
activity_spectrum_rows = deque()
activity_messages_this_second = 0
activity_last_flush = time.time()


def format_service_connection_error(service_name, endpoint, error):
    host, port = endpoint
    error_text = str(error)
    lowered_error = error_text.lower()

    if isinstance(error, ConnectionRefusedError) or 'refused' in lowered_error:
        return (
            f"{service_name} unavailable: connection refused at {host}:{port}. "
            f"Start the {service_name.lower()} service or update config/config.yml."
        )

    return f"{service_name} unavailable at {host}:{port}: {error_text}"

ICAO_CACHE_PATH = './config/icao_cache.json'
ICAO_CACHE_MAX_AGE_DAYS = 30
icao_cache = {}
api_pending = set()
api_request_timestamps = deque()
_recent_message_times = {}
_DEDUP_WINDOW_SECONDS = 120
API_RATE_LIMIT_WINDOW = 300
API_RATE_LIMIT_MAX = 900


def get_api_request_count_5min(now=None):
    now = now or time.time()
    cutoff = now - API_RATE_LIMIT_WINDOW
    while api_request_timestamps and api_request_timestamps[0] < cutoff:
        api_request_timestamps.popleft()
    return len(api_request_timestamps)


def load_icao_cache():
    global icao_cache
    try:
        if os.path.exists(ICAO_CACHE_PATH):
            with open(ICAO_CACHE_PATH, 'r') as f:
                icao_cache = json.load(f)
            log.info(f"Loaded {len(icao_cache)} entries from ICAO cache")
    except Exception as e:
        log.warning(f"Could not load ICAO cache: {e}")
        icao_cache = {}


def save_icao_cache_entry(icao, data):
    entry = {k: data[k] for k in ('manufacturer', 'model', 'owner', 'registration') if k in data}
    entry['cached_at'] = time.time()
    icao_cache[icao] = entry
    try:
        tmp = ICAO_CACHE_PATH + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(icao_cache, f)
        os.replace(tmp, ICAO_CACHE_PATH)
    except Exception as e:
        log.warning(f"Could not save ICAO cache: {e}")



def acquire_instance_lock():
    global instance_lock_file
    if fcntl is None:
        return
    lock_path = '/tmp/plane_tracker.lock'
    instance_lock_file = open(lock_path, 'w')
    try:
        fcntl.flock(instance_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        instance_lock_file.write(str(os.getpid()))
        instance_lock_file.flush()
    except BlockingIOError:
        log.error('Another plane_tracker.py instance is already running')
        sys.exit(1)


def release_instance_lock():
    """Release the production singleton lock before shutdown or restart."""
    global instance_lock_file
    if instance_lock_file is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(instance_lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        instance_lock_file.close()
        instance_lock_file = None


def add_message(message):
    body = " ".join(str(message).split())
    lower_body = body.lower()
    is_error = any(token in lower_body for token in ["error", "failed", "timeout", "warning", "invalid"])
    if is_error and len(body) > 50:
        body = body[:47] + "..."

    now = time.time()
    last_shown = _recent_message_times.get(body)
    if last_shown is not None and now - last_shown < _DEDUP_WINDOW_SECONDS:
        return
    _recent_message_times[body] = now
    if len(_recent_message_times) > 200:
        cutoff = now - _DEDUP_WINDOW_SECONDS
        for k in [k for k, t in _recent_message_times.items() if t < cutoff]:
            del _recent_message_times[k]

    timestamp = strftime("%H:%M", localtime())
    formatted_message = f"{timestamp} {body}"

    with data_lock:
        message_queue.append(formatted_message)
        if len(message_queue) > 500:
            message_queue.pop(0)


def truncate_log_text(text, font, max_width):
    if font.size(text)[0] <= max_width:
        return text
    while text and font.size(text + 'â€¦')[0] > max_width:
        text = text[:-1]
    return text + 'â€¦'


def clone_plane_data_for_ui(plane_data):
    snapshot = dict(plane_data)

    location_history = plane_data.get("location_history")
    if isinstance(location_history, dict):
        snapshot["location_history"] = dict(location_history)

    altitude_history = plane_data.get("altitude_history")
    if isinstance(altitude_history, deque):
        snapshot["altitude_history"] = deque(altitude_history)

    hit_history = plane_data.get("hit_history")
    if isinstance(hit_history, deque):
        snapshot["hit_history"] = deque(hit_history)

    return snapshot


def snapshot_displayed_planes():
    with data_lock:
        return {
            icao: {
                "plane_data": clone_plane_data_for_ui(display_data.get("plane_data", {})),
                "display_until": display_data.get("display_until", 0),
            }
            for icao, display_data in displayed_planes.items()
        }


def prune_tracker_photo_cache_locked(preserve_icao=None):
    if preserve_icao and preserve_icao in tracker_plane_photo_cache:
        tracker_plane_photo_cache[preserve_icao] = tracker_plane_photo_cache.pop(preserve_icao)
    if preserve_icao and preserve_icao in tracker_plane_photo_meta_cache:
        tracker_plane_photo_meta_cache[preserve_icao] = tracker_plane_photo_meta_cache.pop(preserve_icao)

    while len(tracker_plane_photo_cache) > TRACKER_PHOTO_CACHE_LIMIT:
        oldest_icao = next(iter(tracker_plane_photo_cache))
        if preserve_icao and oldest_icao == preserve_icao and len(tracker_plane_photo_cache) > 1:
            tracker_plane_photo_cache[oldest_icao] = tracker_plane_photo_cache.pop(oldest_icao)
            if oldest_icao in tracker_plane_photo_meta_cache:
                tracker_plane_photo_meta_cache[oldest_icao] = tracker_plane_photo_meta_cache.pop(oldest_icao)
            oldest_icao = next(iter(tracker_plane_photo_cache))
        del tracker_plane_photo_cache[oldest_icao]
        tracker_plane_photo_meta_cache.pop(oldest_icao, None)


def build_tracker_image_path(target_icao):
    hex_code = ''.join(ch for ch in str(target_icao or 'UNKNOWN').upper() if ch.isalnum()) or 'UNKNOWN'
    timestamp = datetime.now().strftime('%d-%m-%Y_%H-%M-%S')
    return TRACKER_IMAGE_DIR / f"{hex_code}_{timestamp}.jpg"


def save_tracker_image(image_bytes, target_icao):
    output_path = build_tracker_image_path(target_icao)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)
    return output_path

#Helper thread for API fetches to avoid blocking the radar
def api_worker_thread(icao, plane_data):
    try:
        api_request_timestamps.append(time.time())
        api_data = fetch_plane_info(icao)
        if api_data is None:
            # 404 - not in database, no point retrying
            with data_lock:
                if icao in active_planes:
                    active_planes[icao]['api_retries_exhausted'] = True
        elif api_data.get('last_api_error'):
            # Network/server error - increment retry count and stop after 3 total attempts
            error_msg = api_data.get('api_error_msg', 'API error')
            add_message(f"{error_msg}")
            with data_lock:
                if icao in active_planes:
                    retry_count = active_planes[icao].get('api_retry_count', 0) + 1
                    active_planes[icao]['api_retry_count'] = retry_count
                    active_planes[icao]['last_api_error'] = api_data['last_api_error']
                    if retry_count >= 3:
                        active_planes[icao]['api_retries_exhausted'] = True
                if icao in displayed_planes:
                    displayed_planes[icao]['plane_data']['last_api_error'] = api_data['last_api_error']
        else:
            # Success
            plane_snapshot = None
            with data_lock:
                if icao in active_planes:
                    active_planes[icao].update(api_data)
                    plane_snapshot = dict(active_planes[icao])
                if icao in displayed_planes:
                    displayed_planes[icao]["plane_data"].update(api_data)
            if plane_snapshot and api_data.get("manufacturer") and api_data.get("manufacturer") != "-":
                save_plane_to_csv(icao, plane_snapshot)
                save_icao_cache_entry(icao, api_data)
                _model = api_data.get('model', '-')
                if _model and _model != '-':
                    model_counts[_model] = model_counts.get(_model, 0) + 1
                    _new_ratings = compute_ratings(model_counts)
                    model_ratings.clear()
                    model_ratings.update(_new_ratings)
    finally:
        api_pending.discard(icao)


_tracker_stats_link_ok = False


def fetch_tracker_stats(log_result=False):
    global tracker_device_stats, _tracker_stats_link_ok
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(CAMERA_SERVER)
        sock.sendall(b'stats')
        response = sock.recv(1024).decode().strip()
        sock.close()

        temp_text, ram_text, cpu_text, disk_text = response.split(',', 3)
        parsed_stats = {
            'temp': float(temp_text),
            'ram': float(ram_text),
            'cpu': float(cpu_text),
            'disk': float(disk_text),
        }

        with data_lock:
            tracker_device_stats = parsed_stats

        was_connected = _tracker_stats_link_ok
        _tracker_stats_link_ok = True
        if log_result and not was_connected:
            add_message('Connected to camera module')
    except Exception as error:
        was_connected = _tracker_stats_link_ok
        _tracker_stats_link_ok = False
        with data_lock:
            tracker_device_stats = {'temp': None, 'ram': None, 'cpu': None, 'disk': None}
        if log_result or was_connected:
            add_message(format_service_connection_error('Camera module', CAMERA_SERVER, error))


def tracker_stats_thread():
    first_check = True
    while tracker_running:
        fetch_tracker_stats(log_result=first_check)
        first_check = False
        time.sleep(5)


#Ping-based reachability check for the camera module, independent of the stats/capture
#TCP connections so a busy capture socket doesn't make the status flap to "offline"
TRACKER_PING_INTERVAL = 10.0


def ping_tracker_host(host, timeout=2):
    try:
        if sys.platform.startswith('win'):
            cmd = ['ping', '-n', '1', '-w', str(int(timeout * 1000)), host]
        else:
            cmd = ['ping', '-c', '1', '-W', str(int(timeout)), host]
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout + 1
        )
        return result.returncode == 0
    except Exception:
        return False


def tracker_ping_thread():
    global tracker_status_connected
    while tracker_running:
        reachable = ping_tracker_host(CAMERA_SERVER[0])
        with data_lock:
            tracker_status_connected = reachable
        time.sleep(TRACKER_PING_INTERVAL)


def receive_tracker_line(sock):
    header = bytearray()
    while True:
        chunk = sock.recv(1)
        if not chunk:
            break
        if chunk == b'\n':
            break
        header.extend(chunk)
    return header.decode(errors='ignore').strip()


def receive_tracker_bytes(sock, byte_count):
    payload = bytearray()
    while len(payload) < byte_count:
        chunk = sock.recv(min(4096, byte_count - len(payload)))
        if not chunk:
            raise ConnectionError('camera module closed connection during image transfer')
        payload.extend(chunk)
    return bytes(payload)


def refresh_tracker_photo_surface():
    global tracker_photo_surface, tracker_photo_dirty, tracker_photo_status
    global tracker_photo_bytes, tracker_pending_photo_plane_icao, tracker_plane_photo_meta_cache
    global tracker_plane_photo_history

    pending_bytes = None
    pending_plane_icao = None
    with data_lock:
        if tracker_photo_dirty and tracker_photo_bytes is not None:
            pending_bytes = tracker_photo_bytes
            pending_plane_icao = tracker_pending_photo_plane_icao
            tracker_photo_dirty = False
            tracker_photo_bytes = None
            tracker_pending_photo_plane_icao = None

    if pending_bytes is None:
        return

    try:
        loaded_surface = pygame.image.load(io.BytesIO(pending_bytes), 'camera.jpg').convert()
    except Exception as error:
        with data_lock:
            tracker_photo_status = 'Image decode failed'
        add_message(f'Camera image decode failed: {error}')
        return

    with data_lock:
        tracker_photo_surface = loaded_surface
        if pending_plane_icao:
            tracker_plane_photo_cache[pending_plane_icao] = loaded_surface
            tracker_plane_photo_meta_cache[pending_plane_icao] = dict(tracker_photo_meta)
            prune_tracker_photo_cache_locked(preserve_icao=pending_plane_icao)
            _pending_meta_snapshot = dict(tracker_photo_meta)

    if pending_plane_icao:
        if pending_plane_icao not in tracker_plane_photo_history:
            tracker_plane_photo_history[pending_plane_icao] = []
        _history = tracker_plane_photo_history[pending_plane_icao]
        _history.insert(0, (loaded_surface, _pending_meta_snapshot))
        if len(_history) > TRACKER_PLANE_PHOTO_HISTORY_LIMIT:
            _history.pop()


def predict_tracker_target(plane_data):
    try:
        lat = float(plane_data.get('last_lat'))
        lon = float(plane_data.get('last_lon'))
        alt_ft = float(plane_data.get('altitude'))
    except (TypeError, ValueError):
        return None

    last_update_time = plane_data.get('last_update_time')
    prev_update_time = plane_data.get('prev_update_time')
    prev_lat = plane_data.get('prev_lat')
    prev_lon = plane_data.get('prev_lon')
    prev_alt_ft = plane_data.get('prev_altitude')

    if not isinstance(last_update_time, (int, float)):
        return lat, lon, alt_ft, 0.0

    sample_age = max(0.0, time.time() - last_update_time)
    if sample_age > TRACKER_MAX_SAMPLE_AGE_SECONDS:
        return lat, lon, alt_ft, 0.0

    lead_seconds = min(TRACKER_MAX_EXTRAPOLATION_SECONDS, TRACKER_PREDICTION_SECONDS + sample_age)

    if not isinstance(prev_update_time, (int, float)):
        return lat, lon, alt_ft, lead_seconds

    try:
        prev_lat = float(prev_lat)
        prev_lon = float(prev_lon)
        prev_alt_ft = alt_ft if prev_alt_ft in (None, '-') else float(prev_alt_ft)
    except (TypeError, ValueError):
        return lat, lon, alt_ft, lead_seconds

    dt = last_update_time - prev_update_time
    if dt <= 0.0 or dt > TRACKER_MAX_SAMPLE_AGE_SECONDS:
        return lat, lon, alt_ft, lead_seconds

    scale = lead_seconds / dt
    predicted_lat = lat + (lat - prev_lat) * scale
    predicted_lon = lon + (lon - prev_lon) * scale
    predicted_alt_ft = alt_ft + (alt_ft - prev_alt_ft) * scale
    return predicted_lat, predicted_lon, predicted_alt_ft, lead_seconds


def send_to_tracker(lat, lon, alt_ft, target_icao=None, add_message_callback=None):
    global tracker_capture_in_progress
    global tracker_photo_bytes, tracker_photo_dirty, tracker_photo_status, tracker_photo_plane_icao, tracker_pending_photo_plane_icao, tracker_photo_meta, tracker_plane_photo_meta_cache

    logger = add_message_callback or add_message
    sock = None

    try:
        alt_m = alt_ft * 0.3048  # convert feet to meters
        logger(f'Sending position data to camera module at {CAMERA_SERVER[0]}:{CAMERA_SERVER[1]}')
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(20)
        sock.connect(CAMERA_SERVER)
        hex_code = target_icao or 'UNKNOWN'
        message = f"{hex_code},{lat},{lon},{alt_m}"
        sock.sendall(message.encode())

        header = receive_tracker_line(sock)
        if not header:
            raise ConnectionError('camera module sent no response')

        if header.startswith('IMAGE '):
            header_parts = header.split()
            image_size = int(header_parts[1])
            image_meta = {}
            for token in header_parts[2:]:
                if '=' in token:
                    key, value = token.split('=', 1)
                    image_meta[key] = value
            image_bytes = receive_tracker_bytes(sock, image_size)
            saved_image_path = None
            save_error = None
            try:
                saved_image_path = save_tracker_image(image_bytes, target_icao)
            except Exception as error:
                save_error = error

            label = image_meta.get('label', 'UNKNOWN')
            aircraft = image_meta.get('aircraft', 'unknown')
            confidence = image_meta.get('confidence')
            raw_score = image_meta.get('raw_score')
            score_margin = image_meta.get('score_margin')
            detail = image_meta.get('detail')
            predictor = image_meta.get('predictor')
            classification_bits = [f"label={label}", f"aircraft={aircraft}"]
            if confidence is not None:
                classification_bits.append(f"confidence={confidence}")
            if raw_score is not None:
                classification_bits.append(f"raw_score={raw_score}")
            if score_margin is not None:
                classification_bits.append(f"score_margin={score_margin}")
            if predictor is not None:
                classification_bits.append(f"predictor={predictor}")
            if detail is not None:
                classification_bits.append(f"detail={detail}")
            classification_text = ', '.join(classification_bits)

            image_meta['target_icao'] = target_icao or 'UNKNOWN'
            image_meta['received_at'] = datetime.now().strftime('%H:%M:%S')
            if saved_image_path is not None:
                image_meta['saved_name'] = saved_image_path.name

            with data_lock:
                tracker_photo_bytes = image_bytes
                tracker_photo_dirty = True
                tracker_pending_photo_plane_icao = target_icao
                tracker_photo_plane_icao = target_icao
                tracker_photo_meta = dict(image_meta)
                tracker_photo_status = (f"Image received for {target_icao} ({classification_text})"
                                        if target_icao else f"Image received ({classification_text})")
                if target_icao:
                    tracker_plane_photo_meta_cache[target_icao] = dict(image_meta)
            if save_error is not None:
                logger(f"Image save failed: {save_error}")
            elif saved_image_path is not None:
                logger(f"Camera image saved: {saved_image_path.name}")
            logger(f"Camera image received: {classification_text}")
        elif header == 'BUSY':
            with data_lock:
                tracker_photo_status = 'Camera busy'
            logger('Camera module busy')
        elif header.startswith('ERROR'):
            detail = header.split(' ', 1)[1] if ' ' in header else 'unknown_error'
            with data_lock:
                tracker_photo_status = f"Camera error: {detail.replace('_', ' ')}"
            logger(f"Camera module error: {detail}")
        else:
            with data_lock:
                tracker_photo_status = f"Unexpected response: {header}"
            logger(f"Camera module response: {header}")
    except Exception as error:
        with data_lock:
            tracker_photo_status = 'Camera unavailable'
        logger(format_service_connection_error('Camera module', CAMERA_SERVER, error))
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        with data_lock:
            tracker_capture_in_progress = False
        if tracker_request_lock.locked():
            tracker_request_lock.release()


def begin_camera_tracking(target_icao, logger=None, auto_select=False):
    if runtime_mode == "preview":
        (logger or add_message)(f"Preview simulated camera tracking for {target_icao}")
        return True
    global selected_plane_icao, tracker_capture_in_progress, tracker_photo_status, tracker_photo_plane_icao

    logger = logger or add_message
    if not tracker_request_lock.acquire(blocking=False):
        logger('Camera module busy')
        return False

    try:
        with data_lock:
            if tracker_capture_in_progress:
                logger('Camera module busy')
                return False

            display_data = displayed_planes.get(target_icao)
            if not display_data:
                logger('No target plane available for tracking')
                return False

            plane_data = display_data.get('plane_data', {})
            predicted_target = predict_tracker_target(plane_data)
            if predicted_target is None:
                logger('Target plane altitude unknown, cannot track')
                return False

            lat, lon, alt_ft, lead_seconds = predicted_target

            tracker_capture_in_progress = True
            tracker_photo_status = f"Capturing {target_icao}"
            tracker_photo_plane_icao = target_icao

        if auto_select:
            with data_lock:
                _has_manual_selection = selected_plane_icao is not None and selected_plane_icao in displayed_planes
            if not _has_manual_selection:
                selected_plane_icao = target_icao

        threading.Thread(target=send_to_tracker, args=(lat, lon, float(alt_ft), target_icao, logger), daemon=True).start()
        logger(f"Aiming camera at {target_icao} using {lead_seconds:.1f}s lead")
        return True
    except Exception:
        with data_lock:
            tracker_capture_in_progress = False
        tracker_request_lock.release()
        raise


def build_auto_track_rect(range_km, centre_lat, centre_lon, projection_lat=None):
    if not AUTO_TRACK_CONFIGURED:
        return None

    projected_points = []
    for lat_key, lon_key in AUTO_TRACK_POLYGON_KEYS:
        projected_points.append(
            functions.coords_to_xy(
                float(_config[lat_key]),
                float(_config[lon_key]),
                range_km,
                centre_lat,
                centre_lon,
                width,
                height,
                RADAR_CENTER_X,
                RADAR_CENTER_Y,
                projection_lat,
            )
        )

    xs = [point_x for point_x, _ in projected_points]
    ys = [point_y for _, point_y in projected_points]
    left = int(min(xs))
    top = int(min(ys))
    rect_width = max(1, int(math.ceil(max(xs) - left)))
    rect_height = max(1, int(math.ceil(max(ys) - top)))
    return pygame.Rect(left, top, rect_width, rect_height)

#THREAD 2: ADSB Data Processing
def adsb_processing_thread():
    global is_receiving, is_processing, tracker_running, offline, network_available

    last_stats_upload = time.time()
    last_network_check = time.time()
    last_flight_history_save = time.time()
    readsb_connected = False

    #Heavy CSV/pandas work runs in a subprocess so it can't stall the render loop via the GIL
    bg_pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    flight_history_future = None
    stats_future = None

    while tracker_running:
        current_time = time.time()

        #Check network every 30 seconds
        if current_time - last_network_check > 30:
            network_available = check_network()
            if not network_available and not offline:
                add_message("Network down switching to Offline")
            last_network_check = current_time

        is_receiving = True
        try:
            with open(READSB_JSON_PATH, "r") as f:
                data = json.load(f)

            if not readsb_connected:
                add_message(f"Connected to readsb at {READSB_JSON_PATH}")
                readsb_connected = True

            aircraft_list = data.get("aircraft", [])
            current_api_count = get_api_request_count_5min()

            for aircraft in aircraft_list:
                plane_data = functions.parse_aircraft(aircraft)
                if not plane_data or plane_data["lon"] == "-" or plane_data["lat"] == "-":
                    continue

                icao = plane_data['icao']
                effective_offline = offline or not network_available

                is_new_plane = False
                with data_lock:
                    if icao in active_planes:
                        cached = active_planes[icao]
                        plane_data["manufacturer"] = cached.get("manufacturer", "-")
                        plane_data["registration"] = cached.get("registration", "-")
                        plane_data["owner"] = cached.get("owner", "-")
                        plane_data["model"] = cached.get("model", "-")
                        plane_data["last_api_error"] = cached.get("last_api_error", 0)
                        plane_data["api_retry_count"] = cached.get("api_retry_count", 0)
                        plane_data["api_retries_exhausted"] = cached.get("api_retries_exhausted", False)
                        if "last_lat" in cached:
                            plane_data["prev_lat"] = cached["last_lat"]
                            plane_data["prev_lon"] = cached["last_lon"]
                            plane_data["prev_update_time"] = cached.get("last_update_time")
                            plane_data["prev_altitude"] = cached.get("altitude")

                        #Preserve existing location_history
                        plane_data["location_history"] = cached.get("location_history", {})
                        plane_data["altitude_history"] = cached.get("altitude_history", deque())
                        plane_data["hit_history"] = cached.get("hit_history", deque())
                        plane_data["last_hit_bucket"] = cached.get("last_hit_bucket")
                        plane_data["last_hit_bucket"] = cached.get("last_hit_bucket")
                        plane_data["last_hit_count"] = cached.get("last_hit_count", 0)
                        plane_data["total_hit_count"] = cached.get("total_hit_count", 0)
                    else:
                        is_new_plane = True
                        plane_data["manufacturer"] = "-"
                        plane_data["registration"] = "-"
                        plane_data["owner"] = "-"
                        plane_data["model"] = "-"
                        plane_data["last_api_error"] = 0
                        plane_data["api_retry_count"] = 0
                        plane_data["api_retries_exhausted"] = False
                        plane_data["location_history"] = {}
                        plane_data["altitude_history"] = deque()
                        plane_data["hit_history"] = deque()
                        plane_data["last_hit_bucket"] = None
                        plane_data["last_hit_count"] = 0
                        plane_data["total_hit_count"] = 0
                    plane_data["last_lat"] = float(plane_data["lat"])
                    plane_data["last_lon"] = float(plane_data["lon"])
                    plane_data["last_update_time"] = time.time()
                    current_timestamp = plane_data.get("spotted_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    current_epoch = time.time()
                    history_timestamp = f"{current_epoch:.6f}"
                    plane_data["history_timestamp"] = history_timestamp
                    bearing = functions.calculate_bearing(_config['myLat'], _config['myLon'], plane_data["last_lat"], plane_data["last_lon"])
                    append_directional_hit(directional_hit_history, bearing, PLANE_HIT_SAMPLE_INTERVAL, DIRECTIONAL_SECTOR_COUNT, current_epoch)
                    prune_history(directional_hit_history, DIRECTIONAL_HISTORY_SECONDS, current_epoch)
                    #Build location_history for ALL planes (not just ones with API data)
                    if plane_data["lat"] != "-" and plane_data["lon"] != "-":
                        plane_data["location_history"][history_timestamp] = [float(plane_data["lat"]), float(plane_data["lon"])]

                    altitude_value = plane_data.get("altitude")
                    if altitude_value not in (None, "-"):
                        try:
                            altitude_value = float(altitude_value)
                            append_sample(plane_data["altitude_history"], altitude_value, PLANE_ALTITUDE_SAMPLE_INTERVAL, current_epoch)
                            prune_history(plane_data["altitude_history"], PLANE_GRAPH_HISTORY_SECONDS, current_epoch)
                        except (TypeError, ValueError):
                            pass

                    hit_bucket = int(current_epoch // PLANE_HIT_SAMPLE_INTERVAL) * PLANE_HIT_SAMPLE_INTERVAL
                    if plane_data.get("last_hit_bucket") == hit_bucket:
                        plane_data["last_hit_count"] += 1
                        if plane_data["hit_history"] and plane_data["hit_history"][-1][0] == hit_bucket:
                            plane_data["hit_history"][-1] = (hit_bucket, plane_data["last_hit_count"])
                        else:
                            plane_data["hit_history"].append((hit_bucket, plane_data["last_hit_count"]))
                    else:
                        plane_data["last_hit_bucket"] = hit_bucket
                        plane_data["last_hit_count"] = 1
                    plane_data["total_hit_count"] = plane_data.get("total_hit_count", 0) + 1
                    prune_history(plane_data["hit_history"], PLANE_GRAPH_HISTORY_SECONDS, current_epoch)

                    active_planes[icao] = plane_data
                    displayed_planes[icao] = {
                        "plane_data": plane_data,
                        "display_until": time.time() + display_duration
                    }

                if is_new_plane:
                    cache_entry = icao_cache.get(icao)
                    if cache_entry and (time.time() - cache_entry.get('cached_at', 0)) < ICAO_CACHE_MAX_AGE_DAYS * 86400:
                        for field in ('manufacturer', 'model', 'owner', 'registration'):
                            if field in cache_entry:
                                plane_data[field] = cache_entry[field]
                        active_planes[icao] = plane_data
                        displayed_planes[icao]["plane_data"] = plane_data
                        if plane_data.get('manufacturer', '-') != '-' and plane_data.get('owner', '-') != '-':
                            save_plane_to_csv(icao, plane_data)
                    add_message(f"NEW plane {icao}")

                if not effective_offline and plane_data["manufacturer"] == "-" and not plane_data.get("api_retries_exhausted") and icao not in api_pending and can_retry_plane_api(plane_data, PLANE_API_RETRY_DELAY) and current_api_count < API_RATE_LIMIT_MAX:
                    api_pending.add(icao)
                    current_api_count += 1
                    threading.Thread(target=api_worker_thread, args=(icao, plane_data), daemon=True).start()

        except FileNotFoundError:
            if readsb_connected:
                add_message(f"readsb unavailable: {READSB_JSON_PATH} not found")
                readsb_connected = False
            time.sleep(3)
            is_receiving = False
            continue
        except Exception as e:
            log.error(f"ADSB loop error: {e}")
            add_message(f"ADSB loop error: {str(e)[:40]}")
            readsb_connected = False
            time.sleep(1)
            is_receiving = False
            continue

        #Periodically clean old planes and upload stats
        current_time = time.time()
        with data_lock:
            old_planes = [icao for icao, d in displayed_planes.items() if d["display_until"] < current_time]
            for icao in old_planes:
                del displayed_planes[icao]

            stale_active_planes = [
                icao for icao, plane in active_planes.items()
                if current_time - plane.get("last_update_time", current_time) > ACTIVE_PLANE_RETENTION_SECONDS
            ]
            for icao in stale_active_planes:
                del active_planes[icao]
                tracker_plane_photo_cache.pop(icao, None)
                tracker_plane_photo_meta_cache.pop(icao, None)
                planecam_auto_capture_last_time.pop(icao, None)

        if flight_history_future is not None and flight_history_future.done():
            _fh_error = flight_history_future.exception()
            if _fh_error is not None:
                add_message(f"Flight history save error: {str(_fh_error)[:60]}")
            flight_history_future = None

        if current_time - last_flight_history_save >= 60 and flight_history_future is None:
            with data_lock:
                planes_snapshot = {icao: dict(plane) for icao, plane in active_planes.items()}
            for _plane in planes_snapshot.values():
                _plane['rating'] = get_rarity_rating(_plane.get('model', '-'), model_ratings)
            flight_history_future = bg_pool.submit(save_flight_history, planes_snapshot, FLIGHT_HISTORY_DIR)
            last_flight_history_save = current_time

        if stats_future is not None and stats_future.done():
            try:
                new_stats = stats_future.result()
            except Exception as e:
                new_stats = None
                log.error(f"Stats upload error: {e}")
                add_message(f"Stats upload error: {str(e)[:30]}")
            stats_future = None

            try:
                total = new_stats.get('total', 0) if new_stats else 0
                if total > 0:
                    if _stats_uploader is not None:
                        _stats_uploader(new_stats)
                        add_message(f"Firebase updated: {total} aircraft")
            except Exception as e:
                log.error(f"Stats upload error: {e}")
                add_message(f"Stats upload error: {str(e)[:30]}")

        if current_time - last_stats_upload > 60 and not offline and network_available and stats_future is None:
            stats_future = bg_pool.submit(functions.get_stats, _config['myLat'], _config['myLon'], FLIGHT_HISTORY_DIR)
            last_stats_upload = current_time

        is_receiving = False
        time.sleep(1)

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
    'avg_mach': None,
    'last_updated': None,
}
_flight_stats_lock = threading.Lock()
#Own single-worker process pool: keeps this refresh's pandas/CSV work off the
#render thread's GIL, same reasoning as the pool in adsb_processing_thread.
_flight_stats_pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))


def _load_flight_stats():
    global _flight_stats_cache
    try:
        new_stats = _flight_stats_pool.submit(
            functions.get_stats, _config['myLat'], _config['myLon'],
            flight_history_dir=FLIGHT_HISTORY_DIR,
        ).result()
        if new_stats and new_stats.get('total', 0) > 0:
            with _flight_stats_lock:
                # A newly-created CSV can briefly contain aircraft whose API
                # metadata has not arrived yet. Keep the last meaningful
                # category values instead of flashing 0 / "-" in the UI.
                for key in ('top_model', 'top_manufacturer', 'top_aircraft', 'top_airline'):
                    if not new_stats.get(key, {}).get('name') and _flight_stats_cache.get(key, {}).get('name'):
                        new_stats[key] = dict(_flight_stats_cache[key])
                for key in ('unique_airlines', 'unique_models', 'unique_manufacturers'):
                    if not new_stats.get(key) and _flight_stats_cache.get(key):
                        new_stats[key] = _flight_stats_cache[key]
                if not new_stats.get('manufacturer_breakdown') and _flight_stats_cache.get('manufacturer_breakdown'):
                    new_stats['manufacturer_breakdown'] = dict(_flight_stats_cache['manufacturer_breakdown'])
                for key in ('furthest_detected', 'furthest_plane', 'highest_detected', 'avg_altitude', 'avg_speed', 'max_speed', 'avg_mach'):
                    if new_stats.get(key) is None and _flight_stats_cache.get(key) is not None:
                        new_stats[key] = _flight_stats_cache[key]
                _flight_stats_cache = new_stats
        else:
            log.warning(f"Flight stats: get_stats returned empty (total={new_stats.get('total') if new_stats else None})")
    except Exception as e:
        log.warning(f"Flight stats refresh error: {e}", exc_info=True)


def flight_stats_refresh_thread():
    _load_flight_stats()
    while tracker_running:
        time.sleep(60)
        _load_flight_stats()


def initialise_preview_state():
    """Populate a realistic, entirely in-memory dashboard preview."""
    global active_planes, displayed_planes, message_queue
    global tracker_status_connected, tracker_device_stats, _flight_stats_cache
    now = time.time()

    base_lat = float(_config['myLat'])
    base_lon = float(_config['myLon'])

    def preview_model_for_rating(target_rating, fallback):
        candidates = [
            model for model, rating in model_ratings.items()
            if rating == target_rating
        ]
        if not candidates:
            return fallback
        return min(candidates, key=lambda model: (-model_counts.get(model, 0), model))

    standard_model = preview_model_for_rating(1, "737-800")
    common_model = preview_model_for_rating(4, "A320")
    uncommon_model = preview_model_for_rating(6, "A321neo")
    rare_model = preview_model_for_rating(8, "172")
    samples = (
        ("4CA123", "BAW123", 0.25, 0.15, 35000, 450, 90, "Boeing", standard_model, "G-TEST1", "British Airways", 28.5),
        ("3C4567", "DLH456", -0.10, 0.30, 12000, 280, 180, "Airbus", common_model, "D-AIAB", "Lufthansa", 23.4),
        ("407ABC", "EZY789", 0.08, -0.20, 24000, 390, 315, "Airbus", uncommon_model, "G-UZHA", "easyJet", 18.1),
        ("A1B2C3", "N123EX", -0.30, -0.12, 6500, 145, 45, "Cessna", rare_model, "N123EX", "Private", 35.8),
    )
    preview_planes = {}
    for index, (icao, flight, lat_delta, lon_delta, altitude, speed, track, manufacturer, model, registration, owner, distance) in enumerate(samples):
        history = {
            f"{now - seconds:.6f}": [base_lat + lat_delta - lat_delta * seconds / 900, base_lon + lon_delta - lon_delta * seconds / 900]
            for seconds in (240, 180, 120, 60, 0)
        }
        plane = {
            "icao": icao, "flight": flight, "callsign": flight,
            "lat": base_lat + lat_delta, "lon": base_lon + lon_delta,
            "last_lat": base_lat + lat_delta, "last_lon": base_lon + lon_delta,
            "prev_lat": base_lat + lat_delta * 0.98, "prev_lon": base_lon + lon_delta * 0.98,
            "prev_update_time": now - 5, "last_update_time": now,
            "altitude": str(altitude), "speed": str(speed), "track": str(track),
            "vertical_rate": str((index - 1) * 320), "squawk": "7000",
            "manufacturer": manufacturer, "model": model,
            "registration": registration, "owner": owner,
            "distance": distance, "location_history": history,
            "altitude_history": deque((now - i * 60, altitude - i * 250) for i in range(8, -1, -1)),
            "hit_history": deque((int(now // 60) * 60 - i * 60, 3 + ((i + index) % 8)) for i in range(8, -1, -1)),
            "last_hit_bucket": int(now // 60) * 60, "last_hit_count": 7 + index,
            "total_hit_count": 84 - index * 13,
        }
        preview_planes[icao] = plane
    active_planes = preview_planes
    displayed_planes = {
        icao: {"plane_data": plane, "display_until": now + 86400}
        for icao, plane in preview_planes.items()
    }
    message_queue.clear()
    for text in (
        "Connected to readsb receiver",
        "NEW plane 4CA123",
        "NEW plane 3C4567",
        "NEW plane 407ABC",
    ):
        add_message(text)
    active_count_history.clear()
    total_seen_history.clear()
    for i in range(24, -1, -1):
        active_count_history.append((now - i * 180, 2 + (i * 3) % 13))
        total_seen_history.append((now - i * 180, 96 + (24 - i) * 3))
    tracker_status_connected = True
    tracker_device_stats = {"temp": 46.0, "ram": 38.0, "cpu": 17.0, "disk": 21.4}
    _flight_stats_cache = {
        'total': 168, 'top_model': {'name': 'A320', 'count': 31},
        'top_manufacturer': {'name': 'Airbus', 'count': 72},
        'top_aircraft': {'name': 'A320', 'count': 31},
        'top_airline': {'name': 'British Airways', 'count': 28},
        'manufacturer_breakdown': {'Airbus': 72, 'Boeing': 61},
        'furthest_detected': 241.8, 'highest_detected': 41000,
        'unique_airlines': 22, 'unique_models': 34, 'unique_manufacturers': 12,
        'emergencies_count': 0, 'avg_altitude': 26750, 'avg_speed': 384,
        'max_speed': 552, 'avg_mach': 0.67, 'last_updated': datetime.now().isoformat(),
    }

def start_background_services():
    """Start live workers once, only for the production launcher."""
    global _background_services_started
    if _background_services_started:
        return
    _background_services_started = True
    for target in (
        adsb_processing_thread,
        tracker_stats_thread,
        tracker_ping_thread,
        flight_stats_refresh_thread,
    ):
        threading.Thread(target=target, daemon=True).start()


FIREBASE_DATABASE_URL = "https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app"


def initialise_firebase():
    """Initialise Firebase only for the Linux production launcher."""
    import firebase_admin
    from firebase_admin import credentials

    if not firebase_admin._apps:
        certificate = credentials.Certificate(PROJECT_ROOT / "config" / "firebase.json")
        firebase_admin.initialize_app(certificate, {"databaseURL": FIREBASE_DATABASE_URL})


def upload_daily_stats(stats):
    """Publish the current daily aggregate to Firebase."""
    from firebase_admin import db

    total = stats.get("total", 0)
    if total <= 0:
        return
    today = datetime.today().strftime("%Y-%m-%d")
    top_airline = stats.get("top_airline", {})
    top_aircraft = stats.get("top_aircraft", {})
    furthest = stats.get("furthest_detected")
    db.reference(today).set({
        "total_aircraft": total,
        "top_airline": {"name": top_airline.get("name") or "", "count": top_airline.get("count") or 0},
        "top_aircraft": {"name": top_aircraft.get("name") or "", "count": top_aircraft.get("count") or 0},
        "furthest_aircraft_km": round(furthest, 2) if furthest is not None else None,
        "furthest_plane": stats.get("furthest_plane"),
        "last_updated": datetime.now().strftime("%H-%M-%S"),
    })


def main():
    from modules import gui

    if IS_WINDOWS:
        gui.run(mode="preview")
        return
    initialise_firebase()
    gui.run(mode="production", stats_uploader=upload_daily_stats)


if __name__ == "__main__":
    main()
