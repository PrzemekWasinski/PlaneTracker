import json
import socket
import time
import io
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, db
import pygame
from pygame.locals import *
from time import localtime, strftime
import psutil
import os
import threading
import math
import fcntl
import sys
import subprocess
from collections import deque
from concurrent.futures import ProcessPoolExecutor

_log_dir = Path("logs")
_log_dir.mkdir(exist_ok=True)
log = logging.getLogger("plane_tracker")
log.setLevel(logging.INFO)
_log_handler = logging.handlers.RotatingFileHandler(
    _log_dir / "plane_tracker.log", maxBytes=2 * 1024 * 1024, backupCount=3
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
log.addHandler(_log_handler)

from modules import draw_text, functions, airport_db
from modules.data_utils import append_directional_hit, append_sample, clear_top_graph_history, load_today_heatmap_hits, load_top_graph_history, persist_top_graph_sample, prune_history, save_plane_to_csv, save_flight_history
from modules.network_utils import can_retry_plane_api, check_network, fetch_plane_info, upload_to_firebase
from modules.rarity import build_model_counts, compute_ratings, get_rarity_colour, get_rarity_rating
from modules.ui_utils import draw_altitude_filter, draw_filter_action_buttons, draw_line_graph, draw_polar_coverage_plot, draw_radar_heatmap, draw_rarity_filter, plane_matches_altitude_filter, plane_matches_distance_filter

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
_config.setdefault('cameraHost', '192.168.0.157')
_config.setdefault('cameraPort', 12345)
_config.setdefault('flightHistoryDir', './flight_history')

FLIGHT_HISTORY_DIR = _config['flightHistoryDir']
model_counts = build_model_counts(FLIGHT_HISTORY_DIR)
model_ratings = compute_ratings(model_counts)

CAMERA_SERVER = (_config['cameraHost'], int(_config['cameraPort']))
READSB_JSON_PATH = "/run/readsb/aircraft.json"

#Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("./config/firebase.json")
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app"
    })

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
heatmap_hits = deque()

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

#PYGAME SETUP
pygame.init()
#pygame.mouse.set_visible(False)

width = _config['screenWidth']
height = _config['screenHeight']
window = pygame.display.set_mode((width, height), pygame.FULLSCREEN)

#Fonts
text_font1 = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 16)
text_font2 = pygame.font.Font(os.path.join("textures", "fonts", "DS-DIGI.TTF"), 40)
text_font3 = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 11)
stat_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 13)
graph_time_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 9)
plane_identity_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 12)

#Load images
zoom_in_icon = pygame.image.load(os.path.join("textures", "icons", "zoom_in.png")).convert_alpha()
zoom_out_icon = pygame.image.load(os.path.join("textures", "icons", "zoom_out.png")).convert_alpha()
online_mode_icon = pygame.image.load(os.path.join("textures", "icons", "online_mode.png")).convert_alpha()
offline_mode_icon = pygame.image.load(os.path.join("textures", "icons", "offline_mode.png")).convert_alpha()
shutdown_icon = pygame.image.load(os.path.join("textures", "icons", "shutdown.png")).convert_alpha()
restart_icon = pygame.image.load(os.path.join("textures", "icons", "restart.png")).convert_alpha()
clear_graph_icon = pygame.image.load(os.path.join("textures", "icons", "clear_graph.png")).convert_alpha()
track_target_icon = pygame.image.load(os.path.join("textures", "icons", "track_target.png")).convert_alpha()
auto_tracking_icon = pygame.image.load(os.path.join("textures", "icons", "auto_tracking.png")).convert_alpha()
manual_tracking_icon = pygame.image.load(os.path.join("textures", "icons", "manual_tracking.png")).convert_alpha()
heatmap_on_icon = pygame.image.load(os.path.join("textures", "icons", "heatmap_on.png")).convert_alpha()
heatmap_off_icon = pygame.image.load(os.path.join("textures", "icons", "heatmap_off.png")).convert_alpha()
plane_only_mode_icon = pygame.image.load(os.path.join("textures", "icons", "plane.png")).convert_alpha()
plane_and_text_mode_icon = pygame.image.load(os.path.join("textures", "icons", "plane_and_text.png")).convert_alpha()
hide_plane_mode_icon = pygame.image.load(os.path.join("textures", "icons", "hide_plane.png")).convert_alpha()
clear_filters_icon = pygame.image.load(os.path.join("textures", "icons", "clear_filters.png")).convert_alpha()
plane_icon = pygame.image.load(os.path.join("textures", "icons", "plane_icon.png")).convert_alpha()
selected_plane_icon = pygame.image.load(os.path.join("textures", "icons", "selected_plane.png")).convert_alpha()
plane_icon_white = plane_icon.copy()
plane_icon_white.fill((255, 255, 255), special_flags=pygame.BLEND_RGB_MAX)

#Radar display settings
RADAR_RECT = pygame.Rect(0, 0, 1080, 1080)
RADAR_CENTER_X = RADAR_RECT.centerx
RADAR_CENTER_Y = RADAR_RECT.centery
RADAR_RADIUS = 540
RADAR_RANGE_VALUES = list(range(25, 1001, 25))
RADAR_MAP_DIR = os.path.join('textures', 'radar_map')

radar_map_images = {}
for radar_range_km in RADAR_RANGE_VALUES:
    radar_map_path = os.path.join(RADAR_MAP_DIR, f'{radar_range_km}.png')
    if os.path.exists(radar_map_path):
        try:
            radar_map_images[radar_range_km] = pygame.image.load(radar_map_path).convert()
            radar_map_images[radar_range_km].set_colorkey((0, 0, 0))
        except pygame.error:
            pass

#Sidebar settings
SIDEBAR_X = 1090
SIDEBAR_WIDTH = width - SIDEBAR_X


# UI Buttons - Start at SIDEBAR_X + 10, 10px spacing between buttons
btn_w = 40
btn_h = 40
btn_gap = 10
toolbar_start_x = SIDEBAR_X + 5

zoom_in_ctrl_rect = pygame.Rect(toolbar_start_x, height - 50, btn_w, btn_h)
zoom_out_ctrl_rect = pygame.Rect(toolbar_start_x + (btn_w + btn_gap) * 1, height - 50, btn_w, btn_h)
mode_toggle_rect = pygame.Rect(toolbar_start_x + (btn_w + btn_gap) * 2, height - 50, btn_w, btn_h)
auto_track_mode_rect = pygame.Rect(toolbar_start_x + (btn_w + btn_gap) * 3, height - 50, btn_w, btn_h)
restart_button_rect = pygame.Rect(toolbar_start_x + (btn_w + btn_gap) * 4, height - 50, btn_w, btn_h)
off_button_rect = pygame.Rect(toolbar_start_x + (btn_w + btn_gap) * 5, height - 50, btn_w, btn_h)
clear_graph_rect = pygame.Rect(toolbar_start_x + (btn_w + btn_gap) * 6, height - 50, btn_w, btn_h)

#Global for plane selection
selected_plane_icao = None
plane_rects = {} 
altitude_filter_threshold = 0
altitude_filter_above = True
altitude_filter_dragging = False
distance_filter_threshold_km = 0.0
distance_filter_outside = True
distance_filter_dragging = False
rarity_filter_selected = set()
radar_heatmap_enabled = False
hide_planes_mode = 0
distance_unit = "NM"
tracker_status_connected = False
tracker_device_stats = {"temp": None, "ram": None, "cpu": None, "disk": None}
tracker_capture_in_progress = False
tracker_photo_bytes = None
tracker_photo_surface = None
tracker_photo_dirty = False
tracker_photo_status = "No camera image"
tracker_photo_plane_icao = None
tracker_pending_photo_plane_icao = None
tracker_photo_meta = {}
tracker_plane_photo_cache = {}
tracker_plane_photo_meta_cache = {}
tracking_mode_auto = False
planecam_auto_capture_last_time = {}
PLANECAM_AUTO_CAPTURE_INTERVAL = 15.0
tracker_plane_photo_history = {}
TRACKER_PLANE_PHOTO_HISTORY_LIMIT = 10
camera_scroll_offset = 0
auto_track_queue = deque()
auto_track_inside_icaos = set()
AUTO_TRACK_POLYGON_KEYS = (("tlLat", "tlLon"), ("trLat", "trLon"), ("brLat", "brLon"), ("blLat", "blLon"))
AUTO_TRACK_CONFIGURED = all(_config.get(lat_key) is not None and _config.get(lon_key) is not None for lat_key, lon_key in AUTO_TRACK_POLYGON_KEYS)
instance_lock_file = None

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


load_icao_cache()

def acquire_instance_lock():
    global instance_lock_file
    lock_path = '/tmp/plane_tracker.lock'
    instance_lock_file = open(lock_path, 'w')
    try:
        fcntl.flock(instance_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        instance_lock_file.write(str(os.getpid()))
        instance_lock_file.flush()
    except BlockingIOError:
        log.error('Another plane_tracker.py instance is already running')
        sys.exit(1)

acquire_instance_lock()

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
        if len(message_queue) > 60:
            message_queue.pop(0)


def truncate_log_text(text, font, max_width):
    if font.size(text)[0] <= max_width:
        return text
    while text and font.size(text + '…')[0] > max_width:
        text = text[:-1]
    return text + '…'


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
                upload_to_firebase(plane_snapshot)
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


def build_auto_track_rect(range_km, centre_lat, centre_lon):
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
    bg_pool = ProcessPoolExecutor(max_workers=1)
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
                    heatmap_hits.append((current_epoch, plane_data["last_lat"], plane_data["last_lon"]))
                    prune_history(heatmap_hits, DIRECTIONAL_HISTORY_SECONDS, current_epoch)
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
                    today = datetime.today().strftime("%Y-%m-%d")
                    top_airline_name = new_stats['top_airline']['name'] or ''
                    top_airline_count = new_stats['top_airline']['count'] or 0
                    top_aircraft = new_stats['top_aircraft']['name'] or ''
                    top_aircraft_count = new_stats['top_aircraft']['count'] or 0
                    furthest = new_stats.get('furthest_detected')
                    furthest_plane = new_stats.get('furthest_plane')

                    day_ref = db.reference(today)
                    day_ref.set({
                        'total_aircraft': total,
                        'top_airline': {'name': top_airline_name, 'count': top_airline_count},
                        'top_aircraft': {'name': top_aircraft, 'count': top_aircraft_count},
                        'furthest_aircraft_km': round(furthest, 2) if furthest is not None else None,
                        'furthest_plane': furthest_plane,
                        'last_updated': datetime.now().strftime('%H-%M-%S'),
                    })
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


def _load_flight_stats():
    global _flight_stats_cache
    try:
        new_stats = functions.get_stats(
            _config['myLat'], _config['myLon'],
            flight_history_dir=FLIGHT_HISTORY_DIR,
        )
        if new_stats and new_stats.get('total', 0) > 0:
            with _flight_stats_lock:
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


#Start ADSB processing thread
processing_thread = threading.Thread(target=adsb_processing_thread, daemon=True)
processing_thread.start()

tracker_stats_worker = threading.Thread(target=tracker_stats_thread, daemon=True)
tracker_stats_worker.start()

tracker_ping_worker = threading.Thread(target=tracker_ping_thread, daemon=True)
tracker_ping_worker.start()

flight_stats_worker = threading.Thread(target=flight_stats_refresh_thread, daemon=True)
flight_stats_worker.start()

#THREAD 1: Main UI Thread
def main():
    global tracker_running, offline, selected_plane_icao, heatmap_hits
    global altitude_filter_threshold, altitude_filter_above, altitude_filter_dragging
    global distance_filter_threshold_km, distance_filter_outside, distance_filter_dragging
    global radar_heatmap_enabled, hide_planes_mode, distance_unit, rarity_filter_selected
    global tracker_capture_in_progress, tracker_photo_status, tracker_photo_plane_icao, tracking_mode_auto
    global camera_scroll_offset, planecam_auto_capture_last_time

    start_time = time.time()
    top_graph_last_bucket = load_top_graph_history(active_count_history, total_seen_history, TOP_GRAPH_HISTORY_DIR, TOP_GRAPH_HISTORY_SECONDS, start_time)
    heatmap_hits = deque(load_today_heatmap_hits(FLIGHT_HISTORY_DIR, start_time))
    range_km = 50
    last_health_log = start_time
    last_system_stats_refresh = 0
    cpu_temp = 0
    ram_percentage = 0
    cpu_percentage = 0
    disk_free = functions.get_disk_free()
    
    current_graph_date = datetime.today().strftime('%Y-%m-%d')

    view_center_lat = _config['myLat']
    view_center_lon = _config['myLon']
    plane_headings = {}
    log_scroll_offset = 0
    log_scroll_dragging = False
    log_scrollbar_thumb_rect = pygame.Rect(0, 0, 0, 0)
    log_scroll_drag_start_y = 0
    log_scroll_drag_start_offset = 0
    _prev_target_icao_for_scroll = None
    closest_plane = None

    while True:
        current_time = time.time()

        _today = datetime.today().strftime('%Y-%m-%d')
        if _today != current_graph_date:
            current_graph_date = _today
            with data_lock:
                active_count_history.clear()
                total_seen_history.clear()
            clear_top_graph_history(TOP_GRAPH_HISTORY_DIR)
            top_graph_last_bucket = None

        pic_y = 377
        pic_h = 203
        logs_y = pic_y + pic_h + 10
        logs_h = (height - 50) - logs_y - 10
        filter_panel_rect = pygame.Rect(SIDEBAR_X + (SIDEBAR_WIDTH // 2) + 5, (315 // 2) + 68 + 150, int(SIDEBAR_WIDTH / 2) - 5, int(logs_h // 2))
        log_bottom_row_y = filter_panel_rect.bottom + 10
        log_h_early = (height - 10) - log_bottom_row_y
        log_box_rect = pygame.Rect(filter_panel_rect.left, log_bottom_row_y, filter_panel_rect.width, log_h_early)
        heatmap_button_rect = pygame.Rect(filter_panel_rect.right - 48, filter_panel_rect.top + 8, 40, 40)
        hide_planes_button_rect = pygame.Rect(filter_panel_rect.right - 48, filter_panel_rect.top + 56, 40, 40)
        reset_filters_button_rect = pygame.Rect(filter_panel_rect.right - 48, filter_panel_rect.top + 104, 40, 40)
        distance_unit_rects = {
            "NM": pygame.Rect(filter_panel_rect.right - 44, filter_panel_rect.top + 152, 14, 14),
            "KM": pygame.Rect(filter_panel_rect.right - 44, filter_panel_rect.top + 174, 14, 14),
            "MI": pygame.Rect(filter_panel_rect.right - 44, filter_panel_rect.top + 196, 14, 14),
        }
        filter_checkbox_rect = pygame.Rect(filter_panel_rect.left + 8, filter_panel_rect.top + 10, 14, 14)
        slider_track_rect = pygame.Rect(filter_panel_rect.left + 28, filter_panel_rect.top + 48, 12, max(80, filter_panel_rect.height - 66))
        distance_filter_checkbox_rect = pygame.Rect(filter_panel_rect.left + 83, filter_panel_rect.top + 10, 14, 14)
        distance_slider_track_rect = pygame.Rect(filter_panel_rect.left + 103, filter_panel_rect.top + 48, 12, max(80, filter_panel_rect.height - 66))
        track_plane_button_rect = pygame.Rect(SIDEBAR_X + 250, ((315 // 2) + 68) + 10, 40, 40)
        slider_ratio = 1.0 - (altitude_filter_threshold / 50000.0)
        slider_handle_y = slider_track_rect.top + int(slider_ratio * slider_track_rect.height) - 5
        slider_handle_y = max(slider_track_rect.top - 5, min(slider_track_rect.bottom - 5, slider_handle_y))
        filter_slider_handle_rect = pygame.Rect(slider_track_rect.left - 2, slider_handle_y, slider_track_rect.width + 4, 10)
        distance_slider_ratio = 1.0 - (distance_filter_threshold_km / 1000.0)
        distance_slider_handle_y = distance_slider_track_rect.top + int(distance_slider_ratio * distance_slider_track_rect.height) - 5
        distance_slider_handle_y = max(distance_slider_track_rect.top - 5, min(distance_slider_track_rect.bottom - 5, distance_slider_handle_y))
        distance_filter_slider_handle_rect = pygame.Rect(distance_slider_track_rect.left - 2, distance_slider_handle_y, distance_slider_track_rect.width + 4, 10)
        altitude_slider_up_rect = pygame.Rect(slider_track_rect.right + 30, slider_track_rect.top + 6, 18, 14)
        altitude_slider_down_rect = pygame.Rect(slider_track_rect.right + 30, slider_track_rect.top + 24, 18, 14)
        distance_slider_up_rect = pygame.Rect(distance_slider_track_rect.right + 30, distance_slider_track_rect.top + 6, 18, 14)
        distance_slider_down_rect = pygame.Rect(distance_slider_track_rect.right + 30, distance_slider_track_rect.top + 24, 18, 14)
        _rarity_col_x = filter_panel_rect.centerx
        _rarity_row_h = 22
        _rarity_start_y = filter_panel_rect.top + 10
        rarity_checkbox_rects = {
            tier: pygame.Rect(_rarity_col_x, _rarity_start_y + i * _rarity_row_h, 14, 14)
            for i, (tier, _col, _label) in enumerate(RARITY_TIERS)
        }

        _cam_box_w = int((SIDEBAR_WIDTH / 2) - 10)
        _cam_box_h = int(_cam_box_w * 3 / 4)
        cam_scroll_right_rect = pygame.Rect(SIDEBAR_X + 5 + _cam_box_w - btn_w, log_bottom_row_y + _cam_box_h + 10, btn_w, btn_h)
        cam_scroll_left_rect = pygame.Rect(cam_scroll_right_rect.left - btn_w - btn_gap, log_bottom_row_y + _cam_box_h + 10, btn_w, btn_h)

        #Log health stats every 30 minutes
        if current_time - last_health_log >= 1800:
            log.info(f"Health check: CPU temp={cpu_temp:.1f}C, RAM={ram_percentage:.1f}%")
            last_health_log = current_time

        #Refresh expensive local stats on a timer instead of every frame
        if current_time - last_system_stats_refresh >= 1:
            cpu_temp = _read_cpu_temp()
            ram_percentage = psutil.virtual_memory()[2]
            cpu_percentage = psutil.cpu_percent()
            disk_free = functions.get_disk_free()
            last_system_stats_refresh = current_time

        displayed_planes_snapshot = snapshot_displayed_planes()

        #Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                tracker_running = False
                pygame.quit()
                exit()
            
            #Mouse wheel zoom / log scroll
            elif event.type == pygame.MOUSEWHEEL:
                mouse_x, mouse_y = pygame.mouse.get_pos()

                if log_box_rect.collidepoint(mouse_x, mouse_y):
                    with data_lock:
                        total_msgs = len(message_queue)
                    lines_per_page = max(1, (log_h_early - 4) // 11)
                    max_scroll = max(0, total_msgs - lines_per_page)
                    if event.y > 0:
                        log_scroll_offset = min(log_scroll_offset + 3, max_scroll)
                    elif event.y < 0:
                        log_scroll_offset = max(log_scroll_offset - 3, 0)

                #Only zoom if mouse is over the radar area
                elif RADAR_RECT.collidepoint(mouse_x, mouse_y):
                    #Scroll up = zoom in, scroll down = zoom out
                    if event.y > 0:  #Scroll up
                        if range_km > 25:
                            range_km -= 25
                    elif event.y < 0:  #Scroll down
                        if range_km < 1000:
                            range_km += 25

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    altitude_filter_dragging = False
                    distance_filter_dragging = False
                    log_scroll_dragging = False

            elif event.type == pygame.MOUSEMOTION:
                if altitude_filter_dragging:
                    clamped_y = max(slider_track_rect.top, min(slider_track_rect.bottom, event.pos[1]))
                    altitude_filter_threshold = clamp_altitude_threshold((1.0 - ((clamped_y - slider_track_rect.top) / max(1, slider_track_rect.height))) * 50000)
                if distance_filter_dragging:
                    clamped_y = max(distance_slider_track_rect.top, min(distance_slider_track_rect.bottom, event.pos[1]))
                    distance_filter_threshold_km = clamp_distance_threshold((1.0 - ((clamped_y - distance_slider_track_rect.top) / max(1, distance_slider_track_rect.height))) * 1000.0)
                if log_scroll_dragging:
                    with data_lock:
                        total_msgs_drag = len(message_queue)
                    lines_per_page_drag = max(1, (log_h_early - 4) // 11)
                    max_scroll_drag = max(0, total_msgs_drag - lines_per_page_drag)
                    track_usable = log_h_early - 2 - max(20, int(log_h_early * lines_per_page_drag / max(1, total_msgs_drag)))
                    if track_usable > 0 and max_scroll_drag > 0:
                        dy = event.pos[1] - log_scroll_drag_start_y
                        delta = int(dy / track_usable * max_scroll_drag)
                        # drag down → newer (lower offset); drag up → older (higher offset)
                        log_scroll_offset = max(0, min(max_scroll_drag, log_scroll_drag_start_offset - delta))

            elif event.type == pygame.MOUSEBUTTONDOWN:
                #Only process left mouse button (button 1), ignore middle/right clicks and scroll buttons
                if event.button != 1:
                    continue

                last_tap_time = time.time()
                mouse_x, mouse_y = pygame.mouse.get_pos()

                if log_scrollbar_thumb_rect.collidepoint(mouse_x, mouse_y):
                    log_scroll_dragging = True
                    log_scroll_drag_start_y = mouse_y
                    log_scroll_drag_start_offset = log_scroll_offset
                    continue

                if heatmap_button_rect.collidepoint(mouse_x, mouse_y):
                    radar_heatmap_enabled = not radar_heatmap_enabled
                    add_message("Heatmap enabled" if radar_heatmap_enabled else "Heatmap disabled")
                    continue

                if hide_planes_button_rect.collidepoint(mouse_x, mouse_y):
                    hide_planes_mode = (hide_planes_mode + 1) % 3
                    if hide_planes_mode == 1:
                        add_message('Plane details hidden')
                    elif hide_planes_mode == 2:
                        add_message('Plane icons and details hidden')
                    else:
                        add_message('Plane display shown')
                    continue

                if reset_filters_button_rect.collidepoint(mouse_x, mouse_y):
                    altitude_filter_threshold = 0
                    altitude_filter_above = True
                    altitude_filter_dragging = False
                    distance_filter_threshold_km = 0.0
                    distance_filter_outside = True
                    distance_filter_dragging = False
                    radar_heatmap_enabled = False
                    hide_planes_mode = 0
                    distance_unit = "NM"
                    rarity_filter_selected.clear()
                    add_message("Filters reset to default")
                    continue

                _rarity_clicked = False
                for _tier, _rrect in rarity_checkbox_rects.items():
                    if _rrect.collidepoint(mouse_x, mouse_y):
                        if _tier in rarity_filter_selected:
                            rarity_filter_selected.discard(_tier)
                        else:
                            rarity_filter_selected.add(_tier)
                        _rarity_clicked = True
                        break
                if _rarity_clicked:
                    continue

                for unit_key, rect in distance_unit_rects.items():
                    if rect.collidepoint(mouse_x, mouse_y):
                        distance_unit = unit_key
                        add_message(f"Distance unit set to {unit_key}")
                        break
                else:
                    pass
                if any(rect.collidepoint(mouse_x, mouse_y) for rect in distance_unit_rects.values()):
                    continue

                if filter_checkbox_rect.collidepoint(mouse_x, mouse_y):
                    altitude_filter_above = not altitude_filter_above
                    continue

                if distance_filter_checkbox_rect.collidepoint(mouse_x, mouse_y):
                    distance_filter_outside = not distance_filter_outside
                    continue

                if altitude_slider_up_rect.collidepoint(mouse_x, mouse_y):
                    altitude_filter_threshold = clamp_altitude_threshold(altitude_filter_threshold + 100)
                    continue

                if altitude_slider_down_rect.collidepoint(mouse_x, mouse_y):
                    altitude_filter_threshold = clamp_altitude_threshold(altitude_filter_threshold - 100)
                    continue

                distance_step_km = convert_distance_to_km(10, distance_unit)
                if distance_slider_up_rect.collidepoint(mouse_x, mouse_y):
                    distance_filter_threshold_km = clamp_distance_threshold(distance_filter_threshold_km + distance_step_km)
                    continue

                if distance_slider_down_rect.collidepoint(mouse_x, mouse_y):
                    distance_filter_threshold_km = clamp_distance_threshold(distance_filter_threshold_km - distance_step_km)
                    continue

                if slider_track_rect.collidepoint(mouse_x, mouse_y) or filter_slider_handle_rect.collidepoint(mouse_x, mouse_y):
                    altitude_filter_dragging = True
                    clamped_y = max(slider_track_rect.top, min(slider_track_rect.bottom, mouse_y))
                    altitude_filter_threshold = clamp_altitude_threshold((1.0 - ((clamped_y - slider_track_rect.top) / max(1, slider_track_rect.height))) * 50000)
                    continue

                if distance_slider_track_rect.collidepoint(mouse_x, mouse_y) or distance_filter_slider_handle_rect.collidepoint(mouse_x, mouse_y):
                    distance_filter_dragging = True
                    clamped_y = max(distance_slider_track_rect.top, min(distance_slider_track_rect.bottom, mouse_y))
                    distance_filter_threshold_km = clamp_distance_threshold((1.0 - ((clamped_y - distance_slider_track_rect.top) / max(1, distance_slider_track_rect.height))) * 1000.0)
                    continue

                if cam_scroll_left_rect.collidepoint(mouse_x, mouse_y):
                    _scroll_icao = selected_plane_icao if selected_plane_icao else closest_plane
                    _hist_len = len(tracker_plane_photo_history.get(_scroll_icao, [])) if _scroll_icao else 0
                    if _hist_len > 0:
                        camera_scroll_offset = (camera_scroll_offset - 1) % _hist_len
                    continue

                if cam_scroll_right_rect.collidepoint(mouse_x, mouse_y):
                    _scroll_icao = selected_plane_icao if selected_plane_icao else closest_plane
                    _hist_len = len(tracker_plane_photo_history.get(_scroll_icao, [])) if _scroll_icao else 0
                    if _hist_len > 0:
                        camera_scroll_offset = (camera_scroll_offset + 1) % _hist_len
                    continue

                if track_plane_button_rect.collidepoint(mouse_x, mouse_y):
                    if tracking_mode_auto:
                        add_message('Manual tracking disabled in auto mode')
                        continue

                    with data_lock:
                        manual_track_busy = tracker_capture_in_progress
                    if manual_track_busy:
                        add_message('Camera module busy')
                        continue

                    target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes_snapshot) else None
                    if not target_icao:
                        min_track_dist = float("inf")
                        for icao, display_data in displayed_planes_snapshot.items():
                            plane = display_data.get("plane_data", {})
                            if not plane_matches_altitude_filter(plane, altitude_filter_threshold, altitude_filter_above):
                                continue
                            lat = plane.get("last_lat")
                            lon = plane.get("last_lon")
                            if lat is None or lon is None:
                                continue
                            dist = functions.calculate_distance(view_center_lat, view_center_lon, float(lat), float(lon))
                            if distance_filter_threshold_km > 0:
                                if distance_filter_outside and dist < distance_filter_threshold_km:
                                    continue
                                if not distance_filter_outside and dist > distance_filter_threshold_km:
                                    continue
                            if dist < min_track_dist:
                                min_track_dist = dist
                                target_icao = icao
                    if target_icao:
                        begin_camera_tracking(target_icao, logger=add_message, auto_select=False)
                    else:
                        add_message("No target plane available for tracking")
                    continue
                
                elif zoom_in_ctrl_rect.collidepoint(mouse_x, mouse_y):
                    if range_km > 25:
                        range_km -= 25

                elif zoom_out_ctrl_rect.collidepoint(mouse_x, mouse_y): #Zoom out
                    if range_km < 1000:
                        range_km += 25

                elif mode_toggle_rect.collidepoint(mouse_x, mouse_y):
                    offline = not offline
                    _config['offlineMode'] = offline
                    functions.save_config(_config)
                    add_message(f"Switched to {'offline' if offline else 'online'} mode")

                elif auto_track_mode_rect.collidepoint(mouse_x, mouse_y):
                    tracking_mode_auto = not tracking_mode_auto
                    auto_track_queue.clear()
                    auto_track_inside_icaos.clear()
                    add_message(f"Switched to {'auto' if tracking_mode_auto else 'manual'} camera tracking")
                    continue

                elif clear_graph_rect.collidepoint(mouse_x, mouse_y):
                    with data_lock:
                        active_count_history.clear()
                        total_seen_history.clear()
                        directional_hit_history.clear()
                    top_graph_last_bucket = None
                    if clear_top_graph_history(TOP_GRAPH_HISTORY_DIR, current_time):
                        add_message("Graph history cleared")
                    else:
                        add_message("Graph history clear failed")
                    continue

                elif restart_button_rect.collidepoint(mouse_x, mouse_y) or off_button_rect.collidepoint(mouse_x, mouse_y):
                    if restart_button_rect.collidepoint(mouse_x, mouse_y):
                        add_message("Restarting script")
                        functions.restart_script()
                        return
                    tracker_running = False
                    pygame.quit()
                    exit()
                clicked_plane = None
                with data_lock:
                    for icao, rect in plane_rects.items():
                        if rect.collidepoint(mouse_x, mouse_y):
                            clicked_plane = icao
                            break
                
                if clicked_plane:
                    selected_plane_icao = clicked_plane
                else:
                    if RADAR_RECT.collidepoint(mouse_x, mouse_y):
                        selected_plane_icao = None
        
        displayed_planes_snapshot = snapshot_displayed_planes()

        refresh_tracker_photo_surface()

        #Clear screen
        pygame.draw.rect(window, (0, 0, 0), (0, 0, width, height))
        
        #Draw radar section with clipping
        window.set_clip(RADAR_RECT)

        radar_map_image = radar_map_images.get(range_km)
        if radar_map_image is not None:
            if radar_map_image.get_size() != (RADAR_RECT.width, RADAR_RECT.height):
                radar_map_image = pygame.transform.smoothscale(radar_map_image, (RADAR_RECT.width, RADAR_RECT.height))
            window.blit(radar_map_image, RADAR_RECT.topleft)
        else:
            pygame.draw.rect(window, (0, 0, 0), RADAR_RECT)
        
        #Draw radar circles
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 100, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 200, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 300, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 400, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 500, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 600, 1)
        
        #Draw range labels
        range_steps = [100, 200, 300, 400, 500, 600]
        cos_45 = math.cos(math.radians(45))
        
        for radius in range_steps:
            label_x = RADAR_CENTER_X - (radius * cos_45)
            label_y = RADAR_CENTER_Y - (radius * cos_45)
            circle_distance_km = range_km * (radius / 600.0)
            label_value = convert_distance_from_km(circle_distance_km, distance_unit)
            label_text = str(round(label_value)) if label_value is not None else '-'
            draw_text.normal(window, label_text, text_font3, (225, 225, 225), int(label_x), int(label_y))
        
        auto_track_rect = build_auto_track_rect(range_km, view_center_lat, view_center_lon)
        if auto_track_rect is not None:
            rect_colour = (0, 255, 0) if tracking_mode_auto else (100, 100, 100)
            pygame.draw.rect(window, rect_colour, auto_track_rect, 1)

        #Draw home location marker
        home_x, home_y = functions.coords_to_xy(
            _config['myLat'], _config['myLon'], range_km,
            view_center_lat, view_center_lon, width, height,
            RADAR_CENTER_X, RADAR_CENTER_Y
        )
        pygame.draw.polygon(window, (0, 255, 255), [
            (home_x, home_y - 3), 
            (home_x + 3, home_y), 
            (home_x, home_y + 3), 
            (home_x - 3, home_y)
        ])
        
        #Draw airports - NOW using view_center instead of config location
        for key in airport_db.airports_uk:
            airport = airport_db.airports_uk[key]
            x, y = functions.coords_to_xy(airport["lat"], airport["lon"], range_km, view_center_lat, view_center_lon, width, height, RADAR_CENTER_X, RADAR_CENTER_Y)
            pygame.draw.polygon(window, (0, 0, 255), [(x, y - 2), (x + 2, y), (x, y + 2), (x - 2, y)])
            draw_text.center(window, airport["airport_name"], text_font3, (255, 255, 255), x, y - 10)
        
        displayed_count = 0
        closest_plane = None
        min_dist = float('inf')
        
        
        #Calculate distances using view_center instead of config location
        for icao, display_data in displayed_planes_snapshot.items():
            plane = display_data.get("plane_data", {})
            if not plane_matches_altitude_filter(plane, altitude_filter_threshold, altitude_filter_above):
                continue
            if rarity_filter_selected:
                _r = get_rarity_rating(plane.get('model', '-'), model_ratings)
                _t = 10 if _r >= 10 else (8 if _r >= 8 else (6 if _r >= 6 else (4 if _r >= 4 else 1)))
                if _t not in rarity_filter_selected:
                    continue
            lat = plane.get("last_lat")
            lon = plane.get("last_lon")
            if lat is not None and lon is not None:
                dist = functions.calculate_distance(view_center_lat, view_center_lon, float(lat), float(lon))
                plane["distance"] = dist
                if distance_filter_threshold_km > 0:
                    if distance_filter_outside and dist < distance_filter_threshold_km:
                        continue
                    if not distance_filter_outside and dist > distance_filter_threshold_km:
                        continue
                if dist < min_dist:
                    min_dist = dist
                    closest_plane = icao
                displayed_count += 1

        heatmap_points = []
        if radar_heatmap_enabled:
            with data_lock:
                prune_history(heatmap_hits, DIRECTIONAL_HISTORY_SECONDS, current_time)
                for _, heat_lat, heat_lon in heatmap_hits:
                    try:
                        heat_x, heat_y = functions.coords_to_xy(float(heat_lat), float(heat_lon), range_km, view_center_lat, view_center_lon, width, height, RADAR_CENTER_X, RADAR_CENTER_Y)
                        if RADAR_RECT.collidepoint(heat_x, heat_y):
                            heatmap_points.append((heat_x, heat_y))
                    except (TypeError, ValueError):
                        continue

        if radar_heatmap_enabled:
            draw_radar_heatmap(window, RADAR_RECT, heatmap_points, pygame)
            if radar_map_image is not None:
                window.blit(radar_map_image, RADAR_RECT.topleft)
            # Redraw radar rings and labels on top of the heatmap squares.
            window.set_clip(RADAR_RECT)
            pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 100, 1)
            pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 200, 1)
            pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 300, 1)
            pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 400, 1)
            pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 500, 1)
            pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 600, 1)

            range_steps = [100, 200, 300, 400, 500, 600]
            cos_45 = math.cos(math.radians(45))
            for radius in range_steps:
                label_x = RADAR_CENTER_X - (radius * cos_45)
                label_y = RADAR_CENTER_Y - (radius * cos_45)
                circle_distance_km = range_km * (radius / 600.0)
                label_value = convert_distance_from_km(circle_distance_km, distance_unit)
                label_text = str(round(label_value)) if label_value is not None else '-'
                draw_text.normal(window, label_text, text_font3, (225, 225, 225), int(label_x), int(label_y))

        #Draw radar elements with clipping
        window.set_clip(RADAR_RECT)
        
        #Draw planes with unique highlight
        current_plane_rects = {}
        current_auto_track_icaos = set()
        target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes_snapshot) else closest_plane

        for icao, display_data in displayed_planes_snapshot.items():
            plane = display_data["plane_data"]
            if not plane_matches_altitude_filter(plane, altitude_filter_threshold, altitude_filter_above):
                continue
            if not plane_matches_distance_filter(plane, distance_filter_threshold_km, distance_filter_outside):
                continue
            if rarity_filter_selected:
                _r = get_rarity_rating(plane.get('model', '-'), model_ratings)
                _t = 10 if _r >= 10 else (8 if _r >= 8 else (6 if _r >= 6 else (4 if _r >= 4 else 1)))
                if _t not in rarity_filter_selected:
                    continue
            lat = plane.get("last_lat")
            lon = plane.get("last_lon")
            if lat is None or lon is None:
                continue

            #Calculate fade
            time_remaining = display_data["display_until"] - current_time
            if time_remaining <= 0:
                continue
            fade_value = max(10, int(255 * (time_remaining / fade_duration))) if time_remaining < fade_duration else 255

            try:
                if hide_planes_mode == 2:
                    continue

                #NOW using view_center instead of config location
                x, y = functions.coords_to_xy(float(lat), float(lon), range_km, view_center_lat, view_center_lon, width, height, RADAR_CENTER_X, RADAR_CENTER_Y)

                #Calculate Heading
                track = plane.get("track")
                if track != "-" and track is not None:
                    try:
                        heading = -float(track)
                        plane_headings[icao] = heading
                    except ValueError:
                        heading = plane_headings.get(icao, 0.0)
                else:
                    prev_lat = plane.get("prev_lat")
                    prev_lon = plane.get("prev_lon")
                    if prev_lat is not None and prev_lon is not None and (abs(float(prev_lat) - float(lat)) > 1e-6 or abs(float(prev_lon) - float(lon)) > 1e-6):
                        heading = functions.calculate_heading(prev_lat, prev_lon, lat, lon)
                        plane_headings[icao] = heading
                    else:
                        heading = plane_headings.get(icao, 0.0)

                if tracking_mode_auto and auto_track_rect is not None and auto_track_rect.collidepoint(int(x), int(y)):
                    current_auto_track_icaos.add(icao)

                rating = get_rarity_rating(plane.get('model', '-'), model_ratings)
                rarity_col = get_rarity_colour(rating)

                if icao == target_icao:
                    location_history = plane.get("location_history", {})
                    if location_history and isinstance(location_history, dict) and len(location_history) > 1:
                        #Sort coordinates by timestamp to get chronological order
                        sorted_coords = sorted(location_history.items())

                        #Get current position to exclude it from trajectory
                        current_lat = plane.get("last_lat")
                        current_lon = plane.get("last_lon")

                        #Convert all coordinates to x,y points - NOW using view_center
                        trajectory_points = []
                        last_valid_lat = None
                        last_valid_lon = None

                        for timestamp, coords in sorted_coords:
                            try:
                                hist_lat, hist_lon = coords

                                #Skip the current position (it's drawn as the plane icon)
                                if current_lat is not None and current_lon is not None:
                                    if abs(float(hist_lat) - float(current_lat)) < 0.0001 and abs(float(hist_lon) - float(current_lon)) < 0.0001:
                                        continue

                                #Detect and skip impossible jumps (more than 100km from last point)
                                if last_valid_lat is not None and last_valid_lon is not None:
                                    distance = functions.calculate_distance(last_valid_lat, last_valid_lon, float(hist_lat), float(hist_lon))
                                    if distance > 100:  #Skip jumps greater than 100km
                                        add_message(f"Skipped invalid trajectory point: {distance:.1f}km jump")
                                        continue

                                hist_x, hist_y = functions.coords_to_xy(
                                    float(hist_lat), float(hist_lon), range_km,
                                    view_center_lat, view_center_lon,
                                    width, height, RADAR_CENTER_X, RADAR_CENTER_Y
                                )

                                #Only add points that are on or near the screen
                                if -500 <= hist_x <= width + 500 and -500 <= hist_y <= height + 500:
                                    trajectory_points.append((hist_x, hist_y))
                                    last_valid_lat = float(hist_lat)
                                    last_valid_lon = float(hist_lon)

                            except Exception as e:
                                add_message(f"Trajectory point error: {str(e)[:30]}")
                                continue

                        #Append current plane position to close the gap to the icon
                        trajectory_points.append((int(x), int(y)))

                        #Draw lines connecting the trajectory points
                        if len(trajectory_points) > 1:
                            trajectory_col = tuple(max(0, c - 50) for c in rarity_col)
                            pygame.draw.lines(window, trajectory_col, False, trajectory_points)

                            for i in trajectory_points[:-1]:
                                pygame.draw.circle(window, (0, 255, 255), i, 1)

                coloured = plane_icon_white.copy()
                coloured.fill((*rarity_col, fade_value), special_flags=pygame.BLEND_RGBA_MULT)
                rotated_image = pygame.transform.rotate(coloured, heading)
                new_rect = rotated_image.get_rect(center=(x, y))
                window.blit(rotated_image, new_rect)
                current_plane_rects[icao] = new_rect

                #Labels
                label_colour = rarity_col
                flight = plane.get("flight", "-")
                display_label = flight if (flight and flight != "-") else icao
                if hide_planes_mode == 0:
                    if not offline and plane.get('manufacturer') != "-":
                        draw_text.fading(window, display_label, text_font3, label_colour, x, y - 26, fade_value)
                        draw_text.fading(window, plane.get("owner", "-"), text_font3, label_colour, x, y - 13, fade_value)
                        draw_text.fading(window, f"{plane.get('manufacturer')} {plane.get('model')}", text_font3, label_colour, x, y + 13, fade_value)
                        draw_text.fading(window, f"{plane.get('altitude', '-')}ft", text_font3, label_colour, x, y + 26, fade_value)
                    else:
                        draw_text.fading(window, display_label, text_font3, label_colour, x, y - 13, fade_value)
                        draw_text.fading(window, f"{plane.get('altitude', '-')}ft", text_font3, label_colour, x, y + 13, fade_value)

            except Exception as e:
                log.error(f"Draw error for {icao} at x={x} y={y}: {e}")
        
        with data_lock:
            plane_rects = current_plane_rects
        
        if tracking_mode_auto:
            new_auto_track_icaos = current_auto_track_icaos - auto_track_inside_icaos
            for icao in sorted(new_auto_track_icaos):
                if icao not in auto_track_queue:
                    auto_track_queue.append(icao)
            auto_track_inside_icaos.clear()
            auto_track_inside_icaos.update(current_auto_track_icaos)

            with data_lock:
                camera_busy_for_auto = tracker_capture_in_progress
            if not camera_busy_for_auto:
                while auto_track_queue:
                    queued_icao = auto_track_queue.popleft()
                    if begin_camera_tracking(queued_icao, logger=add_message, auto_select=True):
                        planecam_auto_capture_last_time[queued_icao] = current_time
                        break
        else:
            auto_track_queue.clear()
            auto_track_inside_icaos.clear()

        # Periodic auto-capture (auto-track mode only): every plane currently inside the
        # auto-track zone gets its own independent 15s cooldown, not a shared global one -
        # one plane's cooldown doesn't block capturing a different plane in the meantime.
        if tracking_mode_auto and current_auto_track_icaos:
            with data_lock:
                _ac_busy = tracker_capture_in_progress
            if not _ac_busy:
                _ac_candidates = [
                    icao for icao in current_auto_track_icaos
                    if current_time - planecam_auto_capture_last_time.get(icao, 0.0) >= PLANECAM_AUTO_CAPTURE_INTERVAL
                ]
                if _ac_candidates:
                    _ac_target = min(_ac_candidates, key=lambda icao: planecam_auto_capture_last_time.get(icao, 0.0))
                    if begin_camera_tracking(_ac_target, logger=add_message, auto_select=True):
                        planecam_auto_capture_last_time[_ac_target] = current_time

        # Reset scroll offset when the target plane changes
        _scroll_target_icao = selected_plane_icao if selected_plane_icao else closest_plane
        if _scroll_target_icao != _prev_target_icao_for_scroll:
            camera_scroll_offset = 0
            _prev_target_icao_for_scroll = _scroll_target_icao

        #Reset clip for UI elements outside radar
        window.set_clip(None)
        
        #Draw radar border
        pygame.draw.rect(window, (225, 225, 225), RADAR_RECT, 2)
        
        #Draw Off button
        pygame.draw.rect(window, (255, 0, 0), off_button_rect)

        pygame.draw.rect(window, (255, 0, 0), clear_graph_rect)
        
        #right sidebar
        current_time_str = strftime("%H:%M:%S", localtime())
        draw_text.center(window, current_time_str, text_font2, (255, 0, 0), SIDEBAR_X + SIDEBAR_WIDTH // 2, 40)
        
        #Sys stats
        sys_y = 85
        col1 = SIDEBAR_X + 10
        col2 = SIDEBAR_X + SIDEBAR_WIDTH // 2 - 250
        with data_lock:
            tracker_stats_snapshot = dict(tracker_device_stats)

        tracker_temp_text = f"TEMP:{round(tracker_stats_snapshot['temp'])}C" if tracker_stats_snapshot['temp'] is not None else "TEMP: N/A"
        tracker_ram_text = f"RAM:{round(tracker_stats_snapshot['ram'])}%" if tracker_stats_snapshot['ram'] is not None else "RAM: N/A"
        tracker_cpu_text = f"CPU:{round(tracker_stats_snapshot['cpu'])}%" if tracker_stats_snapshot['cpu'] is not None else "CPU: N/A"
        tracker_disk_text = f"DISK:{round(tracker_stats_snapshot['disk'], 1)}GB" if tracker_stats_snapshot['disk'] is not None else "DISK: N/A"

        api_status_connected = (not offline) and network_available and any(
            display_data.get("plane_data", {}).get('manufacturer', '-') != '-'
            for display_data in displayed_planes_snapshot.values()
        )
        internet_status_connected = network_available

        api_status_colour = (0, 255, 0) if api_status_connected else (255, 0, 0)
        internet_status_colour = (0, 255, 0) if internet_status_connected else (255, 0, 0)
        tracker_status_colour = (0, 255, 0) if tracker_status_connected else (255, 0, 0)



        #Separator
        pygame.draw.line(window, (100, 100, 100), (SIDEBAR_X + 5, sys_y - 10), (SIDEBAR_X + SIDEBAR_WIDTH - 10, sys_y - 10), 1)

        active_graph_rect = pygame.Rect(SIDEBAR_X + 300, sys_y, 240, 130)
        total_graph_rect = pygame.Rect(SIDEBAR_X + 580, sys_y, 240, 130)

        with _flight_stats_lock:
            stats = dict(_flight_stats_cache)
        total_seen = stats.get('total', 0)

        if displayed_count > 0 or (current_time - start_time) >= GRAPH_SAMPLE_INTERVAL:
            top_graph_last_bucket = persist_top_graph_sample(active_count_history, total_seen_history, displayed_count, total_seen, TOP_GRAPH_HISTORY_DIR, top_graph_last_bucket, GRAPH_SAMPLE_INTERVAL, TOP_GRAPH_HISTORY_SECONDS, current_time)

        active_peak = max((sample[1] for sample in active_count_history), default=0)
        active_y_max = max(10, ((active_peak + 10 + 9) // 10) * 10)

        rarity_counts = {10: 0, 8: 0, 6: 0, 4: 0, 1: 0}
        for _icao, _display_data in displayed_planes_snapshot.items():
            _plane = _display_data.get("plane_data", {})
            if not plane_matches_altitude_filter(_plane, altitude_filter_threshold, altitude_filter_above):
                continue
            if not plane_matches_distance_filter(_plane, distance_filter_threshold_km, distance_filter_outside):
                continue
            _rating = get_rarity_rating(_plane.get('model', '-'), model_ratings)
            if _rating >= 10:
                rarity_counts[10] += 1
            elif _rating >= 8:
                rarity_counts[8] += 1
            elif _rating >= 6:
                rarity_counts[6] += 1
            elif _rating >= 4:
                rarity_counts[4] += 1
            else:
                rarity_counts[1] += 1

        draw_line_graph(window, active_graph_rect, list(active_count_history), active_y_max, draw_text, text_font3, pygame, active_peak, current_time, TOP_GRAPH_HISTORY_SECONDS, "ACTIVE")
        total_peak = max((sample[1] for sample in total_seen_history), default=0)
        total_y_max = max(100, ((total_peak + 100 + 99) // 100) * 100)
        draw_line_graph(window, total_graph_rect, list(total_seen_history), total_y_max, draw_text, text_font3, pygame, total_peak, current_time, TOP_GRAPH_HISTORY_SECONDS, "TOTAL")

        #Flight stats
        furthest_detected = stats.get('furthest_detected')
        highest_detected = stats.get('highest_detected')
        furthest_text = format_distance(furthest_detected, distance_unit, 1) if furthest_detected is not None else '-'
        highest_text = f"{highest_detected:,}ft" if highest_detected is not None else '-'
        avg_alt_text = f"{stats['avg_altitude']:,}ft" if stats.get('avg_altitude') is not None else '-'
        avg_spd_text = f"{stats['avg_speed']}kts" if stats.get('avg_speed') is not None else '-'
        max_spd_text = f"{stats['max_speed']}kts" if stats.get('max_speed') is not None else '-'
        avg_mach_text = f"{stats['avg_mach']:.3f}" if stats.get('avg_mach') is not None else '-'
        top_airline_name = (stats['top_airline']['name'] or '-')[:16]
        top_mfr_name = (stats['top_manufacturer']['name'] or '-')[:14]
        top_aircraft_name = (stats['top_aircraft']['name'] or '-')[:16]

        _sp = 17
        col_r = col1 + 155
        draw_text.normal(window, f"Total Seen: {stats['total']:,}", text_font3, (255, 255, 255), col1, sys_y)
        draw_text.normal(window, f"Airlines: {stats['unique_airlines']}", text_font3, (255, 255, 255), col1, sys_y + _sp)
        draw_text.normal(window, f"Models: {stats['unique_models']}", text_font3, (255, 255, 255), col1, sys_y + _sp * 2)
        draw_text.normal(window, f"Active: {displayed_count}", text_font3, (0, 255, 0), col1, sys_y + _sp * 3)
        draw_text.normal(window, f"Top Manufacturer: {top_mfr_name}", text_font3, (255, 255, 255), col1, sys_y + _sp * 4 + 15)
        draw_text.normal(window, f"Top Airline: {top_airline_name}", text_font3, (255, 255, 255), col1, sys_y + _sp * 5 + 15)
        draw_text.normal(window, f"Top Aircraft: {top_aircraft_name}", text_font3, (255, 255, 255), col1, sys_y + _sp * 6 + 15)

        draw_text.normal(window, f"Max Spd: {max_spd_text}", text_font3, (255, 255, 255), col_r, sys_y)
        draw_text.normal(window, f"Avg Mach: {avg_mach_text}", text_font3, (255, 255, 255), col_r, sys_y + _sp)
        draw_text.normal(window, f"Furthest: {furthest_text}", text_font3, (255, 255, 255), col_r, sys_y + _sp * 2)
        draw_text.normal(window, f"Highest: {highest_text}", text_font3, (255, 255, 255), col_r, sys_y + _sp * 3)

        #Sperator 2
        separator_y = (315 // 2) + 68
        pygame.draw.line(window, (100, 100, 100), (SIDEBAR_X + 5, separator_y), (SIDEBAR_X + SIDEBAR_WIDTH - 10, separator_y), 1)

        altitude_graph_rect = pygame.Rect(SIDEBAR_X + 300, separator_y + 10, 240, 130)
        hits_graph_rect = pygame.Rect(SIDEBAR_X + 580, separator_y + 10, 240, 130)

        #Track plane button
        track_button_colour = (120, 120, 120) if (tracking_mode_auto or tracker_capture_in_progress) else (255, 255, 255)
        pygame.draw.rect(window, track_button_colour, track_plane_button_rect, 0)
        pygame.draw.rect(window, (100, 100, 100), track_plane_button_rect, 1)
        scaled_track_target_icon = pygame.transform.smoothscale(track_target_icon, (32, 32))
        window.blit(scaled_track_target_icon, scaled_track_target_icon.get_rect(center=track_plane_button_rect.center))

        #Plane Info
        target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes_snapshot) else closest_plane
        p_data = displayed_planes_snapshot.get(target_icao, {}).get("plane_data") if target_icao else None
        graph_plane_icao = target_icao
        graph_plane_data = p_data


        altitude_samples = []
        hit_samples = []
        if graph_plane_data:
            altitude_history = graph_plane_data.get("altitude_history", deque())
            prune_history(altitude_history, PLANE_GRAPH_HISTORY_SECONDS, current_time)
            altitude_samples = list(altitude_history)

            hit_history = graph_plane_data.get("hit_history", deque())
            prune_history(hit_history, PLANE_GRAPH_HISTORY_SECONDS, current_time)
            hit_samples = list(hit_history)

        draw_line_graph(window, altitude_graph_rect, altitude_samples, 50000, draw_text, text_font3, pygame, 50000, current_time, PLANE_GRAPH_HISTORY_SECONDS, "ALTITUDE")
        hits_peak = max((sample[1] for sample in hit_samples), default=0)
        hits_y_max = max(10, ((hits_peak + 10 + 9) // 10) * 10)
        selected_total_hits = graph_plane_data.get("total_hit_count", 0) if graph_plane_data else 0
        draw_line_graph(window, hits_graph_rect, hit_samples, hits_y_max, draw_text, text_font3, pygame, selected_total_hits, current_time, PLANE_GRAPH_HISTORY_SECONDS, "HITS")
        
        if p_data:
            mfg = p_data.get('manufacturer', '-')
            model = p_data.get('model', '-')
            owner = p_data.get('owner', '-')
            model_display = (f"{mfg} {model}")[:28] if mfg != '-' and model != '-' else "Unidentified Aircraft"
            owner_display = owner[:28] if owner != '-' else "Unidentified Airline"

            p_rating = get_rarity_rating(model, model_ratings)
            p_rarity_col = get_rarity_colour(p_rating)

            id_y = separator_y + 10
            draw_text.normal(window, model_display, plane_identity_font, p_rarity_col, col1, id_y)
            draw_text.normal(window, owner_display, plane_identity_font, p_rarity_col, col1, id_y + 16)

            spacing = 18
            stat_y = 290
            lx = col1
            rx = col2

            def rnd(val, dec=1):
                try: return round(float(val), dec)
                except: return "-"

            flight = p_data.get('flight', '-')
            alt = p_data.get('altitude', '-')
            baro_rate = p_data.get('baro_rate', '-')
            reg = p_data.get('registration', '-')
            spd = p_data.get('speed', '-')
            total_hits = p_data.get("total_hit_count", 0)

            draw_text.normal(window, f"FLIGHT: {flight if flight != '-' else 'N/A'}", stat_font, (255, 255, 255), lx, stat_y)
            draw_text.normal(window, f"HEX: {target_icao or 'N/A'}", stat_font, (255, 255, 255), rx, stat_y)

            draw_text.normal(window, f"ALT: {f'{alt}ft' if alt != '-' else 'N/A'}", stat_font, (255, 255, 255), lx, stat_y + spacing)
            draw_text.normal(window, f"REG: {reg if reg != '-' else 'N/A'}", stat_font, (255, 255, 255), rx, stat_y + spacing)

            baro_display = f"{baro_rate:+d}fpm" if baro_rate != '-' else 'N/A'
            draw_text.normal(window, f"BARO: {baro_display}", stat_font, (255, 255, 255), lx, stat_y + spacing * 2)
            draw_text.normal(window, f"SPD: {f'{rnd(spd)}kt' if spd != '-' else 'N/A'}", stat_font, (255, 255, 255), rx, stat_y + spacing * 2)

            draw_text.normal(window, f"HITS: {int(total_hits)}", stat_font, (255, 255, 255), lx, stat_y + spacing * 3)

            dist_km = p_data.get('distance', '-')
            if dist_km != '-' and dist_km is not None:
                try:
                    dist_converted = convert_distance_from_km(float(dist_km), distance_unit)
                    dist_text = f"{rnd(dist_converted, 1)}{distance_unit.lower()}"
                except (TypeError, ValueError):
                    dist_text = 'N/A'
            else:
                dist_text = 'N/A'
            draw_text.normal(window, f"DST: {dist_text}", stat_font, (255, 255, 255), rx, stat_y + spacing * 3)
        else:
            draw_text.center(window, "NO PLANE SELECTED", text_font1, (100, 100, 100), SIDEBAR_X + SIDEBAR_WIDTH // 2, separator_y + 80)

        #LOGS BOX
        logs_y = altitude_graph_rect.bottom + 10
        bottom_row_y = filter_panel_rect.bottom + 10
        log_h = (height - 10) - bottom_row_y
        pygame.draw.rect(window, (20, 20, 20), (filter_panel_rect.left, bottom_row_y, filter_panel_rect.width, log_h), 0)
        pygame.draw.rect(window, (100, 100, 100), (filter_panel_rect.left, bottom_row_y, filter_panel_rect.width, log_h), 1)

        with data_lock:
            prune_history(directional_hit_history, DIRECTIONAL_HISTORY_SECONDS, current_time)
            directional_plot_history = [(timestamp, counts.copy()) for timestamp, counts in directional_hit_history]
        #FILTERS
        draw_altitude_filter(
            window, filter_panel_rect, filter_checkbox_rect, slider_track_rect, 
            filter_slider_handle_rect, altitude_slider_up_rect, altitude_slider_down_rect, 
            altitude_filter_threshold, altitude_filter_above, distance_filter_checkbox_rect, 
            distance_slider_track_rect, distance_filter_slider_handle_rect, distance_slider_up_rect, 
            distance_slider_down_rect, distance_filter_threshold_km, distance_filter_outside, 
            distance_unit, distance_unit_rects, draw_text, stat_font, graph_time_font, text_font3, pygame
        )
        filter_button_icons = {
            'heatmap_on': heatmap_on_icon,
            'heatmap_off': heatmap_off_icon,
            'plane_and_text': plane_and_text_mode_icon,
            'plane_only': plane_only_mode_icon,
            'hide_plane': hide_plane_mode_icon,
            'clear_filters': clear_filters_icon,
        }
        draw_filter_action_buttons(
            window, heatmap_button_rect, hide_planes_button_rect,
            reset_filters_button_rect, radar_heatmap_enabled,
            hide_planes_mode, filter_button_icons, pygame
        )
        draw_rarity_filter(
            window, rarity_checkbox_rects, rarity_counts, rarity_filter_selected,
            RARITY_TIERS, draw_text, text_font3, pygame
        )

        #INFO BOX — polar plot + system stats
        info_box_rect = pygame.Rect(SIDEBAR_X + 5, logs_y, int((SIDEBAR_WIDTH / 2) - 10), filter_panel_rect.height)
        pygame.draw.rect(window, (20, 20, 20), info_box_rect, 0)
        pygame.draw.rect(window, (100, 100, 100), info_box_rect, 1)

        polar_size = info_box_rect.height
        polar_plot_rect = pygame.Rect(info_box_rect.right - polar_size, info_box_rect.top, polar_size, polar_size)
        draw_polar_coverage_plot(
            window, polar_plot_rect, directional_plot_history, draw_text, text_font3, graph_time_font,
            pygame, current_time, DIRECTIONAL_HISTORY_SECONDS, DIRECTIONAL_SECTOR_COUNT
        )

        sx = info_box_rect.left + 8
        sy = info_box_rect.top + 3
        sp = 15

        draw_text.normal(window, "Controller:", stat_font, (255, 255, 255), sx, sy)
        draw_text.normal(window, f"TEMP:{round(cpu_temp)}C", stat_font, (255, 255, 255), sx, sy + sp)
        draw_text.normal(window, f"RAM:{ram_percentage}%", stat_font, (255, 255, 255), sx, sy + sp * 2)
        draw_text.normal(window, f"CPU:{cpu_percentage}%", stat_font, (255, 255, 255), sx, sy + sp * 3)
        draw_text.normal(window, f"DISK:{disk_free}GB", stat_font, (255, 255, 255), sx, sy + sp * 4)
        draw_text.normal(window, "Camera:", stat_font, (255, 255, 255), sx, sy + sp * 5 + 5)
        draw_text.normal(window, tracker_temp_text, stat_font, (255, 255, 255), sx, sy + sp * 6 + 5)
        draw_text.normal(window, tracker_ram_text, stat_font, (255, 255, 255), sx, sy + sp * 7 + 5)
        draw_text.normal(window, tracker_cpu_text, stat_font, (255, 255, 255), sx, sy + sp * 8 + 5)
        draw_text.normal(window, tracker_disk_text, stat_font, (255, 255, 255), sx, sy + sp * 9 + 5)

        dot_y = sy + sp * 10 + 10
        pygame.draw.circle(window, api_status_colour, (sx + 5, dot_y + 9), 5)
        draw_text.normal(window, "API", stat_font, (255, 255, 255), sx + 14, dot_y)
        pygame.draw.circle(window, internet_status_colour, (sx + 5, dot_y + sp + 9), 5)
        draw_text.normal(window, "Internet", stat_font, (255, 255, 255), sx + 14, dot_y + sp)
        pygame.draw.circle(window, tracker_status_colour, (sx + 5, dot_y + sp * 2 + 9), 5)
        draw_text.normal(window, "Camera", stat_font, (255, 255, 255), sx + 14, dot_y + sp * 2)

        _LOG_SCROLLBAR_W = 6
        log_scrollbar_track_rect = pygame.Rect(filter_panel_rect.right - _LOG_SCROLLBAR_W - 1, bottom_row_y + 1, _LOG_SCROLLBAR_W, log_h - 2)
        log_max_w = filter_panel_rect.width - 10 - _LOG_SCROLLBAR_W - 2
        lines_per_page = max(1, (log_h - 4) // 11)
        with data_lock:
            all_msgs = list(message_queue)
        total_msgs = len(all_msgs)
        max_scroll = max(0, total_msgs - lines_per_page)
        log_scroll_offset = min(log_scroll_offset, max_scroll)
        start_idx = max(0, total_msgs - lines_per_page - log_scroll_offset)
        end_idx = max(0, total_msgs - log_scroll_offset)
        y_msg = bottom_row_y + 2
        for message in all_msgs[start_idx:end_idx]:
            colour = (200, 200, 200)
            if "WARNING" in message:
                colour = (255, 0, 0)
            elif "NEW" in message:
                colour = (0, 255, 0)
            draw_text.normal(window, truncate_log_text(str(message), text_font3, log_max_w), text_font3, colour, filter_panel_rect.left + 5, y_msg)
            y_msg += 11
            if y_msg > bottom_row_y + log_h - 10:
                break
        # Draw scrollbar
        pygame.draw.rect(window, (40, 40, 40), log_scrollbar_track_rect)
        if total_msgs > lines_per_page:
            thumb_h = max(20, int(log_scrollbar_track_rect.height * lines_per_page / total_msgs))
            thumb_travel = log_scrollbar_track_rect.height - thumb_h
            # offset=0 (newest) → thumb at bottom; offset=max_scroll (oldest) → thumb at top
            thumb_y = log_scrollbar_track_rect.top + int(thumb_travel * (1.0 - log_scroll_offset / max_scroll)) if max_scroll > 0 else log_scrollbar_track_rect.top + thumb_travel
            log_scrollbar_thumb_rect = pygame.Rect(log_scrollbar_track_rect.left, thumb_y, _LOG_SCROLLBAR_W, thumb_h)
            pygame.draw.rect(window, (140, 140, 140), log_scrollbar_thumb_rect)
        else:
            log_scrollbar_thumb_rect = pygame.Rect(0, 0, 0, 0)

        #CAMERA IMAGE
        cam_w = int((SIDEBAR_WIDTH / 2) - 10)
        cam_h = int(cam_w * 3 / 4)
        cam_rect = pygame.Rect(SIDEBAR_X + 5, bottom_row_y, cam_w, cam_h)
        pygame.draw.rect(window, (20, 20, 20), cam_rect, 0)
        pygame.draw.rect(window, (100, 100, 100), cam_rect, 1)

        with data_lock:
            camera_busy = tracker_capture_in_progress
            camera_connected = tracker_status_connected
            _latest_cam_surface = tracker_photo_surface
            _latest_cam_meta = dict(tracker_photo_meta)

        _scroll_display_icao = selected_plane_icao if selected_plane_icao else closest_plane
        _photo_history = tracker_plane_photo_history.get(_scroll_display_icao, []) if _scroll_display_icao else []
        if _photo_history:
            _display_idx = min(camera_scroll_offset, len(_photo_history) - 1)
            camera_photo_surface, cam_meta = _photo_history[_display_idx]
        else:
            camera_photo_surface = None if _scroll_display_icao else _latest_cam_surface
            cam_meta = _latest_cam_meta

        if camera_photo_surface is not None:
            img_w, img_h = camera_photo_surface.get_size()
            if img_w > 0 and img_h > 0:
                scale = min(cam_rect.width / img_w, cam_rect.height / img_h)
                scaled_size = (max(1, int(img_w * scale)), max(1, int(img_h * scale)))
                scaled_surface = pygame.transform.smoothscale(camera_photo_surface, scaled_size)
                window.blit(scaled_surface, scaled_surface.get_rect(center=cam_rect.center))
        else:
            placeholder = 'CAMERA BUSY' if camera_busy else 'NO IMAGE'
            draw_text.center(window, placeholder, text_font1, (100, 100, 100), cam_rect.centerx, cam_rect.centery)

        # Scroll buttons below camera image
        for _scroll_rect, _arrow_dir in [(cam_scroll_left_rect, 'L'), (cam_scroll_right_rect, 'R')]:
            pygame.draw.rect(window, (255, 255, 255), _scroll_rect, 0)
            pygame.draw.rect(window, (100, 100, 100), _scroll_rect, 1)
            _cx, _cy = _scroll_rect.centerx, _scroll_rect.centery
            if _arrow_dir == 'L':
                pygame.draw.polygon(window, (0, 0, 0), [(_cx + 8, _cy - 8), (_cx - 8, _cy), (_cx + 8, _cy + 8)])
            else:
                pygame.draw.polygon(window, (0, 0, 0), [(_cx - 8, _cy - 8), (_cx + 8, _cy), (_cx - 8, _cy + 8)])

        if _photo_history:
            _total_photos = len(_photo_history)
            _shown_idx = min(camera_scroll_offset, _total_photos - 1)
            draw_text.right(window, f"{_shown_idx + 1}/{_total_photos}", stat_font, (200, 200, 200), cam_scroll_right_rect.right, cam_scroll_right_rect.bottom + 5)

        cam_status = 'BUSY' if camera_busy else ('CONNECTED' if camera_connected else 'OFFLINE')
        cam_pan = cam_meta.get('pan', '-')
        cam_tilt = cam_meta.get('tilt', '-')
        cam_sx = cam_rect.left
        cam_sy = cam_rect.bottom + 10
        cam_sp = 15
        draw_text.normal(window, f"STATUS: {cam_status}", stat_font, (200, 200, 200), cam_sx, cam_sy)
        draw_text.normal(window, f"PAN: {cam_pan}", stat_font, (200, 200, 200), cam_sx, cam_sy + cam_sp)
        draw_text.normal(window, f"TILT: {cam_tilt}", stat_font, (200, 200, 200), cam_sx, cam_sy + cam_sp * 2)

        #TOOLBAR
        toolbar_buttons = [
            (zoom_in_ctrl_rect, zoom_in_icon),
            (zoom_out_ctrl_rect, zoom_out_icon),
            (mode_toggle_rect, offline_mode_icon if offline else online_mode_icon),
            (auto_track_mode_rect, manual_tracking_icon if tracking_mode_auto else auto_tracking_icon),
            (restart_button_rect, restart_icon),
            (clear_graph_rect, clear_graph_icon),
            (off_button_rect, shutdown_icon),
        ]
        for rect, icon in toolbar_buttons:
            pygame.draw.rect(window, (255, 255, 255), rect, 0)
            pygame.draw.rect(window, (100, 100, 100), rect, 1)
            scaled_icon = pygame.transform.smoothscale(icon, (rect.width - 8, rect.height - 8))
            icon_rect = scaled_icon.get_rect(center=rect.center)
            window.blit(scaled_icon, icon_rect)

        pygame.display.update()
        time.sleep(0.05)

if __name__ == "__main__":
    main()




