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
TOP_GRAPH_HISTORY_DIR = "stats_history"

#Rolling graph data
active_count_history = deque()
total_seen_history = deque()

#Activity spectrogram state
ACTIVITY_SPECTRUM_SECONDS = 120
ACTIVITY_SPECTRUM_BINS = 96
activity_spectrum_rows = deque()
activity_messages_this_second = 0
activity_last_flush = time.time()

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

def get_top_graph_history_path(now=None):
    now = datetime.fromtimestamp(now or time.time())
    return os.path.join(TOP_GRAPH_HISTORY_DIR, f"graph_history_{now.strftime('%Y-%m-%d')}.csv")


def load_top_graph_history(now=None):
    global top_graph_last_bucket

    now = now or time.time()
    cutoff = now - TOP_GRAPH_HISTORY_SECONDS
    history_path = get_top_graph_history_path(now)
    active_count_history.clear()
    total_seen_history.clear()
    top_graph_last_bucket = None

    if not os.path.exists(history_path):
        return

    try:
        with open(history_path, 'r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                try:
                    bucket_time = datetime.strptime(row['timestamp'], "%Y-%m-%d %H:%M:%S").timestamp()
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

    prune_history(active_count_history, TOP_GRAPH_HISTORY_SECONDS, now)
    prune_history(total_seen_history, TOP_GRAPH_HISTORY_SECONDS, now)


def persist_top_graph_sample(active_count, total_seen, now=None):
    global top_graph_last_bucket

    now = now or time.time()
    bucket_time = int(now // GRAPH_SAMPLE_INTERVAL) * GRAPH_SAMPLE_INTERVAL
    history_path = get_top_graph_history_path(now)

    append_sample(active_count_history, active_count, GRAPH_SAMPLE_INTERVAL, now)
    prune_history(active_count_history, TOP_GRAPH_HISTORY_SECONDS, now)
    append_sample(total_seen_history, total_seen, GRAPH_SAMPLE_INTERVAL, now)
    prune_history(total_seen_history, TOP_GRAPH_HISTORY_SECONDS, now)

    if top_graph_last_bucket == bucket_time:
        return

    try:
        os.makedirs(TOP_GRAPH_HISTORY_DIR, exist_ok=True)
        file_exists = os.path.exists(history_path)

        with open(history_path, 'a', newline='', encoding='utf-8') as file:
            fieldnames = ['timestamp', 'active_count', 'total_seen']
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                'timestamp': datetime.fromtimestamp(bucket_time).strftime("%Y-%m-%d %H:%M:%S"),
                'active_count': int(active_count),
                'total_seen': int(total_seen)
            })
    except (PermissionError, OSError, csv.Error):
        return

    top_graph_last_bucket = bucket_time

def plane_matches_altitude_filter(plane_data):
    altitude_value = plane_data.get("altitude")
    try:
        altitude_value = float(altitude_value)
    except (TypeError, ValueError):
        return False

    if altitude_filter_above:
        return altitude_value >= altitude_filter_threshold
    return altitude_value <= altitude_filter_threshold


def draw_altitude_filter(surface, panel_rect, checkbox_rect, slider_track_rect, slider_handle_rect):
    pygame.draw.rect(surface, (100, 100, 100), panel_rect, 1)

    pygame.draw.rect(surface, (20, 20, 20), checkbox_rect, 0)
    pygame.draw.rect(surface, (160, 160, 160), checkbox_rect, 1)
    if altitude_filter_above:
        pygame.draw.line(surface, (0, 255, 0), (checkbox_rect.left + 3, checkbox_rect.centery), (checkbox_rect.centerx, checkbox_rect.bottom - 4), 2)
        pygame.draw.line(surface, (0, 255, 0), (checkbox_rect.centerx, checkbox_rect.bottom - 4), (checkbox_rect.right - 3, checkbox_rect.top + 3), 2)

    mode_text = "ABOVE" if altitude_filter_above else "BELOW"
    draw_text.normal(surface, mode_text, text_font3, (255, 255, 255), checkbox_rect.right + 8, checkbox_rect.top - 1)
    draw_text.normal(surface, f"{int(altitude_filter_threshold)} FT", stat_font, (255, 255, 255), panel_rect.left + 8, checkbox_rect.bottom + 4)

    pygame.draw.rect(surface, (35, 35, 35), slider_track_rect, 0)
    pygame.draw.rect(surface, (100, 100, 100), slider_track_rect, 1)
    pygame.draw.line(surface, (0, 255, 255), (slider_track_rect.centerx, slider_track_rect.top + 4), (slider_track_rect.centerx, slider_track_rect.bottom - 4), 3)

    for alt_mark in [0, 10000, 20000, 30000, 40000, 50000]:
        tick_ratio = 1.0 - (alt_mark / 50000.0)
        tick_y = slider_track_rect.top + int(tick_ratio * slider_track_rect.height)
        pygame.draw.line(surface, (120, 120, 120), (slider_track_rect.left, tick_y), (slider_track_rect.left + 8, tick_y), 1)
        draw_text.normal(surface, f"{alt_mark // 1000}", graph_time_font, (180, 180, 180), slider_track_rect.right + 6, tick_y - 4)

    pygame.draw.rect(surface, (255, 255, 0), slider_handle_rect, 0)
    pygame.draw.rect(surface, (255, 255, 255), slider_handle_rect, 1)

def draw_line_graph(surface, rect, samples, y_max, now=None, time_window_seconds=PLANE_GRAPH_HISTORY_SECONDS, title=None, border_color=(100, 100, 100)):
    pygame.draw.rect(surface, border_color, rect, 1)

    inner_rect = rect.inflate(-12, -12)
    if inner_rect.width <= 1 or inner_rect.height <= 1:
        return

    plot_rect = inner_rect
    pygame.draw.rect(surface, (15, 15, 15), inner_rect)

    y_min = 0
    y_max = max(1, int(y_max))
    now = now or time.time()

    if samples:
        first_visible_time = samples[0][0]
        min_time = max(first_visible_time, now - time_window_seconds)
    else:
        min_time = now - time_window_seconds
    max_time = max(now, min_time + 1)

    old_clip = surface.get_clip()
    surface.set_clip(plot_rect)
    pygame.draw.line(surface, (45, 45, 45), (plot_rect.left, plot_rect.bottom - 1), (plot_rect.right - 1, plot_rect.bottom - 1), 1)

    if samples:
        points = []
        for timestamp, value in samples:
            if timestamp < min_time or timestamp > max_time:
                continue
            x_ratio = (timestamp - min_time) / max(1, (max_time - min_time))
            clamped_value = max(y_min, min(y_max, value))
            y_ratio = (clamped_value - y_min) / max(1, (y_max - y_min))
            x = plot_rect.left + int(x_ratio * (plot_rect.width - 1))
            y = plot_rect.bottom - 1 - int(y_ratio * (plot_rect.height - 1))
            x = max(plot_rect.left, min(plot_rect.right - 1, x))
            y = max(plot_rect.top, min(plot_rect.bottom - 1, y))
            points.append((x, y))

        if len(points) >= 2:
            pygame.draw.lines(surface, (0, 255, 255), False, points, 2)
        for point in points:
            pygame.draw.circle(surface, (255, 255, 0), point, 2)

    surface.set_clip(old_clip)

    y_max_img = text_font3.render(str(y_max), True, (255, 255, 255))
    y_max_rect = y_max_img.get_rect(topleft=(rect.left + 6, rect.top + 3))
    surface.blit(y_max_img, y_max_rect)

    if title:
        title_img = text_font3.render(title, True, (255, 255, 255))
        title_rect = title_img.get_rect(topright=(rect.right - 6, rect.top + 3))
        surface.blit(title_img, title_rect)
    draw_text.normal(surface, "0", text_font3, (255, 255, 255), rect.left + 4, rect.bottom - 14)

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
image1 = pygame.image.load(os.path.join("textures", "icons", "open_menu.png"))
image2 = pygame.image.load(os.path.join("textures", "icons", "close_menu.png"))
image3 = pygame.image.load(os.path.join("textures", "icons", "zoom_in.png"))
image4 = pygame.image.load(os.path.join("textures", "icons", "zoom_out.png"))
image5 = pygame.image.load(os.path.join("textures", "icons", "online.png"))
image6 = pygame.image.load(os.path.join("textures", "icons", "offline.png"))
image7 = pygame.image.load(os.path.join("textures", "icons", "off.png"))
plane_icon = pygame.image.load(os.path.join("textures", "icons", "plane.png")).convert_alpha()

#Radar display settings
RADAR_RECT = pygame.Rect(0, 0, 1080, 1080)
RADAR_CENTER_X = RADAR_RECT.centerx
RADAR_CENTER_Y = RADAR_RECT.centery
RADAR_RADIUS = 540

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
future_button_rect = pygame.Rect(toolbar_start_x + (btn_w + btn_gap) * 3, height - 50, btn_w, btn_h)
off_button_rect = pygame.Rect(toolbar_start_x + (btn_w + btn_gap) * 4, height - 50, btn_w, btn_h)

#Global for plane selection
selected_plane_icao = None
plane_rects = {} 
altitude_filter_threshold = 0
altitude_filter_above = True
altitude_filter_dragging = False

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

#Map images
map_images = {}
for km in [25, 50, 75, 100, 125, 150, 175, 200, 225, 250]:
    map_images[km] = pygame.image.load(os.path.join("textures", "images", f"{km}.png"))

def add_message(message):
    with data_lock:
        message_queue.append(message)
        if len(message_queue) > 24:
            message_queue.pop(0)

def check_network():
    try:
        requests.get("https://hexdb.io", timeout=2)
        return True
    except:
        return False

def can_retry_plane_api(plane_data):
    last_error = plane_data.get("last_api_error", 0)
    if last_error == 0:
        return True  #Never tried or succeeded
    return (time.time() - last_error) >= PLANE_API_RETRY_DELAY

def fetch_plane_info(icao):
    try:
        url = f"https://hexdb.io/api/v1/aircraft/{icao}"
        response = requests.get(url, timeout=5) 
        
        if response.status_code == 200:
            api_data = response.json()
            
            manufacturer = functions.clean_string(str(api_data.get("Manufacturer", "-")))
            if manufacturer == "Avions de Transport Regional":
                manufacturer = "ATR"
            elif manufacturer == "Honda Aircraft Company":
                manufacturer = "Honda"
            
            return {
                "manufacturer": manufacturer,
                "registration": functions.clean_string(str(api_data.get("Registration", "-"))),
                "owner": functions.clean_string(str(api_data.get("RegisteredOwners", "-"))),
                "model": functions.clean_string(str(api_data.get("Type", "-"))),
                "last_api_error": 0 #Clear error timestamp on success
            }
            
        elif response.status_code == 404:
            #Plane not found 
            return None
            
        elif response.status_code == 429:
            #Rate limited 
            print(f"Rate limited for {icao}")
            return {"last_api_error": time.time()}
            
        elif response.status_code >= 500:
            #Server error 
            print(f"Server error {response.status_code} for {icao}")
            backup_result = try_backup_api(icao)
            if backup_result:
                return backup_result
            return {"last_api_error": time.time()}
        else:
            return try_backup_api(icao)

    except requests.exceptions.Timeout:
        print(f"API timeout for {icao}")
        return {"last_api_error": time.time()}
        
    except requests.exceptions.ConnectionError:
        print(f"API connection error for {icao}")
        return {"last_api_error": time.time()}
        
    except Exception as e:
        print(f"API error for {icao}: {e}")
        return {"last_api_error": time.time()}
    
    return None

def try_backup_api(icao):
    try:
        url = f"https://opensky-network.org/api/metadata/aircraft/icao/{icao}"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            api_data = response.json()

            output = {
                "manufacturer": api_data.get("model", "-").split(" ", 1)[0],
                "registration": api_data.get("registration", "-"),
                "owner": api_data.get("operator", "-"),
                "model": api_data.get("model", "-").split(" ", 1)[1] if " " in api_data.get("model", "") else "-",
                "last_api_error": 0  
            }

            if output.get("manufacturer") == '' or output.get("registration") == '' or output.get("owner") == '' or output.get("model") == '':
                return None

            return output
            
        elif response.status_code == 404:
            #Plane not found in backup 
            return None
            
        elif response.status_code >= 500:
            print(f"Backup server error {response.status_code}")
            return {"last_api_error": time.time()}
            
    except Exception as e:
        print(f"Backup API error: {e}")
        pass
    
    return None

def save_plane_to_csv(icao, plane_data):
    try:
        #Check if we have complete API data
        manufacturer = plane_data.get('manufacturer', '-')
        model = plane_data.get('model', '-')
        owner = plane_data.get('owner', '-')
        registration = plane_data.get('registration', '-')
        
        if manufacturer == "-" or model == "-" or owner == "-" or registration == "-":
            return  #Dont save incomplete data
        
        today = datetime.today().strftime("%Y-%m-%d")
        stats_dir = './stats_history'
        csv_path = os.path.join(stats_dir, f'{today}.csv')
        os.makedirs(stats_dir, exist_ok=True)
        
        #Use file locking to prevent concurrent access issues
        lock_path = csv_path + '.lock'
        with open(lock_path, 'w') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            
            try:
                #Read existing data
                existing_planes = {}
                if os.path.exists(csv_path):
                    with open(csv_path, 'r', newline='', encoding='utf-8') as file:
                        reader = csv.DictReader(file)
                        for row in reader:
                            if row.get('icao'):
                                existing_planes[row['icao']] = row
                
                #Update plane data
                full_model = f"{manufacturer} {model}".strip()
                
                #Build location history
                location_history = {}
                if icao in existing_planes:
                    existing_history = existing_planes[icao].get('location_history', '{}')
                    if existing_history and existing_history != '{}':
                        try:
                            import ast
                            location_history = ast.literal_eval(existing_history)
                        except:
                            pass
                
                if plane_data["lat"] != "-" and plane_data["lon"] != "-":
                    location_history[plane_data["spotted_at"]] = [plane_data["lat"], plane_data["lon"]]
                
                #Create row
                row_data = {
                    "icao": icao,
                    "manufacturer": manufacturer,
                    "model": model,
                    "full_model": full_model,
                    "airline": owner.strip(),
                    "location_history": str(location_history),
                    "altitude": plane_data.get("altitude"),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
                existing_planes[icao] = row_data
                
                #Write all data back atomically
                temp_path = csv_path + '.tmp'
                with open(temp_path, 'w', newline='', encoding='utf-8') as file:
                    fieldnames = ["icao", "manufacturer", "model", "full_model", "airline", "location_history", "altitude", "timestamp"]
                    writer = csv.DictWriter(file, fieldnames=fieldnames)
                    writer.writeheader()
                    for plane in existing_planes.values():
                        writer.writerow(plane)
                
                #Atomic replace
                os.replace(temp_path, csv_path)
                
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                
    except Exception as e:
        print(f"CSV error: {e}")
        #Clean up temp file if it exists
        temp_path = csv_path + '.tmp' if 'csv_path' in locals() else None
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

def upload_to_firebase(plane_data):
    try:
        manufacturer = plane_data.get("manufacturer", "-")
        model = plane_data.get("model", "-")
        registration = plane_data.get("registration", "-")
        owner = plane_data.get("owner", "-")
        
        #Only upload if we have complete API data
        if manufacturer == "-" or model == "-" or registration == "-" or owner == "-":
            return  #Dont upload incomplete data
        
        #Create firebase data
        firebase_data = {}
        for key in plane_data:
            if key not in ["location_history", "last_update_time", "last_lat", "last_lon", "last_api_error"]:
                firebase_data[key] = plane_data[key]
        
        #Get time path
        min_str = strftime("%M", localtime())
        hour = strftime("%H", localtime())
        time_10 = f"{hour}:{min_str[:-1]}0"
        today = datetime.today().strftime("%Y-%m-%d")
        
        path = f"{today}/{time_10}/{manufacturer}-{model}-({registration})-{owner}"
        ref = db.reference(path)
        
        #Check if exists
        current_data = ref.get()
        if current_data is None:
            ref.set(firebase_data)
        else:
            #Update only nonempty fields
            new_data = {}
            for key in firebase_data:
                value = firebase_data[key]
                if value != "-" and value != []:
                    new_data[key] = value
                else:
                    if key in current_data:
                        new_data[key] = current_data[key]
            ref.update(new_data)
            
    except Exception as e:
        print(f"Firebase error: {e}")

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

def send_to_tracker(lat, lon, alt_ft):
    try:
        alt_m = alt_ft * 0.3048  # convert feet to meters
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('192.168.0.145', 12345))
        message = f"{lat},{lon},{alt_m}"
        sock.send(message.encode())
        response = sock.recv(1024).decode()
        sock.close()
        if response == "success":
            add_message("Tracker pointed successfully")
        elif response == "busy":
            add_message("Tracker is busy")
        else:
            add_message("Tracker error")
    except Exception as e:
        add_message(f"Tracker connection error: {e}")

#THREAD 2: ADSB Data Processing
def adsb_processing_thread():
    global is_receiving, is_processing, tracker_running, offline, network_available
    
    SERVER_SBS = ("localhost", 30003)
    last_stats_upload = time.time()
    last_network_check = time.time()
    
    sock = None
    
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
                continue
                
            buffer = data.decode(errors="ignore")
            lines = buffer.split("\n")
            
            for line in lines:
                plane_data = functions.split_message(line)
                if not plane_data or plane_data["lon"] == "-" or plane_data["lat"] == "-":
                    continue

                icao = plane_data['icao']
                effective_offline = offline or not network_available

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
                        plane_data["last_hit_count"] = cached.get("last_hit_count", 0)
                    else:
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
                    
                    plane_data["last_lat"] = float(plane_data["lat"])
                    plane_data["last_lon"] = float(plane_data["lon"])
                    plane_data["last_update_time"] = time.time()
                    current_timestamp = plane_data.get("spotted_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    current_epoch = time.time()
                    
                    #Build location_history for ALL planes (not just ones with API data)
                    if plane_data["lat"] != "-" and plane_data["lon"] != "-":
                        plane_data["location_history"][current_timestamp] = [float(plane_data["lat"]), float(plane_data["lon"])]

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
                        plane_data["hit_history"].append((hit_bucket, 1))
                    prune_history(plane_data["hit_history"], PLANE_GRAPH_HISTORY_SECONDS, current_epoch)
                    
                    active_planes[icao] = plane_data
                    displayed_planes[icao] = {
                        "plane_data": plane_data,
                        "display_until": time.time() + display_duration
                    }
                
                #If online mode no API data yet and enough time has passed since last error
                if not effective_offline and plane_data["manufacturer"] == "-" and can_retry_plane_api(plane_data):
                    threading.Thread(target=api_worker_thread, args=(icao, plane_data), daemon=True).start()

        except socket.timeout:
            pass
        except Exception as e:
            print(f"ADSB loop error: {e}")
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

#Start ADSB processing thread
processing_thread = threading.Thread(target=adsb_processing_thread, daemon=True)
processing_thread.start()

#THREAD 1: Main UI Thread
def main():
    global tracker_running, offline, selected_plane_icao
    global is_animating, animation_start_time, animation_start_lat, animation_start_lon
    global animation_target_lat, animation_target_lon, last_scroll_time
    global altitude_filter_threshold, altitude_filter_above, altitude_filter_dragging
    
    start_time = time.time()
    load_top_graph_history(start_time)
    range_km = 50
    map_enabled = False
    
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
        filter_checkbox_rect = pygame.Rect(filter_panel_rect.left + 8, filter_panel_rect.top + 10, 14, 14)
        slider_track_rect = pygame.Rect(filter_panel_rect.left + 28, filter_panel_rect.top + 48, 18, max(80, filter_panel_rect.height - 66))
        track_plane_button_rect = pygame.Rect(SIDEBAR_X + 250, ((315 // 2) + 68) + 10, 40, 40)
        slider_ratio = 1.0 - (altitude_filter_threshold / 50000.0)
        slider_handle_y = slider_track_rect.top + int(slider_ratio * slider_track_rect.height) - 5
        slider_handle_y = max(slider_track_rect.top - 5, min(slider_track_rect.bottom - 5, slider_handle_y))
        filter_slider_handle_rect = pygame.Rect(slider_track_rect.left - 6, slider_handle_y, slider_track_rect.width + 12, 10)
        
        #Restart every 30 minutes
        if current_time - start_time > 1800:
            print("Restarting...")
            functions.restart_script()
        
        #Get CPU and RAM stats
        cpu_temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
        ram_percentage = psutil.virtual_memory()[2]
        
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
                        if range_km < 250:
                            range_km += 25
                    
                    #If zoom level changed, log it
                    if old_range != range_km:
                        if selected_plane_icao and selected_plane_icao in displayed_planes:
                            #Don't animate - the continuous tracking will keep the plane centered
                            add_message(f"Zoomed to {range_km}km on selected plane")
                        else:
                            #No plane selected - animate to home if not already there
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
                            
                            add_message(f"Zoomed to {range_km}km on home")
                
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    altitude_filter_dragging = False

            elif event.type == pygame.MOUSEMOTION:
                if altitude_filter_dragging:
                    clamped_y = max(slider_track_rect.top, min(slider_track_rect.bottom, event.pos[1]))
                    altitude_filter_threshold = int(round((1.0 - ((clamped_y - slider_track_rect.top) / max(1, slider_track_rect.height))) * 50000))
                    altitude_filter_threshold = max(0, min(50000, altitude_filter_threshold))

            elif event.type == pygame.MOUSEBUTTONDOWN:
                #Only process left mouse button (button 1), ignore middle/right clicks and scroll buttons
                if event.button != 1:
                    continue
                
                #Ignore clicks shortly after scrolling to prevent accidental plane selection
                if current_time - last_scroll_time < scroll_click_delay:
                    continue
                    
                last_tap_time = time.time()
                mouse_x, mouse_y = pygame.mouse.get_pos()
                
                if filter_checkbox_rect.collidepoint(mouse_x, mouse_y):
                    altitude_filter_above = not altitude_filter_above
                    continue

                if slider_track_rect.collidepoint(mouse_x, mouse_y) or filter_slider_handle_rect.collidepoint(mouse_x, mouse_y):
                    altitude_filter_dragging = True
                    clamped_y = max(slider_track_rect.top, min(slider_track_rect.bottom, mouse_y))
                    altitude_filter_threshold = int(round((1.0 - ((clamped_y - slider_track_rect.top) / max(1, slider_track_rect.height))) * 50000))
                    altitude_filter_threshold = max(0, min(50000, altitude_filter_threshold))
                    continue

                if track_plane_button_rect.collidepoint(mouse_x, mouse_y):
                    target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes) else None
                    if not target_icao:
                        min_track_dist = float("inf")
                        with data_lock:
                            for icao, display_data in displayed_planes.items():
                                plane = display_data.get("plane_data", {})
                                if not plane_matches_altitude_filter(plane):
                                    continue
                                lat = plane.get("last_lat")
                                lon = plane.get("last_lon")
                                if lat is None or lon is None:
                                    continue
                                dist = functions.calculate_distance(view_center_lat, view_center_lon, float(lat), float(lon))
                                if dist < min_track_dist:
                                    min_track_dist = dist
                                    target_icao = icao
                    if target_icao and target_icao in displayed_planes:
                        plane_data = displayed_planes[target_icao]["plane_data"]
                        alt_ft = plane_data.get("altitude", "-")
                        if alt_ft != '-':
                            threading.Thread(target=send_to_tracker, args=(plane_data['last_lat'], plane_data['last_lon'], float(alt_ft)), daemon=True).start()
                            add_message(f"Aiming camera at {target_icao}")
                        else:
                            add_message("Target plane altitude unknown, cannot track")
                    else:
                        add_message("No target plane available for tracking")
                    continue
                    if range_km > 25: 
                        range_km -= 25
                        #If a plane is manually selected, just change zoom - continuous tracking handles centering
                        if selected_plane_icao and selected_plane_icao in displayed_planes:
                            add_message(f"Zoomed to {range_km}km on selected plane")
                        else:
                            #No plane selected - animate to home if not already there
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
                            
                            add_message(f"Zoomed to {range_km}km on home")
                
                elif zoom_out_ctrl_rect.collidepoint(mouse_x, mouse_y): #Zoom out
                    if range_km < 250: 
                        range_km += 25
                        #If a plane is manually selected, just change zoom - continuous tracking handles centering
                        if selected_plane_icao and selected_plane_icao in displayed_planes:
                            add_message(f"Zoomed to {range_km}km on selected plane")
                        else:
                            #No plane selected - animate to home if not already there
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
                            
                            add_message(f"Zoomed to {range_km}km on home")

                elif mode_toggle_rect.collidepoint(mouse_x, mouse_y):
                    offline = not offline
                    _config['offlineMode'] = offline
                    functions.save_config(_config)
                    add_message(f"Switched to {'offline' if offline else 'online'} mode")

                elif off_button_rect.collidepoint(mouse_x, mouse_y):
                    tracker_running = False
                    pygame.quit()
                    exit()

                #Plane Selection
                clicked_plane = None
                with data_lock:
                    for icao, rect in plane_rects.items():
                        if rect.collidepoint(mouse_x, mouse_y):
                            clicked_plane = icao
                            break
                
                if clicked_plane:
                    selected_plane_icao = clicked_plane
                    #Start smooth animation to the clicked plane's location
                    if clicked_plane in displayed_planes:
                        plane = displayed_planes[clicked_plane]["plane_data"]
                        target_lat = plane.get("last_lat", _config['myLat'])
                        target_lon = plane.get("last_lon", _config['myLon'])
                        
                        #Start animation
                        is_animating = True
                        animation_start_time = current_time
                        animation_start_lat = view_center_lat
                        animation_start_lon = view_center_lon
                        animation_target_lat = target_lat
                        animation_target_lon = target_lon
                        
                        add_message(f"Panning to {clicked_plane}")
                else:
                    #If clicked elsewhere on radar clear selection and animate back to home
                    if RADAR_RECT.collidepoint(mouse_x, mouse_y):
                        selected_plane_icao = None
                        
                        #Start animation back to home
                        is_animating = True
                        animation_start_time = current_time
                        animation_start_lat = view_center_lat
                        animation_start_lon = view_center_lon
                        animation_target_lat = _config['myLat']
                        animation_target_lon = _config['myLon']
                        
                        add_message("Panning to home location")
        
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
        
        #Draw map if enabled
        if map_enabled and range_km in map_images:
            window.blit(map_images[range_km], (0, 0))
        
        #Draw radar section with clipping
        window.set_clip(RADAR_RECT)
        
        #Draw radar circles
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 100, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 200, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 300, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 400, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 500, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 600, 1)
        
        #Draw range labels
        range_steps = [(100, 0.2), (200, 0.36), (300, 0.52), (400, 0.68), (500, 0.84), (600, 1.0)]
        cos_45 = math.cos(math.radians(45))
        
        for radius, factor in range_steps:
            label_x = RADAR_CENTER_X - (radius * cos_45)
            label_y = RADAR_CENTER_Y - (radius * cos_45)
            draw_text.normal(window, str(round(range_km * factor)), text_font3, (225, 225, 225), int(label_x), int(label_y))
        
        #Draw home location marker
        if not map_enabled:
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
        
        #Update view center to track selected plane if one is manually selected
        if not is_animating and selected_plane_icao and selected_plane_icao in displayed_planes:
            plane = displayed_planes[selected_plane_icao]["plane_data"]
            view_center_lat = plane.get("last_lat", view_center_lat)
            view_center_lon = plane.get("last_lon", view_center_lon)
        
        #Calculate distances using view_center instead of config location
        with data_lock:
            for icao, display_data in displayed_planes.items():
                plane = display_data.get("plane_data", {})
                if not plane_matches_altitude_filter(plane):
                    continue
                lat = plane.get("last_lat")
                lon = plane.get("last_lon")
                if lat is not None and lon is not None:
                    dist = functions.calculate_distance(view_center_lat, view_center_lon, float(lat), float(lon))
                    plane["distance"] = dist 
                    if dist < min_dist:
                        min_dist = dist
                        closest_plane = icao
                    displayed_count += 1

        #Draw radar elements with clipping
        window.set_clip(RADAR_RECT)
        
        #Draw planes with unique highlight
        current_plane_rects = {}
        target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes) else closest_plane

        with data_lock:
            for icao in list(displayed_planes.keys()):
                display_data = displayed_planes[icao]
                plane = display_data["plane_data"]
                if not plane_matches_altitude_filter(plane):
                    continue
                lat = plane.get("last_lat")
                lon = plane.get("last_lon")
                if lat is None or lon is None: continue

                #Calculate fade
                time_remaining = display_data["display_until"] - current_time
                if time_remaining <= 0: continue
                fade_value = max(10, int(255 * (time_remaining / fade_duration))) if time_remaining < fade_duration else 255
                
                try:
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

                    coloured = plane_icon.copy()
                    
                    #Unique Highlight Logic
                    if icao == target_icao:
                        coloured.fill((0, 255, 255), special_flags=pygame.BLEND_RGB_MULT)
                    else:
                        coloured.fill((0, 255, 0), special_flags=pygame.BLEND_RGB_MULT)
                    
                    coloured.set_alpha(fade_value)
                    rotated_image = pygame.transform.rotate(coloured, heading)
                    new_rect = rotated_image.get_rect(center=(x, y))
                    window.blit(rotated_image, new_rect)
                    current_plane_rects[icao] = new_rect
                    
                    #Labels 
                    label_colour = (0, 255, 255) if icao == target_icao else (0, 255, 0)
                    
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
        
        #right sidebar
        current_time_str = strftime("%H:%M:%S", localtime())
        draw_text.center(window, current_time_str, text_font2, (255, 0, 0), SIDEBAR_X + SIDEBAR_WIDTH // 2, 40)
        
        #Sys stats
        disk_free = functions.get_disk_free()
        sys_y = 85
        col1 = SIDEBAR_X + 10
        col2 = SIDEBAR_X + SIDEBAR_WIDTH // 2 - 250
        draw_text.normal(window, f"TEMP:{round(cpu_temp)}C", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 20, 650)
        draw_text.normal(window, f"RAM:{ram_percentage}%", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 20, 670)
        draw_text.normal(window, f"CPU:{psutil.cpu_percent()}%", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 20, 690)
        draw_text.normal(window, f"DISK:{disk_free}GB", stat_font, (255, 255, 255), SIDEBAR_X + (SIDEBAR_WIDTH / 2) + 20, 710)

        #Separator
        pygame.draw.line(window, (100, 100, 100), (SIDEBAR_X + 5, sys_y - 10), (SIDEBAR_X + SIDEBAR_WIDTH - 10, sys_y - 10), 1)

        active_graph_rect = pygame.Rect(SIDEBAR_X + 300, sys_y, 240, 130)
        total_graph_rect = pygame.Rect(SIDEBAR_X + 580, sys_y, 240, 130)

        stats = None
        total_seen = 0
        if not offline:
            stats = functions.get_stats()
            total_seen = stats.get('total', 0)

        persist_top_graph_sample(displayed_count, total_seen, current_time)

        active_peak = max((sample[1] for sample in active_count_history), default=0)
        active_y_max = max(10, ((active_peak + 10 + 9) // 10) * 10)
        draw_line_graph(window, active_graph_rect, list(active_count_history), active_y_max, current_time, TOP_GRAPH_HISTORY_SECONDS, "ACTIVE")
        total_peak = max((sample[1] for sample in total_seen_history), default=0)
        total_y_max = max(100, ((total_peak + 100 + 99) // 100) * 100)
        draw_line_graph(window, total_graph_rect, list(total_seen_history), total_y_max, current_time, TOP_GRAPH_HISTORY_SECONDS, "TOTAL")

        #Flight stats
        if not offline:
            draw_text.normal(window, f"Total Seen: {stats['total']}", text_font3, (255, 255, 255), col1, sys_y)
            draw_text.normal(window, f"Top Mfg: {stats['top_manufacturer']['name'] or '-'}", text_font3, (255, 255, 255), col1, sys_y + 20)
            draw_text.normal(window, f"Top Type: {stats['top_model']['name'] or '-'}", text_font3, (255, 255, 255), col1, sys_y + 40)
            draw_text.normal(window, f"Top Airline: {stats['top_airline']['name'] or '-'}", text_font3, (255, 255, 255), col1, sys_y + 60)
            draw_text.normal(window, f"Active Count: {displayed_count}", text_font3, (0, 255, 0), col1, sys_y + 80)
            draw_text.normal(window, f"Furthest Detected:", text_font3, (255, 255, 255), col1, sys_y + 100)
            draw_text.normal(window, f"Highest Detected:", text_font3, (255, 255, 255), col1, sys_y + 120)

        #Sperator 2
        separator_y = (315 // 2) + 68
        pygame.draw.line(window, (100, 100, 100), (SIDEBAR_X + 5, separator_y), (SIDEBAR_X + SIDEBAR_WIDTH - 10, separator_y), 1)

        altitude_graph_rect = pygame.Rect(SIDEBAR_X + 300, separator_y + 10, 240, 130)
        hits_graph_rect = pygame.Rect(SIDEBAR_X + 580, separator_y + 10, 240, 130)

        #Track plane button!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        pygame.draw.rect(window, (100, 100, 100), (SIDEBAR_X + 250, separator_y + 10, 40, 40))

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

        draw_line_graph(window, altitude_graph_rect, altitude_samples, 50000, current_time, PLANE_GRAPH_HISTORY_SECONDS, "ALTITUDE")
        hits_peak = max((sample[1] for sample in hit_samples), default=0)
        hits_y_max = max(10, ((hits_peak + 10 + 9) // 10) * 10)
        draw_line_graph(window, hits_graph_rect, hit_samples, hits_y_max, current_time, PLANE_GRAPH_HISTORY_SECONDS, "HITS")
        
        if p_data:
            mfg = p_data.get('manufacturer', '-')
            model = p_data.get('model', '-')
            owner = p_data.get('owner', '-')
            
            reg = p_data.get('registration', '-')
            alt = p_data.get('altitude', '-')
            spd = p_data.get('speed', '-')
            lat = p_data.get('last_lat', '-')
            lon = p_data.get('last_lon', '-')
            track = p_data.get('track', '-')

            
            
            id_y = separator_y + 10
            if not offline and mfg != "-" and model != "-":
                draw_text.normal(window, f"{mfg} {model}", plane_identity_font, (255, 255, 255), col1, id_y)
            else:
                draw_text.normal(window, "Unidentified Aircraft", plane_identity_font, (255, 255, 255), col1, id_y)

            if owner != "-":
                draw_text.normal(window, f"{owner}", plane_identity_font, (255, 255, 255), col1, id_y + 20)
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
            
            #Row 4 Hdg / Dist
            if track != '-':
                draw_text.normal(window, f"HDG: {rnd(track, 0)}deg", stat_font, (200, 200, 200), lx, stat_y + spacing*3)
            else:                
                draw_text.normal(window, f"HDG: N/A", stat_font, (200, 200, 200), lx, stat_y + spacing*3)
            
            dist_km = p_data.get('distance', '-')
            dist_nm = dist_km
            if dist_km != '-':
                dist_nm = float(dist_km) / 1.852
            draw_text.normal(window, f"DST: {rnd(dist_nm, 2)}nm", stat_font, (200, 200, 200), rx, stat_y + spacing*3)
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

        #FILTERS
        draw_altitude_filter(window, filter_panel_rect, filter_checkbox_rect, slider_track_rect, filter_slider_handle_rect)
        
        y_msg = logs_y + 10
        with data_lock:
            for message in message_queue[-50:]:
                colour = (200, 200, 200)
                if "WARNING" in message: 
                    colour = (255, 50, 50)
                elif "NEW" in message: 
                    colour = (50, 255, 50)
                draw_text.normal(window, str(message), text_font3, colour, col1 + 5, y_msg)
                y_msg += 11
                if y_msg > logs_y + logs_h - 10: 
                    break

        #TOOLBAR 
        window.blit(pygame.transform.scale(image3, (btn_w, btn_h)), zoom_in_ctrl_rect)
        window.blit(pygame.transform.scale(image4, (btn_w, btn_h)), zoom_out_ctrl_rect)
        btn_img = image5 if not offline else image6
        window.blit(pygame.transform.scale(btn_img, (btn_w, btn_h)), mode_toggle_rect)
        pygame.draw.rect(window, (50, 50, 50), future_button_rect, 1)
        pygame.draw.rect(window, (255, 0, 0), off_button_rect, 0)
        
        pygame.display.update()
        time.sleep(0.05)

if __name__ == "__main__":
    main()

