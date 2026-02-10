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

from modules import draw_text, functions, airport_db

#Load config
_config = functions.load_config()

# #Start C++ process
# cpp_proc = subprocess.Popen(
#     ["./camera_module/communication_test/test"],
#     stdin=subprocess.PIPE,
#     stdout=subprocess.PIPE,
#     stderr=subprocess.PIPE,
#     text=True,
#     bufsize=1
# )

# def send_plane(icao, lat, lon, alt):
#     try:
#         line = f"{icao},{lat},{lon},{alt}\n"
#         cpp_proc.stdin.write(line)
#         cpp_proc.stdin.flush()
#     except BrokenPipeError:
#         print("C++ process died: exiting")
#         sys.exit(1)


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
last_api_failure_time = 0
api_consecutive_failures = 0
network_available = True
message_queue = []
tracker_running = True
display_duration = 30
fade_duration = 10

api_available = True
api_failures_window = []  #list of (timestamp, error_type) tuples
API_FAILURE_WINDOW = 120  
API_FAILURE_THRESHOLD = 5  #5 failures in 2min triggers cooldown
API_COOLDOWN_PERIOD = 300  
last_api_cooldown_start = 0
auto_switched_offline = False

#Thread lock for shared data
data_lock = threading.Lock()

#PYGAME SETUP
pygame.init()
#pygame.mouse.set_visible(False)

width = _config['screenWidth']
height = _config['screenHeight']
window = pygame.display.set_mode((width, height), pygame.FULLSCREEN)

#Fonts
text_font1 = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 16)
text_font2 = pygame.font.Font(os.path.join("textures", "fonts", "DS-DIGI.TTF"), 40)
text_font3 = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 9)
stat_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 13)
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
RADAR_RECT = pygame.Rect(3, 1, 1024, 1024)
RADAR_CENTER_X = RADAR_RECT.centerx
RADAR_CENTER_Y = RADAR_RECT.centery
RADAR_RADIUS = 512

#Sidebar settings
SIDEBAR_X = 1035
SIDEBAR_WIDTH = width - SIDEBAR_X

#UI Buttons
btn_w = 40
btn_h = 40
btn_spacing = (SIDEBAR_WIDTH - (5 * btn_w)) // 6

zoom_in_ctrl_rect = pygame.Rect(SIDEBAR_X + btn_spacing, height - 50, btn_w, btn_h)
zoom_out_ctrl_rect = pygame.Rect(SIDEBAR_X + 2*btn_spacing + btn_w, height - 50, btn_w, btn_h)
mode_toggle_rect = pygame.Rect(SIDEBAR_X + 3*btn_spacing + 2*btn_w, height - 50, btn_w, btn_h)
future_button_rect = pygame.Rect(SIDEBAR_X + 4*btn_spacing + 3*btn_w, height - 50, btn_w, btn_h)
off_button_rect = pygame.Rect(SIDEBAR_X + 5*btn_spacing + 4*btn_w, height - 50, btn_w, btn_h)

#Global for plane selection
selected_plane_icao = None
plane_rects = {} 

#Map images
map_images = {}
for km in [25, 50, 75, 100, 125, 150, 175, 200, 225, 250]:
    map_images[km] = pygame.image.load(os.path.join("textures", "images", f"{km}.png"))

#Helper functions
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

def is_api_healthy():
    global last_api_cooldown_start
    
    #If were in cooldown check if its expired
    if last_api_cooldown_start > 0:
        if time.time() - last_api_cooldown_start < API_COOLDOWN_PERIOD:
            return False
        else:
            #Cooldown expired reset
            global api_failures_window, auto_switched_offline
            api_failures_window = []
            last_api_cooldown_start = 0
            auto_switched_offline = False
            add_message("API cooldown ended")
    
    return True

def record_api_result(success, error_type=None):
    global api_failures_window, last_api_cooldown_start, api_available, auto_switched_offline
    
    current_time = time.time()
    
    if success:
        #Success - clear old failures
        api_failures_window = []
        return
    
    #Failure - record it
    api_failures_window.append((current_time, error_type))
    
    #Remove failures outside the time window
    api_failures_window = [
        (t, e) for t, e in api_failures_window 
        if current_time - t < API_FAILURE_WINDOW
    ]
    
    #Count recent failures by type
    recent_count = len(api_failures_window)
    network_errors = sum(1 for _, e in api_failures_window if e == 'network')
    server_errors = sum(1 for _, e in api_failures_window if e == 'server')
    
    #Trigger cooldown only if we have enough failures
    if recent_count >= API_FAILURE_THRESHOLD:
        last_api_cooldown_start = current_time
        api_available = False
        if not auto_switched_offline:
            auto_switched_offline = True
            add_message(f"API DOWN: {recent_count} failures in {API_FAILURE_WINDOW}s")
            add_message(f"(Network: {network_errors}, Server: {server_errors})")
            add_message(f"Auto-retry in {API_COOLDOWN_PERIOD // 60}m")
    elif recent_count >= 3:
        add_message(f"API unstable: {recent_count} recent failures")

def fetch_plane_info(icao):
    global api_available
    
    if not is_api_healthy():
        return None

    try:
        url = f"https://hexdb.io/api/v1/aircraft/{icao}"
        response = requests.get(url, timeout=5) 
        
        if response.status_code == 200:
            api_data = response.json()
            record_api_result(success=True)  
            api_available = True
            
            manufacturer = functions.clean_string(str(api_data.get("Manufacturer", "-")))
            if manufacturer == "Avions de Transport Regional":
                manufacturer = "ATR"
            elif manufacturer == "Honda Aircraft Company":
                manufacturer = "Honda"
            
            return {
                "manufacturer": manufacturer,
                "registration": functions.clean_string(str(api_data.get("Registration", "-"))),
                "owner": functions.clean_string(str(api_data.get("RegisteredOwners", "-"))),
                "model": functions.clean_string(str(api_data.get("Type", "-")))
            }
            
        elif response.status_code == 404:
            record_api_result(success=True)  
            return None
            
        elif response.status_code == 429:
            print(f"Rate limited for {icao}")
            return None
            
        elif response.status_code >= 500:
            print(f"Server error {response.status_code} for {icao}")
            record_api_result(success=False, error_type='server')
            
            #Try backup API
            return try_backup_api(icao)
        else:
            #Other error - try backup
            return try_backup_api(icao)

    except requests.exceptions.Timeout:
        print(f"API timeout for {icao}")
        record_api_result(success=False, error_type='network')
        return None
        
    except requests.exceptions.ConnectionError:
        print(f"API connection error for {icao}")
        record_api_result(success=False, error_type='network')
        return None
        
    except Exception as e:
        print(f"API error for {icao}: {e}")
        record_api_result(success=False, error_type='server')
        return None
    
    return None

def try_backup_api(icao):
    try:
        url = f"https://opensky-network.org/api/metadata/aircraft/icao/{icao}"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            api_data = response.json()
            record_api_result(success=True)  

            output = {
                "manufacturer": api_data.get("model", "-").split(" ", 1)[0],
                "registration": api_data.get("registration", "-"),
                "owner": api_data.get("operator", "-"),
                "model": api_data.get("model", "-").split(" ", 1)[1] if " " in api_data.get("model", "") else "-"
            }

            if output.get("manufacturer") == '' or output.get("registration") == '' or output.get("owner") == '' or output.get("model") == '':
                return None

            return output
            
        elif response.status_code == 404:
            # Plane not found in backup 
            record_api_result(success=True)
            return None
            
        elif response.status_code >= 500:
            print(f"Backup server error {response.status_code}")
            record_api_result(success=False, error_type='server')
            return None
            
    except Exception as e:
        print(f"Backup API error: {e}")
        #Dont record another failure already recorded from primary
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
        
        #Write all data back
        with open(csv_path, 'w', newline='', encoding='utf-8') as file:
            fieldnames = ["icao", "manufacturer", "model", "full_model", "airline", "location_history", "altitude", "timestamp"]
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            for plane in existing_planes.values():
                writer.writerow(plane)
                
    except Exception as e:
        print(f"CSV error: {e}")

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
            if key not in ["location_history", "last_update_time", "last_lat", "last_lon"]:
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
        #Also save to csv and firebase now that we have data
        save_plane_to_csv(icao, active_planes[icao])
        upload_to_firebase(active_planes[icao])

#THREAD 2: ADSB Data Processing
def adsb_processing_thread():
    global is_receiving, is_processing, tracker_running, offline, api_available, network_available, auto_switched_offline
    
    SERVER_SBS = ("localhost", 30003)
    last_stats_upload = time.time()
    last_network_check = time.time()
    last_api_retry = time.time()
    
    sock = None
    
    while tracker_running:
        current_time = time.time()
        
        #Check network every 30 seconds
        if current_time - last_network_check > 30:
            network_available = check_network()
            if not network_available and not offline:
                add_message("Network down switching to Offline")
            last_network_check = current_time
            
        if auto_switched_offline and last_api_cooldown_start > 0:
            time_passed = current_time - last_api_cooldown_start
            if time_passed > API_COOLDOWN_PERIOD:
                pass
            elif current_time - last_api_retry > 60:
                mins_left = int((API_COOLDOWN_PERIOD - time_passed) // 60) + 1
                secs_left = int(API_COOLDOWN_PERIOD - time_passed) % 60
                add_message(f"API cooldown: {mins_left}m {secs_left}s remaining")
                last_api_retry = current_time

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
                
                effective_offline = offline or not network_available or not is_api_healthy()

                with data_lock:
                    if icao in active_planes:
                        cached = active_planes[icao]
                        plane_data["manufacturer"] = cached.get("manufacturer", "-")
                        plane_data["registration"] = cached.get("registration", "-")
                        plane_data["owner"] = cached.get("owner", "-")
                        plane_data["model"] = cached.get("model", "-")
                        if "last_lat" in cached:
                            plane_data["prev_lat"] = cached["last_lat"]
                            plane_data["prev_lon"] = cached["last_lon"]
                    else:
                        plane_data["manufacturer"] = "-"
                        plane_data["registration"] = "-"
                        plane_data["owner"] = "-"
                        plane_data["model"] = "-"
                    
                    plane_data["last_lat"] = float(plane_data["lat"])
                    plane_data["last_lon"] = float(plane_data["lon"])
                    plane_data["last_update_time"] = time.time()
                    
                    active_planes[icao] = plane_data
                    displayed_planes[icao] = {
                        "plane_data": plane_data,
                        "display_until": time.time() + display_duration
                    }
                
                # If we are in online mode and we dont have API data yet launch a background fetch
                if not effective_offline and plane_data["manufacturer"] == "-":
                    threading.Thread(target=api_worker_thread, args=(icao, plane_data), daemon=True).start()
                elif not effective_offline:
                    pass

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

        if current_time - last_stats_upload > 60 and not offline and is_api_healthy() and network_available:
            try:
                cpu_temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
                ram_percentage = psutil.virtual_memory()[2]
                
                #Upload flight stats with validation
                today = datetime.today().strftime("%Y-%m-%d")
                stats_ref = db.reference(f"{today}/stats")
                
                new_stats = functions.get_stats()
                
                #Validate stats before uploading to prevent overwriting with zeros
                if new_stats and isinstance(new_stats.get('total'), int) and new_stats.get('total', 0) > 0:
                    current_stats = stats_ref.get()
                    
                    #Only update if new stats are valid and higher equal
                    if current_stats is None or new_stats.get('total', 0) >= current_stats.get('total', 0):
                        stats_ref.set(new_stats)
                    else:
                        #Log but don't upload if new stats look wrong
                        print(f"Stats validation: Skipping upload - new total ({new_stats.get('total')}) < current ({current_stats.get('total')})")
                        add_message(f"Skipping Firebase upload")
                else:
                    print(f"Stats validation: Invalid data - {new_stats}")
                    add_message(f"Stats read error skipping upload")
                
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
                add_message(f"Stats upload failed: {str(e)[:30]}")

        is_receiving = False

    if sock:
        sock.close()

#Start ADSB processing thread
processing_thread = threading.Thread(target=adsb_processing_thread, daemon=True)
processing_thread.start()

#THREAD 1: Main UI Thread
def main():
    global tracker_running, offline, api_available, selected_plane_icao
    
    start_time = time.time()
    range_km = 50
    map_enabled = False
    
    while True:
        current_time = time.time()
        
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
                
            elif event.type == pygame.MOUSEBUTTONDOWN:
                last_tap_time = time.time()
                mouse_x, mouse_y = pygame.mouse.get_pos()
                
                #Toolbar Buttons
                if zoom_in_ctrl_rect.collidepoint(mouse_x, mouse_y): # Zoom IN (range decreases)
                    if range_km > 25: range_km -= 25
                
                elif zoom_out_ctrl_rect.collidepoint(mouse_x, mouse_y): # Zoom OUT (range increases)
                    if range_km < 250: range_km += 25

                elif mode_toggle_rect.collidepoint(mouse_x, mouse_y):
                    global api_consecutive_failures
                    offline = not offline
                    auto_switched_offline = False
                    api_consecutive_failures = 0
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
                else:
                    #If clicked elsewhere on radar clear selection to default back to closest plane
                    if RADAR_RECT.collidepoint(mouse_x, mouse_y):
                        selected_plane_icao = None
        
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
        
        #Draw center point
        if not map_enabled:
            pygame.draw.polygon(window, (0, 255, 255), [(RADAR_CENTER_X, RADAR_CENTER_Y - 2), (RADAR_CENTER_X + 2, RADAR_CENTER_Y), (RADAR_CENTER_X, RADAR_CENTER_Y + 2), (RADAR_CENTER_X - 2, RADAR_CENTER_Y)])
        
        #Draw airports
        for key in airport_db.airports_uk:
            airport = airport_db.airports_uk[key]
            x, y = functions.coords_to_xy(airport["lat"], airport["lon"], range_km, _config['myLat'], _config['myLon'], width, height, RADAR_CENTER_X, RADAR_CENTER_Y)
            pygame.draw.polygon(window, (0, 0, 255), [(x, y - 2), (x + 2, y), (x, y + 2), (x - 2, y)])
            draw_text.center(window, airport["airport_name"], text_font3, (255, 255, 255), x, y - 10)
        
        displayed_count = 0
        closest_plane = None
        min_dist = float('inf')
        
        with data_lock:
            for icao, display_data in displayed_planes.items():
                plane = display_data.get("plane_data", {})
                lat = plane.get("last_lat")
                lon = plane.get("last_lon")
                if lat is not None and lon is not None:
                    dist = functions.calculate_distance(_config['myLat'], _config['myLon'], float(lat), float(lon))
                    plane["distance"] = dist # Store for display
                    if dist < min_dist:
                        min_dist = dist
                        closest_plane = icao
                    displayed_count += 1

        #2. Draw radar elements with clipping
        window.set_clip(RADAR_RECT)
        
        #3. Draw planes with unique highlight
        current_plane_rects = {}
        target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes) else closest_plane

        with data_lock:
            for icao in list(displayed_planes.keys()):
                display_data = displayed_planes[icao]
                plane = display_data["plane_data"]
                lat = plane.get("last_lat")
                lon = plane.get("last_lon")
                if lat is None or lon is None: continue

                #Calculate fade
                time_remaining = display_data["display_until"] - current_time
                if time_remaining <= 0: continue
                fade_value = max(10, int(255 * (time_remaining / fade_duration))) if time_remaining < fade_duration else 255
                
                try:
                    x, y = functions.coords_to_xy(float(lat), float(lon), range_km, _config['myLat'], _config['myLon'], width, height, RADAR_CENTER_X, RADAR_CENTER_Y)
                    
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
                        plane["track"] = heading # Update track with calculated heading
                    
                    colored_icon = plane_icon.copy()
                    
                    #Unique Highlight Logic
                    if icao == target_icao:
                        colored_icon.fill((0, 255, 255), special_flags=pygame.BLEND_RGB_MULT)
                    else:
                        colored_icon.fill((0, 255, 0), special_flags=pygame.BLEND_RGB_MULT)
                    
                    colored_icon.set_alpha(fade_value)
                    rotated_image = pygame.transform.rotate(colored_icon, heading)
                    new_rect = rotated_image.get_rect(center=(x, y))
                    window.blit(rotated_image, new_rect)
                    current_plane_rects[icao] = new_rect
                    
                    #Labels 
                    label_color = (0, 255, 255) if icao == target_icao else (0, 255, 0)
                    
                    if not offline and plane.get('manufacturer') != "-":
                        draw_text.fading(window, plane.get("owner", "-"), text_font3, label_color, x, y - 13, fade_value)
                        draw_text.fading(window, f"{plane.get('manufacturer')} {plane.get('model')}", text_font3, label_color, x, y + 13, fade_value)
                    else:
                        draw_text.fading(window, icao, text_font3, label_color, x, y - 13, fade_value)
                        draw_text.fading(window, f"{plane.get('altitude', '-')}ft", text_font3, label_color, x, y + 13, fade_value)
                            
                except Exception as e:
                    print(f"Draw error for {icao}: {e}")
                    print(x, y)
        
        with data_lock:
            plane_rects = current_plane_rects
        
        #Reset clip for UI elements outside radar
        window.set_clip(None)
        
        #Draw radar border
        pygame.draw.rect(window, (0, 255, 0), RADAR_RECT, 2)
        
        #Draw Off button
        pygame.draw.rect(window, (255, 0, 0), off_button_rect)
        
        #right sidebar
        current_time_str = strftime("%H:%M:%S", localtime())
        draw_text.center(window, current_time_str, text_font2, (255, 0, 0), SIDEBAR_X + SIDEBAR_WIDTH // 2, 40)
        
        #Sys stats
        disk_free = functions.get_disk_free()
        sys_y = 85
        col1 = SIDEBAR_X + 10
        col2 = SIDEBAR_X + SIDEBAR_WIDTH // 2 + 5
        draw_text.normal(window, f"TEMP:{round(cpu_temp)}°C", stat_font, (255, 255, 255), col1, sys_y)
        draw_text.normal(window, f"RAM:{ram_percentage}%", stat_font, (255, 255, 255), col2, sys_y)
        draw_text.normal(window, f"CPU:{psutil.cpu_percent()}%", stat_font, (255, 255, 255), col1, sys_y + 20)
        draw_text.normal(window, f"DISK:{disk_free}GB", stat_font, (255, 255, 255), col2, sys_y + 20)

        #Flight stats
        if not offline:
            stats = functions.get_stats()
            f_y = 140
            draw_text.normal(window, f"Total Seen: {stats['total']}", text_font3, (255, 255, 255), col1, f_y)
            draw_text.normal(window, f"Top Mfg: {stats['top_manufacturer']['name'] or '-'}", text_font3, (255, 255, 255), col1, f_y + 20)
            draw_text.normal(window, f"Top Type: {stats['top_model']['name'] or '-'}", text_font3, (255, 255, 255), col1, f_y + 40)
            draw_text.normal(window, f"Top Airline: {stats['top_airline']['name'] or '-'}", text_font3, (255, 255, 255), col1, f_y + 60)
            draw_text.normal(window, f"Active Count: {displayed_count}", text_font3, (0, 255, 0), col1, f_y + 80)

        #Plane Info
        separator_y = 235
        pygame.draw.line(window, (100, 100, 100), (SIDEBAR_X + 5, separator_y), (SIDEBAR_X + SIDEBAR_WIDTH - 10, separator_y), 1)
        
        target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes) else closest_plane
        p_data = displayed_planes.get(target_icao, {}).get("plane_data") if target_icao else None
        
        if p_data:
            mfg = p_data.get('manufacturer', '-')
            model = p_data.get('model', '-')
            owner = p_data.get('owner', '-')
            
            id_y = separator_y + 10
            draw_text.normal(window, f"{mfg} {model}", plane_identity_font, (255, 255, 255), col1 + 5, id_y)
            draw_text.normal(window, f"{owner}", plane_identity_font, (255, 255, 255), col1 + 5, id_y + 20)
            
            stat_y = id_y + 50
            lx = col1 + 5
            rx = col2 - 10
            spacing = 18  
            
            def rnd(val, dec=1): 
                try: return round(float(val), dec)
                except: return "-"

            #Row 1: ICAO / Reg
            draw_text.normal(window, f"ICAO: {target_icao}", stat_font, (200, 200, 200), lx, stat_y)
            draw_text.normal(window, f"REG: {p_data.get('registration', '-')}", stat_font, (200, 200, 200), rx, stat_y)
            
            #Row 2: Alt / Speed
            draw_text.normal(window, f"ALT: {p_data.get('altitude', '-')}ft", stat_font, (200, 200, 200), lx, stat_y + spacing)
            draw_text.normal(window, f"SPD: {rnd(p_data.get('speed', '-'))}kt", stat_font, (200, 200, 200), rx, stat_y + spacing)
            
            #Row 3: Lat / Lon (4 decimals)
            draw_text.normal(window, f"LAT: {rnd(p_data.get('last_lat', '-'), 4)}", stat_font, (200, 200, 200), lx, stat_y + spacing*2)
            draw_text.normal(window, f"LON: {rnd(p_data.get('last_lon', '-'), 4)}", stat_font, (200, 200, 200), rx, stat_y + spacing*2)
            
            #Row 4: Hdg / Dist
            draw_text.normal(window, f"HDG: {rnd(p_data.get('track', '-'), 0)}°", stat_font, (200, 200, 200), lx, stat_y + spacing*3)
            draw_text.normal(window, f"DST: {rnd(p_data.get('distance', '-'))}km", stat_font, (200, 200, 200), rx, stat_y + spacing*3)
        else:
            draw_text.center(window, "NO PLANE SELECTED", text_font1, (100, 100, 100), SIDEBAR_X + SIDEBAR_WIDTH // 2, separator_y + 80)

        #4. LOGS BOX 
        logs_y = 370
        logs_h = 560
        pygame.draw.rect(window, (20, 20, 20), (SIDEBAR_X+5, logs_y, SIDEBAR_WIDTH-15, logs_h), 0, 5)
        pygame.draw.rect(window, (100, 100, 100), (SIDEBAR_X+5, logs_y, SIDEBAR_WIDTH-15, logs_h), 1, 5)
        
        y_msg = logs_y + 10
        with data_lock:
            for message in message_queue[-50:]:
                color = (200, 200, 200)
                if "WARNING" in message: color = (255, 50, 50)
                elif "NEW" in message: color = (50, 255, 50)
                draw_text.normal(window, str(message), text_font3, color, col1 + 5, y_msg)
                y_msg += 11
                if y_msg > logs_y + logs_h - 10: break

        #5. TOOLBAR 
        window.blit(pygame.transform.scale(image3, (btn_w, btn_h)), zoom_in_ctrl_rect)
        window.blit(pygame.transform.scale(image4, (btn_w, btn_h)), zoom_out_ctrl_rect)
        btn_img = image5 if not offline else image6
        window.blit(pygame.transform.scale(btn_img, (btn_w, btn_h)), mode_toggle_rect)
        pygame.draw.rect(window, (50, 50, 50), future_button_rect, 1, 5)
        pygame.draw.rect(window, (255, 0, 0), off_button_rect, 0, 5)
        
        pygame.display.update()
        time.sleep(0.05)

if __name__ == "__main__":
    main()