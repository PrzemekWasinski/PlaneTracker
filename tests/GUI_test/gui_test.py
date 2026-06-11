import sys
import os

_PROJECT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
os.chdir(_PROJECT_ROOT)
sys.path.insert(0, _PROJECT_ROOT)

import time
import io
import logging
import pygame
from pygame.locals import *
from time import localtime, strftime
import psutil
import threading
import math
from collections import deque
from datetime import datetime
from pathlib import Path

from modules import draw_text, functions, airport_db
from modules.data_utils import (
    clear_top_graph_history, load_today_heatmap_hits, load_top_graph_history,
    persist_top_graph_sample, prune_history,
)
from modules.ui_utils import (
    draw_altitude_filter, draw_filter_action_buttons, draw_line_graph,
    draw_polar_coverage_plot, draw_radar_heatmap,
    plane_matches_altitude_filter, plane_matches_distance_filter,
)

log = logging.getLogger("gui_test")
logging.basicConfig(level=logging.WARNING)

# Load config
_config = functions.load_config()
_config.setdefault('cameraHost', '192.168.0.157')
_config.setdefault('cameraPort', 12345)
_config.setdefault('adsbHost', '127.0.0.1')
_config.setdefault('adsbPort', 30003)

CAMERA_SERVER = (_config['cameraHost'], int(_config['cameraPort']))
ADSB_SERVER = (_config['adsbHost'], int(_config['adsbPort']))

# Global variables
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
TRACKER_PHOTO_CACHE_LIMIT = 24
TRACKER_PREDICTION_SECONDS = 1.2
TRACKER_MAX_EXTRAPOLATION_SECONDS = 2.0
TRACKER_MAX_SAMPLE_AGE_SECONDS = 5.0

data_lock = threading.Lock()
tracker_request_lock = threading.Lock()

TOP_GRAPH_HISTORY_SECONDS = 24 * 60 * 60
PLANE_GRAPH_HISTORY_SECONDS = 30 * 60
GRAPH_SAMPLE_INTERVAL = 60
PLANE_ALTITUDE_SAMPLE_INTERVAL = 0
PLANE_HIT_SAMPLE_INTERVAL = 60
DIRECTIONAL_HISTORY_SECONDS = 24 * 60 * 60
DIRECTIONAL_SECTOR_COUNT = 8
TOP_GRAPH_HISTORY_DIR = "stats_history"
TRACKER_IMAGE_DIR = Path("images")

active_count_history = deque()
total_seen_history = deque()
directional_hit_history = deque()
heatmap_hits = deque()

ACTIVITY_SPECTRUM_SECONDS = 120
ACTIVITY_SPECTRUM_BINS = 96
activity_spectrum_rows = deque()
activity_messages_this_second = 0
activity_last_flush = time.time()

selected_plane_icao = None
plane_rects = {}
altitude_filter_threshold = 0
altitude_filter_above = True
altitude_filter_dragging = False
distance_filter_threshold_km = 0.0
distance_filter_outside = True
distance_filter_dragging = False
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
auto_track_queue = deque()
auto_track_inside_icaos = set()
AUTO_TRACK_POLYGON_KEYS = (("tlLat", "tlLon"), ("trLat", "trLon"), ("brLat", "brLon"), ("blLat", "blLon"))
AUTO_TRACK_CONFIGURED = all(
    _config.get(lat_key) is not None and _config.get(lon_key) is not None
    for lat_key, lon_key in AUTO_TRACK_POLYGON_KEYS
)

is_animating = False
animation_duration = 0.5
animation_start_time = 0
animation_start_lat = 0
animation_start_lon = 0
animation_target_lat = 0
animation_target_lon = 0

last_scroll_time = 0
scroll_click_delay = 0.2


# Helper functions

def add_message(message):
    body = " ".join(str(message).split())
    lower_body = body.lower()
    is_error = any(token in lower_body for token in ["error", "failed", "timeout", "warning", "invalid"])
    if is_error and len(body) > 50:
        body = body[:47] + "..."

    timestamp = strftime("%H:%M", localtime())
    formatted_message = f"{timestamp} {body}"

    with data_lock:
        message_queue.append(formatted_message)
        if len(message_queue) > 37:
            message_queue.pop(0)


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


def refresh_tracker_photo_surface():
    pass  # no camera in test mode


def begin_camera_tracking(target_icao, logger=None, auto_select=False):
    return False  # no camera in test mode


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


# PYGAME SETUP
pygame.init()

width = _config['screenWidth']
height = _config['screenHeight']
window = pygame.display.set_mode((width, height))

# Fonts
text_font1 = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 16)
text_font2 = pygame.font.Font(os.path.join("textures", "fonts", "DS-DIGI.TTF"), 40)
text_font3 = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 11)
stat_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 13)
graph_time_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 9)
plane_identity_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 12)

# Load images
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

# Radar display settings
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

# Sidebar settings
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

# Fake plane data for GUI preview
_now = time.time()
_base_lat = _config.get('myLat', 51.5)
_base_lon = _config.get('myLon', -0.12)

displayed_planes = {
    "4CA123": {
        "plane_data": {
            "icao": "4CA123",
            "last_lat": _base_lat + 0.25,
            "last_lon": _base_lon + 0.15,
            "altitude": "35000",
            "speed": "450",
            "track": "90",
            "manufacturer": "Boeing",
            "model": "737-800",
            "registration": "G-TEST1",
            "owner": "Test Airlines",
            "prev_lat": _base_lat + 0.24,
            "prev_lon": _base_lon + 0.14,
            "prev_update_time": _now - 5,
            "last_update_time": _now,
            "location_history": {
                f"{_now - 120:.6f}": [_base_lat + 0.15, _base_lon + 0.05],
                f"{_now - 60:.6f}": [_base_lat + 0.20, _base_lon + 0.10],
                f"{_now:.6f}": [_base_lat + 0.25, _base_lon + 0.15],
            },
            "altitude_history": deque([(_now - 120, 33000), (_now - 60, 34000), (_now, 35000)]),
            "hit_history": deque([(int(_now // 60) * 60, 8)]),
            "total_hit_count": 84,
            "last_hit_count": 8,
            "last_hit_bucket": int(_now // 60) * 60,
            "distance": 28.5,
        },
        "display_until": _now + 999999,
    },
    "3C4567": {
        "plane_data": {
            "icao": "3C4567",
            "last_lat": _base_lat - 0.10,
            "last_lon": _base_lon + 0.30,
            "altitude": "12000",
            "speed": "280",
            "track": "180",
            "manufacturer": "Airbus",
            "model": "A320",
            "registration": "D-AIAB",
            "owner": "Mock Air",
            "prev_lat": _base_lat - 0.11,
            "prev_lon": _base_lon + 0.29,
            "prev_update_time": _now - 5,
            "last_update_time": _now,
            "location_history": {},
            "altitude_history": deque([(_now, 12000)]),
            "hit_history": deque([(int(_now // 60) * 60, 3)]),
            "total_hit_count": 22,
            "last_hit_count": 3,
            "last_hit_bucket": int(_now // 60) * 60,
            "distance": 12.3,
        },
        "display_until": _now + 999999,
    },
    "407ABC": {
        "plane_data": {
            "icao": "407ABC",
            "last_lat": _base_lat + 0.05,
            "last_lon": _base_lon - 0.20,
            "altitude": "-",
            "speed": "-",
            "track": "-",
            "manufacturer": "-",
            "model": "-",
            "registration": "-",
            "owner": "-",
            "prev_lat": None,
            "prev_lon": None,
            "prev_update_time": None,
            "last_update_time": _now,
            "location_history": {},
            "altitude_history": deque(),
            "hit_history": deque(),
            "total_hit_count": 5,
            "last_hit_count": 0,
            "last_hit_bucket": None,
            "distance": 8.0,
        },
        "display_until": _now + 999999,
    },
}

for _msg in [
    "12:00 Connected to Antenna at 127.0.0.1:30003",
    "12:01 NEW plane 4CA123",
    "12:01 NEW plane 3C4567",
    "12:02 NEW plane 407ABC",
    "12:05 Stats uploaded: 3 total",
]:
    message_queue.append(_msg)


def main():
    global tracker_running, offline, selected_plane_icao, heatmap_hits
    global is_animating, animation_start_time, animation_start_lat, animation_start_lon
    global animation_target_lat, animation_target_lon, last_scroll_time
    global altitude_filter_threshold, altitude_filter_above, altitude_filter_dragging
    global distance_filter_threshold_km, distance_filter_outside, distance_filter_dragging
    global radar_heatmap_enabled, hide_planes_mode, distance_unit
    global tracker_capture_in_progress, tracker_photo_status, tracker_photo_plane_icao, tracking_mode_auto

    start_time = time.time()
    Path(TOP_GRAPH_HISTORY_DIR).mkdir(exist_ok=True)
    top_graph_last_bucket = load_top_graph_history(active_count_history, total_seen_history, TOP_GRAPH_HISTORY_DIR, TOP_GRAPH_HISTORY_SECONDS, start_time)
    heatmap_hits = deque(load_today_heatmap_hits(TOP_GRAPH_HISTORY_DIR, start_time))
    range_km = 50
    last_local_stats_refresh = 0
    last_health_log = start_time
    cached_flight_stats = functions.get_stats(_config['myLat'], _config['myLon'])
    last_system_stats_refresh = 0
    cpu_temp = 50.0
    ram_percentage = 0
    cpu_percentage = 0
    disk_free = functions.get_disk_free()

    #NEW: Track view center (initially use config location)
    view_center_lat = _config['myLat']
    view_center_lon = _config['myLon']

    run = True
    while run:
        current_time = time.time()
        pic_y = 377
        pic_h = 203
        logs_y = pic_y + pic_h + 10
        logs_h = (height - 50) - logs_y - 10
        filter_panel_rect = pygame.Rect(SIDEBAR_X + (SIDEBAR_WIDTH // 2) + 10, logs_y + 215, int(SIDEBAR_WIDTH / 2 - 20), int(logs_h // 2))
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

        #Log health stats every 30 minutes
        if current_time - last_health_log >= 1800:
            log.info(f"Health check: CPU temp={cpu_temp:.1f}C, RAM={ram_percentage:.1f}%")
            last_health_log = current_time

        #Refresh expensive local stats on a timer instead of every frame
        if current_time - last_system_stats_refresh >= 1:
            try:
                cpu_temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
            except OSError:
                cpu_temp = 50.0
            ram_percentage = psutil.virtual_memory()[2]
            cpu_percentage = psutil.cpu_percent()
            disk_free = functions.get_disk_free()
            last_system_stats_refresh = current_time

        if current_time - last_local_stats_refresh >= 5:
            cached_flight_stats = functions.get_stats(_config['myLat'], _config['myLon'])
            last_local_stats_refresh = current_time

        displayed_planes_snapshot = snapshot_displayed_planes()

        #Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                tracker_running = False
                pygame.quit()
                exit()

            #Mouse wheel zoom
            elif event.type == pygame.MOUSEWHEEL:
                mouse_x, mouse_y = pygame.mouse.get_pos()

                #Only zoom if mouse is over the radar area
                if RADAR_RECT.collidepoint(mouse_x, mouse_y):
                    last_scroll_time = current_time  #Track scroll time to prevent accidental clicks
                    old_range = range_km

                    #Scroll up = zoom in, scroll down = zoom out
                    if event.y > 0:  #Scroll up
                        if range_km > 25:
                            range_km -= 25
                    elif event.y < 0:  #Scroll down
                        if range_km < 1000:
                            range_km += 25

                    #If zoom level changed, keep home-centered behavior when no plane is selected
                    if old_range != range_km and not (selected_plane_icao and selected_plane_icao in displayed_planes_snapshot):
                        target_lat = _config['myLat']
                        target_lon = _config['myLon']

                        #Only animate if we're not already there
                        if abs(view_center_lat - target_lat) > 0.0001 or abs(view_center_lon - target_lon) > 0.0001:
                            is_animating = True
                            animation_start_time = current_time
                            animation_start_lat = view_center_lat
                            animation_start_lon = view_center_lon
                            animation_target_lat = target_lat
                            animation_target_lon = target_lon


            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    altitude_filter_dragging = False
                    distance_filter_dragging = False

            elif event.type == pygame.MOUSEMOTION:
                if altitude_filter_dragging:
                    clamped_y = max(slider_track_rect.top, min(slider_track_rect.bottom, event.pos[1]))
                    altitude_filter_threshold = clamp_altitude_threshold((1.0 - ((clamped_y - slider_track_rect.top) / max(1, slider_track_rect.height))) * 50000)
                if distance_filter_dragging:
                    clamped_y = max(distance_slider_track_rect.top, min(distance_slider_track_rect.bottom, event.pos[1]))
                    distance_filter_threshold_km = clamp_distance_threshold((1.0 - ((clamped_y - distance_slider_track_rect.top) / max(1, distance_slider_track_rect.height))) * 1000.0)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                #Only process left mouse button (button 1), ignore middle/right clicks and scroll buttons
                if event.button != 1:
                    continue

                #Ignore clicks shortly after scrolling to prevent accidental plane selection
                if current_time - last_scroll_time < scroll_click_delay:
                    continue

                last_tap_time = time.time()
                mouse_x, mouse_y = pygame.mouse.get_pos()

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
                    add_message("Filters reset to default")
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
                        if not (selected_plane_icao and selected_plane_icao in displayed_planes_snapshot):
                            target_lat = _config['myLat']
                            target_lon = _config['myLon']

                            if abs(view_center_lat - target_lat) > 0.0001 or abs(view_center_lon - target_lon) > 0.0001:
                                is_animating = True
                                animation_start_time = current_time
                                animation_start_lat = view_center_lat
                                animation_start_lon = view_center_lon
                                animation_target_lat = target_lat
                                animation_target_lon = target_lon

                elif zoom_out_ctrl_rect.collidepoint(mouse_x, mouse_y): #Zoom out
                    if range_km < 1000:
                        range_km += 25
                        if not (selected_plane_icao and selected_plane_icao in displayed_planes_snapshot):
                            target_lat = _config['myLat']
                            target_lon = _config['myLon']

                            if abs(view_center_lat - target_lat) > 0.0001 or abs(view_center_lon - target_lon) > 0.0001:
                                is_animating = True
                                animation_start_time = current_time
                                animation_start_lat = view_center_lat
                                animation_start_lon = view_center_lon
                                animation_target_lat = target_lat
                                animation_target_lon = target_lon

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

        #Handle smooth panning animation
        if is_animating:
            elapsed = current_time - animation_start_time
            progress = min(elapsed / animation_duration, 1.0)

            #Apply easing for smooth deceleration
            eased_progress = 1 - pow(1 - progress, 3)

            #Interpolate between start and target positions
            view_center_lat = animation_start_lat + (animation_target_lat - animation_start_lat) * eased_progress
            view_center_lon = animation_start_lon + (animation_target_lon - animation_start_lon) * eased_progress

            #Stop animation when complete
            if progress >= 1.0:
                is_animating = False
                view_center_lat = animation_target_lat
                view_center_lon = animation_target_lon

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
                prev_lat = plane.get("prev_lat")
                prev_lon = plane.get("prev_lon")
                heading = plane.get("track")
                if heading == "-" or heading is None:
                    heading = 0.0
                else:
                    try:
                        heading = float(heading)
                    except ValueError:
                        heading = 0.0
                if prev_lat is not None and prev_lon is not None:
                    heading = functions.calculate_heading(prev_lat, prev_lon, lat, lon)
                    plane["track"] = heading #Update track with calculated heading

                if tracking_mode_auto and auto_track_rect is not None and auto_track_rect.collidepoint(int(x), int(y)):
                    current_auto_track_icaos.add(icao)

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

                        #Draw lines connecting the trajectory points
                        if len(trajectory_points) > 1:
                            pygame.draw.lines(window, (0, 255, 255), False, trajectory_points)

                            for i in trajectory_points:
                                pygame.draw.circle(window, (255, 255, 0), i, 1)

                base_icon = selected_plane_icon if icao == target_icao else plane_icon
                coloured = base_icon.copy()
                coloured.set_alpha(fade_value)
                rotated_image = pygame.transform.rotate(coloured, heading)
                new_rect = rotated_image.get_rect(center=(x, y))
                window.blit(rotated_image, new_rect)
                current_plane_rects[icao] = new_rect

                #Labels
                label_colour = (0, 255, 255) if icao == target_icao else (0, 255, 0)
                if hide_planes_mode == 0:
                    if not offline and plane.get('manufacturer') != "-":
                        draw_text.fading(window, icao, text_font3, label_colour, x, y - 26, fade_value)
                        draw_text.fading(window, plane.get("owner", "-"), text_font3, label_colour, x, y - 13, fade_value)
                        draw_text.fading(window, f"{plane.get('manufacturer')} {plane.get('model')}", text_font3, label_colour, x, y + 13, fade_value)
                        draw_text.fading(window, f"{plane.get('altitude', '-')}ft", text_font3, label_colour, x, y + 26, fade_value)
                    else:
                        draw_text.fading(window, icao, text_font3, label_colour, x, y - 13, fade_value)
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
                        break
        else:
            auto_track_queue.clear()
            auto_track_inside_icaos.clear()

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
        draw_text.normal(window, "Controller:", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 590)

        draw_text.normal(window, f"TEMP:{round(cpu_temp)}C", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 610)
        draw_text.normal(window, f"RAM:{ram_percentage}%", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 630)
        draw_text.normal(window, f"CPU:{cpu_percentage}%", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 650)
        draw_text.normal(window, f"DISK:{disk_free}GB", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 670)

        with data_lock:
            tracker_stats_snapshot = dict(tracker_device_stats)

        tracker_temp_text = f"TEMP:{round(tracker_stats_snapshot['temp'])}C" if tracker_stats_snapshot['temp'] is not None else "TEMP: N/A"
        tracker_ram_text = f"RAM:{round(tracker_stats_snapshot['ram'])}%" if tracker_stats_snapshot['ram'] is not None else "RAM: N/A"
        tracker_cpu_text = f"CPU:{round(tracker_stats_snapshot['cpu'])}%" if tracker_stats_snapshot['cpu'] is not None else "CPU: N/A"
        tracker_disk_text = f"DISK:{round(tracker_stats_snapshot['disk'], 1)}GB" if tracker_stats_snapshot['disk'] is not None else "DISK: N/A"

        draw_text.normal(window, "Tracker:", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 700)
        draw_text.normal(window, tracker_temp_text, stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 720)
        draw_text.normal(window, tracker_ram_text, stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 740)
        draw_text.normal(window, tracker_cpu_text, stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 760)
        draw_text.normal(window, tracker_disk_text, stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 780)


        api_status_connected = (not offline) and network_available and any(
            display_data.get("plane_data", {}).get('manufacturer', '-') != '-'
            for display_data in displayed_planes_snapshot.values()
        )
        internet_status_connected = network_available

        api_status_colour = (0, 255, 0) if api_status_connected else (255, 0, 0)
        internet_status_colour = (0, 255, 0) if internet_status_connected else (255, 0, 0)
        tracker_status_colour = (0, 255, 0) if tracker_status_connected else (255, 0, 0)

        draw_text.normal(window, "API", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 155, 590)
        pygame.draw.circle(window, api_status_colour, (SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 190, 600), 5)

        draw_text.normal(window, "Internet", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 115, 610)
        pygame.draw.circle(window, internet_status_colour, (SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 190, 620), 5)

        draw_text.normal(window, "Tracker", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 122, 630)
        pygame.draw.circle(window, tracker_status_colour, (SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 190, 640), 5)



        #Separator
        pygame.draw.line(window, (100, 100, 100), (SIDEBAR_X + 5, sys_y - 10), (SIDEBAR_X + SIDEBAR_WIDTH - 10, sys_y - 10), 1)

        active_graph_rect = pygame.Rect(SIDEBAR_X + 300, sys_y, 240, 130)
        total_graph_rect = pygame.Rect(SIDEBAR_X + 580, sys_y, 240, 130)

        stats = cached_flight_stats
        total_seen = stats.get('total', 0)

        if displayed_count > 0 or (current_time - start_time) >= GRAPH_SAMPLE_INTERVAL:
            top_graph_last_bucket = persist_top_graph_sample(active_count_history, total_seen_history, displayed_count, total_seen, TOP_GRAPH_HISTORY_DIR, top_graph_last_bucket, GRAPH_SAMPLE_INTERVAL, TOP_GRAPH_HISTORY_SECONDS, current_time)

        active_peak = max((sample[1] for sample in active_count_history), default=0)
        active_y_max = max(10, ((active_peak + 10 + 9) // 10) * 10)
        draw_line_graph(window, active_graph_rect, list(active_count_history), active_y_max, draw_text, text_font3, pygame, active_peak, current_time, TOP_GRAPH_HISTORY_SECONDS, "ACTIVE")
        total_peak = max((sample[1] for sample in total_seen_history), default=0)
        total_y_max = max(100, ((total_peak + 100 + 99) // 100) * 100)
        draw_line_graph(window, total_graph_rect, list(total_seen_history), total_y_max, draw_text, text_font3, pygame, total_peak, current_time, TOP_GRAPH_HISTORY_SECONDS, "TOTAL")

        #Flight stats
        top_mfg = stats['top_manufacturer']['name'] or 'Unknown'
        top_type = stats['top_model']['name'] or 'Unknown'
        top_airline = stats['top_airline']['name'] or 'Unknown'
        furthest_detected = stats.get('furthest_detected')
        highest_detected = stats.get('highest_detected')
        furthest_text = format_distance(furthest_detected, distance_unit, 1) if furthest_detected is not None else 'Unknown'
        highest_text = f"{highest_detected}ft" if highest_detected is not None else 'Unknown'

        draw_text.normal(window, f"Total Seen: {stats['total']}", text_font3, (255, 255, 255), col1, sys_y)
        draw_text.normal(window, f"Top Mfg: {top_mfg}", text_font3, (255, 255, 255), col1, sys_y + 20)
        draw_text.normal(window, f"Top Type: {top_type}", text_font3, (255, 255, 255), col1, sys_y + 40)
        draw_text.normal(window, f"Top Airline: {top_airline}", text_font3, (255, 255, 255), col1, sys_y + 60)
        draw_text.normal(window, f"Active Count: {displayed_count}", text_font3, (0, 255, 0), col1, sys_y + 80)
        draw_text.normal(window, f"Furthest Detected: {furthest_text}", text_font3, (255, 255, 255), col1, sys_y + 100)
        draw_text.normal(window, f"Highest Detected: {highest_text}", text_font3, (255, 255, 255), col1, sys_y + 120)

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
            model_display = model[:25] if model != '-' else model
            owner_display = owner[:25] if owner != '-' else owner

            reg = p_data.get('registration', '-')
            alt = p_data.get('altitude', '-')
            spd = p_data.get('speed', '-')
            lat = p_data.get('last_lat', '-')
            lon = p_data.get('last_lon', '-')
            total_hits = p_data.get("total_hit_count", 0)



            id_y = separator_y + 10
            if not offline and mfg != "-" and model != "-":
                full_model_display = f"{mfg} {model_display}"[:25]
                draw_text.normal(window, full_model_display, plane_identity_font, (255, 255, 255), col1, id_y)
            else:
                draw_text.normal(window, "Unidentified Aircraft", plane_identity_font, (255, 255, 255), col1, id_y)

            if owner != "-":
                draw_text.normal(window, f"{owner_display}", plane_identity_font, (255, 255, 255), col1, id_y + 20)
            else:
                draw_text.normal(window, f"Unidentified Airline", plane_identity_font, (255, 255, 255), col1, id_y + 20)



            stat_y = id_y + 50
            lx = col1
            rx = col2
            spacing = 18

            def rnd(val, dec=1):
                try: return round(float(val), dec)
                except: return "-"

            #Row 1 ICAO / Reg
            if target_icao != '-':
                draw_text.normal(window, f"HEX: {target_icao}", stat_font, (200, 200, 200), col1, stat_y)
            else:
                draw_text.normal(window, f"HEX: N/A", stat_font, (200, 200, 200), col1, stat_y)

            if reg != '-':
                draw_text.normal(window, f"REG: {reg}", stat_font, (200, 200, 200), rx, stat_y)
            else:
                draw_text.normal(window, f"REG: N/A", stat_font, (200, 200, 200), rx, stat_y)

            #Row 2 Alt / Speed
            if alt != '-':
                draw_text.normal(window, f"ALT: {alt}ft", stat_font, (200, 200, 200), lx, stat_y + spacing)
            else:
                draw_text.normal(window, f"ALT: N/A", stat_font, (200, 200, 200), lx, stat_y + spacing)

            if spd != '-':
                draw_text.normal(window, f"SPD: {spd}kt", stat_font, (200, 200, 200), rx, stat_y + spacing)
            else:
                draw_text.normal(window, f"SPD: N/A", stat_font, (200, 200, 200), rx, stat_y + spacing)

            #Row 3 Lat / Lon (4 decimals)
            if lat != '-':
                draw_text.normal(window, f"LAT: {rnd(lat, 4)}", stat_font, (200, 200, 200), lx, stat_y + spacing*2)
            else:
                draw_text.normal(window, f"LAT: N/A", stat_font, (200, 200, 200), lx, stat_y + spacing*2)

            if lon != '-':
                draw_text.normal(window, f"LON: {rnd(lon, 4)}", stat_font, (200, 200, 200), rx, stat_y + spacing*2)
            else:
                draw_text.normal(window, f"LON: N/A", stat_font, (200, 200, 200), rx, stat_y + spacing*2)

            #Row 4 Hits / Dist
            draw_text.normal(window, f"HITS: {int(total_hits)}", stat_font, (200, 200, 200), lx, stat_y + spacing*3)




            dist_km = p_data.get('distance', '-')
            dist_text = 'Unknown'
            if dist_km != '-':
                converted_distance = convert_distance_from_km(float(dist_km), distance_unit)
                if converted_distance is not None:
                    dist_text = f"{rnd(converted_distance, 2)}{distance_unit.lower()}"
            draw_text.normal(window, f"DST: {dist_text}", stat_font, (200, 200, 200), rx, stat_y + spacing*3)
        else:
            draw_text.center(window, "NO PLANE SELECTED", text_font1, (100, 100, 100), SIDEBAR_X + SIDEBAR_WIDTH // 2, separator_y + 80)

        #Picture Section
        pic_y = 377
        pic_h = 203
        pic_x = SIDEBAR_X + 5
        pic_w = SIDEBAR_WIDTH - 15
        pygame.draw.rect(window, (100, 100, 100), (pic_x, pic_y, pic_w, pic_h), 1)

        #Picture holder
        picture_holder_rect = pygame.Rect(pic_x, pic_y, 271, 203)
        pygame.draw.rect(window, (20, 20, 20), picture_holder_rect, 0)
        pygame.draw.rect(window, (100, 100, 100), picture_holder_rect, 1)

        with data_lock:
            camera_busy = tracker_capture_in_progress
            latest_camera_photo_surface = tracker_photo_surface
            latest_camera_photo_meta = dict(tracker_photo_meta)
            target_camera_photo_surface = tracker_plane_photo_cache.get(target_icao) if target_icao else None
            target_camera_photo_meta = dict(tracker_plane_photo_meta_cache.get(target_icao, {})) if target_icao else {}
            selected_camera_photo_surface = tracker_plane_photo_cache.get(selected_plane_icao) if selected_plane_icao else None
            selected_camera_photo_meta = dict(tracker_plane_photo_meta_cache.get(selected_plane_icao, {})) if selected_plane_icao else {}

        if target_camera_photo_surface is not None:
            camera_photo_surface = target_camera_photo_surface
            camera_photo_meta = target_camera_photo_meta
        elif selected_camera_photo_surface is not None:
            camera_photo_surface = selected_camera_photo_surface
            camera_photo_meta = selected_camera_photo_meta
        elif target_icao or selected_plane_icao:
            camera_photo_surface = None
            camera_photo_meta = {}
        else:
            camera_photo_surface = latest_camera_photo_surface
            camera_photo_meta = latest_camera_photo_meta

        if camera_photo_surface is not None:
            inner_rect = picture_holder_rect.inflate(-6, -6)
            image_width, image_height = camera_photo_surface.get_size()
            if image_width > 0 and image_height > 0:
                scale = min(inner_rect.width / image_width, inner_rect.height / image_height)
                scaled_size = (max(1, int(image_width * scale)), max(1, int(image_height * scale)))
                scaled_surface = pygame.transform.smoothscale(camera_photo_surface, scaled_size)
                scaled_rect = scaled_surface.get_rect(center=picture_holder_rect.center)
                window.blit(scaled_surface, scaled_rect)
        else:
            placeholder_text = 'CAMERA BUSY' if camera_busy else 'NO IMAGE'
            draw_text.center(window, placeholder_text, text_font1, (100, 100, 100), picture_holder_rect.centerx, picture_holder_rect.centery - 8)

        image_prediction_y = 385
        spacing = 18
        meta_label = camera_photo_meta.get('label', 'UNKNOWN')
        meta_confidence = camera_photo_meta.get('confidence', '-')
        meta_raw_score = camera_photo_meta.get('raw_score', '-')
        meta_score_margin = camera_photo_meta.get('score_margin', '-')
        meta_mode = camera_photo_meta.get('mode', '-')
        meta_pan = camera_photo_meta.get('pan', '-')
        meta_tilt = camera_photo_meta.get('tilt', '-')
        meta_bearing = camera_photo_meta.get('bearing_deg', '-')
        meta_elev = camera_photo_meta.get('elev_deg', '-')
        camera_state = 'BUSY' if camera_busy else ('FREE' if tracker_status_connected else 'OFFLINE')
        draw_text.normal(window, f"STATUS: {camera_state}", stat_font, (255, 255, 255), SIDEBAR_X + 285, image_prediction_y)
        draw_text.normal(window, f"LABEL: {meta_label}", stat_font, (255, 255, 255), SIDEBAR_X + 285, image_prediction_y + spacing)
        draw_text.normal(window, f"CONF: {meta_confidence}", stat_font, (255, 255, 255), SIDEBAR_X + 285, image_prediction_y + spacing * 2)
        draw_text.normal(window, f"RAW: {meta_raw_score}", stat_font, (255, 255, 255), SIDEBAR_X + 285, image_prediction_y + spacing * 3)
        draw_text.normal(window, f"MARGIN: {meta_score_margin}", stat_font, (255, 255, 255), SIDEBAR_X + 285, image_prediction_y + spacing * 4)
        draw_text.normal(window, f"MODE: {meta_mode}", stat_font, (255, 255, 255), SIDEBAR_X + 285, image_prediction_y + spacing * 5)
        draw_text.normal(window, f"PAN: {meta_pan}", stat_font, (255, 255, 255), SIDEBAR_X + 285, image_prediction_y + spacing * 6)
        draw_text.normal(window, f"TILT: {meta_tilt}", stat_font, (255, 255, 255), SIDEBAR_X + 285, image_prediction_y + spacing * 7)
        draw_text.normal(window, f"BRG: {meta_bearing}", stat_font, (255, 255, 255), SIDEBAR_X + 285, image_prediction_y + spacing * 8)
        draw_text.normal(window, f"ELEV: {meta_elev}", stat_font, (255, 255, 255), SIDEBAR_X + 285, image_prediction_y + spacing * 9)

        #LOGS BOX
        logs_y = pic_y + pic_h + 10
        logs_h = (height - 50) - logs_y - 10
        pygame.draw.rect(window, (20, 20, 20), (SIDEBAR_X+5, logs_y, (SIDEBAR_WIDTH / 2) - 5, logs_h), 0)
        pygame.draw.rect(window, (100, 100, 100), (SIDEBAR_X+5, logs_y, (SIDEBAR_WIDTH / 2) - 5, logs_h), 1)

        #Polar plot
        polar_plot_rect = pygame.Rect(SIDEBAR_X + (SIDEBAR_WIDTH // 2) + 200, logs_y, 205, 205)
        with data_lock:
            prune_history(directional_hit_history, DIRECTIONAL_HISTORY_SECONDS, current_time)
            directional_plot_history = [(timestamp, counts.copy()) for timestamp, counts in directional_hit_history]

        draw_polar_coverage_plot(
            window, polar_plot_rect, directional_plot_history, draw_text, text_font3, graph_time_font,
            pygame, current_time, DIRECTIONAL_HISTORY_SECONDS, DIRECTIONAL_SECTOR_COUNT
        )
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

        y_msg = logs_y + 10
        with data_lock:
            for message in message_queue[-50:]:
                colour = (200, 200, 200)
                if "WARNING" in message:
                    colour = (255, 0, 0)
                elif "NEW" in message:
                    colour = (0, 255, 0)
                draw_text.normal(window, str(message), text_font3, colour, col1 + 5, y_msg)
                y_msg += 11
                if y_msg > logs_y + logs_h - 10:
                    break

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
