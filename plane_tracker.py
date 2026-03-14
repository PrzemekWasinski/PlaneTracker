import socket
import time
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db
import pygame
from pygame.locals import *
from time import localtime, strftime
import psutil
import os
import threading
import requests
import csv
import math
import fcntl 
from collections import deque

from modules import draw_text, functions, airport_db
from modules.data_utils import append_directional_hit, append_sample, clear_top_graph_history, load_today_heatmap_hits, load_top_graph_history, persist_top_graph_sample, prune_history, save_plane_to_csv
from modules.network_utils import can_retry_plane_api, check_network, fetch_plane_info, upload_to_firebase
from modules.ui_utils import draw_altitude_filter, draw_filter_action_buttons, draw_line_graph, draw_polar_coverage_plot, draw_radar_heatmap, plane_matches_altitude_filter, plane_matches_distance_filter

#Load config
_config = functions.load_config()

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

#Thread lock for shared data
data_lock = threading.Lock()

#Graph history settings
TOP_GRAPH_HISTORY_SECONDS = 24 * 60 * 60
PLANE_GRAPH_HISTORY_SECONDS = 30 * 60
GRAPH_SAMPLE_INTERVAL = 60
PLANE_ALTITUDE_SAMPLE_INTERVAL = 0
PLANE_HIT_SAMPLE_INTERVAL = 60
DIRECTIONAL_HISTORY_SECONDS = 24 * 60 * 60
DIRECTIONAL_SECTOR_COUNT = 8
TOP_GRAPH_HISTORY_DIR = "stats_history"
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
heatmap_on_icon = pygame.image.load(os.path.join("textures", "icons", "heatmap_on.png")).convert_alpha()
heatmap_off_icon = pygame.image.load(os.path.join("textures", "icons", "heatmap_off.png")).convert_alpha()
plane_only_mode_icon = pygame.image.load(os.path.join("textures", "icons", "plane.png")).convert_alpha()
plane_and_text_mode_icon = pygame.image.load(os.path.join("textures", "icons", "plane_and_text.png")).convert_alpha()
hide_plane_mode_icon = pygame.image.load(os.path.join("textures", "icons", "hide_plane.png")).convert_alpha()
clear_filters_icon = pygame.image.load(os.path.join("textures", "icons", "clear_filters.png")).convert_alpha()
plane_icon = pygame.image.load(os.path.join("textures", "icons", "plane_icon.png")).convert_alpha()
selected_plane_icon = pygame.image.load(os.path.join("textures", "icons", "selected_plane.png")).convert_alpha()

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
restart_button_rect = pygame.Rect(toolbar_start_x + (btn_w + btn_gap) * 3, height - 50, btn_w, btn_h)
off_button_rect = pygame.Rect(toolbar_start_x + (btn_w + btn_gap) * 4, height - 50, btn_w, btn_h)
clear_graph_rect = pygame.Rect(toolbar_start_x + (btn_w + btn_gap) * 5, height - 50, btn_w, btn_h)

#Global for plane selection
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

#Animation variables for smooth panning
is_animating = False
animation_duration = 0.5  
animation_start_time = 0
animation_start_lat = 0
animation_start_lon = 0
animation_target_lat = 0
animation_target_lon = 0

#Track last scroll wheel use to prevent accidental clicks
last_scroll_time = 0
scroll_click_delay = 0.2 


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

#Helper thread for API fetches to avoid blocking the radar
def api_worker_thread(icao, plane_data):
    api_data = fetch_plane_info(icao)
    if api_data:
        with data_lock:
            if icao in active_planes:
                active_planes[icao].update(api_data)
            if icao in displayed_planes:
                displayed_planes[icao]["plane_data"].update(api_data)

        #Only save if we got actual plane data (not just an error timestamp)
        if api_data.get("manufacturer") and api_data.get("manufacturer") != "-":
            save_plane_to_csv(icao, active_planes[icao])
            upload_to_firebase(active_planes[icao])


def fetch_tracker_stats(log_result=False):
    global tracker_status_connected, tracker_device_stats
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(('192.168.0.145', 12345))
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

        was_connected = tracker_status_connected
        tracker_status_connected = True
        if log_result and not was_connected:
            add_message('Connected to camera module')
    except Exception as error:
        was_connected = tracker_status_connected
        tracker_status_connected = False
        with data_lock:
            tracker_device_stats = {'temp': None, 'ram': None, 'cpu': None, 'disk': None}
        if log_result or was_connected:
            add_message(f'Camera module unavailable: {error}')


def tracker_stats_thread():
    first_check = True
    while tracker_running:
        fetch_tracker_stats(log_result=first_check)
        first_check = False
        time.sleep(5)


def send_to_tracker(lat, lon, alt_ft, add_message_callback=None):
    global tracker_status_connected
    logger = add_message_callback or add_message
    try:
        alt_m = alt_ft * 0.3048  # convert feet to meters
        logger('Sending position data to camera module')
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('192.168.0.145', 12345))
        message = f"{lat},{lon},{alt_m}"
        sock.send(message.encode())
        response = sock.recv(1024).decode().strip()
        sock.close()
        tracker_status_connected = True
        logger(f"Camera module response: {response or 'no response'}")
    except Exception as error:
        tracker_status_connected = False
        logger(f"Camera module error: {error}")

#THREAD 2: ADSB Data Processing
def adsb_processing_thread():
    global is_receiving, is_processing, tracker_running, offline, network_available
    
    SERVER_SBS = ("localhost", 30003)
    last_stats_upload = time.time()
    last_network_check = time.time()
    
    sock = None
    recv_buffer = ""
    
    while tracker_running:
        current_time = time.time()
        
        #Check network every 30 seconds
        if current_time - last_network_check > 30:
            network_available = check_network()
            if not network_available and not offline:
                add_message("Network down switching to Offline")
            last_network_check = current_time

        #Ensure we have a socket connection
        if sock is None:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect(SERVER_SBS)
                recv_buffer = ""
                add_message("Connected to Antenna")
            except Exception as e:
                add_message(f"Antenna connection error: {e}")
                sock = None
                time.sleep(3)
                continue

        is_receiving = True
        try:
            #Use short read timeout to keep loop responsive
            sock.settimeout(0.5)
            data = sock.recv(4096)
            if not data:
                add_message("Reconnecting with antenna...")
                sock.close()
                sock = None
                recv_buffer = ""
                continue
                
            recv_buffer += data.decode(errors="ignore")
            lines = recv_buffer.split("\n")
            recv_buffer = lines.pop() if lines else ""
            
            for line in lines:
                plane_data = functions.split_message(line)
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
                        if "last_lat" in cached:
                            plane_data["prev_lat"] = cached["last_lat"]
                            plane_data["prev_lon"] = cached["last_lon"]
                        
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
                    add_message(f"NEW plane {icao}")
                
                #If online mode no API data yet and enough time has passed since last error
                if not effective_offline and plane_data["manufacturer"] == "-" and can_retry_plane_api(plane_data, PLANE_API_RETRY_DELAY):
                    threading.Thread(target=api_worker_thread, args=(icao, plane_data), daemon=True).start()

        except socket.timeout:
            pass
        except Exception as e:
            print(f"ADSB loop error: {e}")
            add_message(f"ADSB loop error: {str(e)[:40]}")
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
                sock = None
            recv_buffer = ""
            time.sleep(1)

        #Periodically clean old planes and upload stats
        current_time = time.time()
        with data_lock:
            old_planes = [icao for icao, d in displayed_planes.items() if d["display_until"] < current_time]
            for icao in old_planes:
                del displayed_planes[icao]

        if current_time - last_stats_upload > 60 and not offline and network_available:
            try:
                cpu_temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
                ram_percentage = psutil.virtual_memory()[2]
                
                #Upload flight stats with improved error handling
                today = datetime.today().strftime("%Y-%m-%d")
                stats_ref = db.reference(f"{today}/stats")
                
                new_stats = functions.get_stats()
                
                #More detailed validation and logging
                if new_stats is None:
                    print(f"Stats validation: get_stats() returned None")
                    add_message("Stats: get_stats() returned None")
                elif not isinstance(new_stats, dict):
                    print(f"Stats validation: get_stats() returned non-dict: {type(new_stats)}")
                    add_message(f"Stats: invalid type {type(new_stats)}")
                else:
                    #Check if stats has required fields
                    total = new_stats.get('total')
                    if total is None:
                        print(f"Stats validation: 'total' field missing from stats: {new_stats}")
                        add_message("Stats: missing 'total' field")
                    elif not isinstance(total, (int, float)):
                        print(f"Stats validation: 'total' is not numeric: {total} (type: {type(total)})")
                        add_message(f"Stats: total not numeric")
                    elif total == 0:
                        print(f"Stats validation: total is 0 - likely read error")
                        add_message("Stats: total is 0 (skipping)")
                    else:
                        #Stats look valid proceed with upload
                        current_stats = stats_ref.get()
                        
                        #Upload if no existing stats or new total is higher/equal
                        if current_stats is None:
                            stats_ref.set(new_stats)
                            add_message(f"Stats uploaded: {total} total")
                        elif new_stats.get('total', 0) >= current_stats.get('total', 0):
                            stats_ref.set(new_stats)
                            add_message(f"Stats updated: {total} total")
                        else:
                            print(f"Stats validation: Skipping - new ({total}) < current ({current_stats.get('total')})")
                            add_message(f"Stats: skip (new < current)")
                
                #Upload device stats
                device_stats_ref = db.reference("device_stats")
                device_stats_ref.update({
                    "cpu_temp": cpu_temp,
                    "ram_percentage": ram_percentage,
                    "run": True
                })
                
                last_stats_upload = current_time
            except Exception as e:
                print(f"Stats upload error: {e}")
                add_message(f"Stats upload error: {str(e)[:30]}")

        is_receiving = False

    if sock:
        sock.close()

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


#Start ADSB processing thread
processing_thread = threading.Thread(target=adsb_processing_thread, daemon=True)
processing_thread.start()

tracker_stats_worker = threading.Thread(target=tracker_stats_thread, daemon=True)
tracker_stats_worker.start()

#THREAD 1: Main UI Thread
def main():
    global tracker_running, offline, selected_plane_icao, heatmap_hits
    global is_animating, animation_start_time, animation_start_lat, animation_start_lon
    global animation_target_lat, animation_target_lon, last_scroll_time
    global altitude_filter_threshold, altitude_filter_above, altitude_filter_dragging
    global distance_filter_threshold_km, distance_filter_outside, distance_filter_dragging
    global radar_heatmap_enabled, hide_planes_mode, distance_unit
    
    start_time = time.time()
    top_graph_last_bucket = load_top_graph_history(active_count_history, total_seen_history, TOP_GRAPH_HISTORY_DIR, TOP_GRAPH_HISTORY_SECONDS, start_time)
    heatmap_hits = deque(load_today_heatmap_hits(TOP_GRAPH_HISTORY_DIR, start_time))
    range_km = 50
    last_local_stats_refresh = 0
    cached_flight_stats = functions.get_stats(_config['myLat'], _config['myLon'])
    last_system_stats_refresh = 0
    cpu_temp = 0
    ram_percentage = 0
    cpu_percentage = 0
    disk_free = functions.get_disk_free()
    
    #NEW: Track view center (initially use config location)
    view_center_lat = _config['myLat']
    view_center_lon = _config['myLon']
    
    while True:
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
        
        #Restart every 30 minutes
        if current_time - start_time > 1800:
            print("Restarting...")
            functions.restart_script()
        
        #Refresh expensive local stats on a timer instead of every frame
        if current_time - last_system_stats_refresh >= 1:
            cpu_temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
            ram_percentage = psutil.virtual_memory()[2]
            cpu_percentage = psutil.cpu_percent()
            disk_free = functions.get_disk_free()
            last_system_stats_refresh = current_time

        if current_time - last_local_stats_refresh >= 5:
            cached_flight_stats = functions.get_stats(_config['myLat'], _config['myLon'])
            last_local_stats_refresh = current_time
        
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
                    if old_range != range_km and not (selected_plane_icao and selected_plane_icao in displayed_planes):
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
                    target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes) else None
                    if not target_icao:
                        min_track_dist = float("inf")
                        with data_lock:
                            for icao, display_data in displayed_planes.items():
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
                    if target_icao and target_icao in displayed_planes:
                        plane_data = displayed_planes[target_icao]["plane_data"]
                        alt_ft = plane_data.get("altitude", "-")
                        if alt_ft != '-':
                            threading.Thread(target=send_to_tracker, args=(plane_data['last_lat'], plane_data['last_lon'], float(alt_ft), add_message), daemon=True).start()
                            add_message(f"Aiming camera at {target_icao}")
                        else:
                            add_message("Target plane altitude unknown, cannot track")
                    else:
                        add_message("No target plane available for tracking")
                    continue
                
                elif zoom_in_ctrl_rect.collidepoint(mouse_x, mouse_y):
                    if range_km > 25:
                        range_km -= 25
                        if not (selected_plane_icao and selected_plane_icao in displayed_planes):
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
                        if not (selected_plane_icao and selected_plane_icao in displayed_planes):
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
        with data_lock:
            for icao, display_data in displayed_planes.items():
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
        target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes) else closest_plane

        with data_lock:
            for icao in list(displayed_planes.keys()):
                display_data = displayed_planes[icao]
                plane = display_data["plane_data"]
                if not plane_matches_altitude_filter(plane, altitude_filter_threshold, altitude_filter_above):
                    continue
                if not plane_matches_distance_filter(plane, distance_filter_threshold_km, distance_filter_outside):
                    continue
                lat = plane.get("last_lat")
                lon = plane.get("last_lon")
                if lat is None or lon is None: continue

                #Calculate fade
                time_remaining = display_data["display_until"] - current_time
                if time_remaining <= 0: continue
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
                    print(f"Draw error for {icao}: {e}")
                    print(x, y)
        
        with data_lock:
            plane_rects = current_plane_rects
        
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

        tracker_temp_text = f"TEMP:{round(tracker_stats_snapshot['temp'])}C" if tracker_stats_snapshot['temp'] is not None else "TEMP: --"
        tracker_ram_text = f"RAM:{round(tracker_stats_snapshot['ram'])}%" if tracker_stats_snapshot['ram'] is not None else "RAM: --"
        tracker_cpu_text = f"CPU:{round(tracker_stats_snapshot['cpu'])}%" if tracker_stats_snapshot['cpu'] is not None else "CPU: --"
        tracker_disk_text = f"DISK:{round(tracker_stats_snapshot['disk'], 1)}GB" if tracker_stats_snapshot['disk'] is not None else "DISK: --"

        draw_text.normal(window, "Tracker:", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 700)
        draw_text.normal(window, tracker_temp_text, stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 720)
        draw_text.normal(window, tracker_ram_text, stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 740)
        draw_text.normal(window, tracker_cpu_text, stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 760)
        draw_text.normal(window, tracker_disk_text, stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 10, 780)


        with data_lock:
            api_status_connected = (not offline) and network_available and any(
                plane_data.get('manufacturer', '-') != '-'
                for plane_data in active_planes.values()
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
        pygame.draw.rect(window, (255, 255, 255), track_plane_button_rect, 0)
        pygame.draw.rect(window, (100, 100, 100), track_plane_button_rect, 1)
        scaled_track_target_icon = pygame.transform.smoothscale(track_target_icon, (32, 32))
        window.blit(scaled_track_target_icon, scaled_track_target_icon.get_rect(center=track_plane_button_rect.center))

        #Plane Info
        target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes) else closest_plane
        p_data = displayed_planes.get(target_icao, {}).get("plane_data") if target_icao else None
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

        #Picture Placeholder
        pic_y = 377
        pic_h = 203
        pic_x = SIDEBAR_X + 5
        pic_w = SIDEBAR_WIDTH - 15
        pygame.draw.rect(window, (100, 100, 100), (pic_x, pic_y, pic_w, pic_h), 1)

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
        draw_polar_coverage_plot(window, polar_plot_rect, directional_plot_history, draw_text, text_font3, graph_time_font, pygame, current_time, DIRECTIONAL_HISTORY_SECONDS, DIRECTIONAL_SECTOR_COUNT)
        #FILTERS
        draw_altitude_filter(window, filter_panel_rect, filter_checkbox_rect, slider_track_rect, filter_slider_handle_rect, altitude_slider_up_rect, altitude_slider_down_rect, altitude_filter_threshold, altitude_filter_above, distance_filter_checkbox_rect, distance_slider_track_rect, distance_filter_slider_handle_rect, distance_slider_up_rect, distance_slider_down_rect, distance_filter_threshold_km, distance_filter_outside, distance_unit, distance_unit_rects, draw_text, stat_font, graph_time_font, text_font3, pygame)
        filter_button_icons = {
            'heatmap_on': heatmap_on_icon,
            'heatmap_off': heatmap_off_icon,
            'plane_and_text': plane_and_text_mode_icon,
            'plane_only': plane_only_mode_icon,
            'hide_plane': hide_plane_mode_icon,
            'clear_filters': clear_filters_icon,
        }
        draw_filter_action_buttons(window, heatmap_button_rect, hide_planes_button_rect, reset_filters_button_rect, radar_heatmap_enabled, hide_planes_mode, filter_button_icons, pygame)
        
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

