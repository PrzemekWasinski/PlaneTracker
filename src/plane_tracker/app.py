import json
from pathlib import Path
import sys
import time
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

from collections import deque
from concurrent.futures import ProcessPoolExecutor

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IS_WINDOWS = sys.platform.startswith("win")

DEFAULT_PREVIEW = IS_WINDOWS or os.environ.get("PLANE_TRACKER_DEV_GUI") == "1"
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

from . import legacy_functions as functions
from .adsb import processor
from .aircraft import airports as airport_db
from .aircraft.rarity import build_model_counts, compute_ratings, get_rarity_colour, get_rarity_rating
from .core.compatibility import bind_module
from .gui.legacy import text as draw_text
from .gui.legacy.widgets import draw_altitude_filter, draw_filter_action_buttons, draw_line_graph, draw_polar_coverage_plot, draw_rarity_filter, plane_matches_altitude_filter, plane_matches_distance_filter
from .gui import preview_data
from .history.csv_storage import save_flight_history, save_plane_to_csv
from .history import runtime as history_runtime
from .history.samples import append_directional_hit, append_sample, clear_top_graph_history, load_top_graph_history, persist_top_graph_sample, prune_history
from .services import aircraft_api
from .services.network import can_retry_plane_api, check_network, fetch_plane_info
from . import orchestration

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


_config = functions.load_config()
_config.setdefault('screenWidth', 1920)
_config.setdefault('screenHeight', 1080)
_config.setdefault('flightHistoryDir', './flight_history')
_config.setdefault('offlineMode', False)
_config.setdefault('myLat', 0.0)
_config.setdefault('myLon', 0.0)

FLIGHT_HISTORY_DIR = _config['flightHistoryDir']
model_counts = build_model_counts(FLIGHT_HISTORY_DIR)
model_ratings = compute_ratings(model_counts)

READSB_JSON_PATH = "/run/readsb/aircraft.json"


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


PLANE_API_RETRY_DELAY = 60
ACTIVE_PLANE_RETENTION_SECONDS = 30 * 60


data_lock = threading.Lock()


TOP_GRAPH_HISTORY_SECONDS = 24 * 60 * 60
PLANE_GRAPH_HISTORY_SECONDS = 30 * 60
GRAPH_SAMPLE_INTERVAL = 60
PLANE_ALTITUDE_SAMPLE_INTERVAL = 0
PLANE_HIT_SAMPLE_INTERVAL = 60
DIRECTIONAL_HISTORY_SECONDS = 24 * 60 * 60
DIRECTIONAL_SECTOR_COUNT = 8
TOP_GRAPH_HISTORY_DIR = "stats_history"

active_count_history = deque()
total_seen_history = deque()
directional_hit_history = deque()


ACTIVITY_SPECTRUM_SECONDS = 120
ACTIVITY_SPECTRUM_BINS = 96
activity_spectrum_rows = deque()
activity_messages_this_second = 0
activity_last_flush = time.time()


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


for _module in (aircraft_api, processor, history_runtime, preview_data, orchestration):
    bind_module(globals(), _module)
