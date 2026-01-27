#!/usr/bin/env python3

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
import subprocess
import sys

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

def send_plane(icao, lat, lon, alt):
    try:
        line = f"{icao},{lat},{lon},{alt}\n"
        cpp_proc.stdin.write(line)
        cpp_proc.stdin.flush()
    except BrokenPipeError:
        print("C++ process died: exiting")
        sys.exit(1)


#Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("./config/firebase.json")
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app"
    })

#Global variables
offline = _config['mode']['offline']
active_planes = {}
displayed_planes = {}
is_receiving = False
is_processing = False
api_available = True
network_available = True
message_queue = []
tracker_running = True
display_duration = 30
fade_duration = 10

#Thread lock for shared data
data_lock = threading.Lock()

#Initialize Pygame
pygame.init()
pygame.mouse.set_visible(False)

width = _config['display']['screen_width']
height = _config['display']['screen_height']
window = pygame.display.set_mode((width, height), pygame.FULLSCREEN)

#Fonts
text_font1 = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 16)
text_font2 = pygame.font.Font(os.path.join("textures", "fonts", "DS-DIGI.TTF"), 40)
text_font3 = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 9)

#Load images
image1 = pygame.image.load(os.path.join("textures", "icons", "open_menu.png"))
image2 = pygame.image.load(os.path.join("textures", "icons", "close_menu.png"))
image3 = pygame.image.load(os.path.join("textures", "icons", "zoom_in.png"))
image4 = pygame.image.load(os.path.join("textures", "icons", "zoom_out.png"))
image5 = pygame.image.load(os.path.join("textures", "icons", "online.png"))
image6 = pygame.image.load(os.path.join("textures", "icons", "offline.png"))
image7 = pygame.image.load(os.path.join("textures", "icons", "off.png"))
plane_icon = pygame.image.load(os.path.join("textures", "icons", "plane.png")).convert_alpha()

#Set image coordinates and drawing styles
open_menu_image = image1.get_rect(center=(765, 240))
close_menu_image = image2.get_rect(center=(550, 240))
zoom_in_image = image3.get_rect(topleft=(585, 415))
zoom_out_image = image4.get_rect(topleft=(635, 415))
online_image = image5.get_rect(topleft=(685, 415))
offline_image = image6.get_rect(topleft=(685, 415))
off_image = image7.get_rect(topleft=(735, 415))

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
        requests.get("https://www.google.com", timeout=3)
        return True
    except:
        return False

def fetch_plane_info(icao):
    try:
        url = f"https://hexdb.io/api/v1/aircraft/{icao}" #Amazing API!!! :)
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
                "model": functions.clean_string(str(api_data.get("Type", "-")))
            }
        else: 
            url = f"https://opensky-network.org/api/metadata/aircraft/icao/{icao}" #Backup API that kind of sucks :/
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                api_data = response.json()

                output = {
                    "manufacturer": api_data.get("model", "-").split(" ", 1)[0],
                    "registration": api_data.get("registration", "-"),
                    "owner": api_data.get("operator", "-"),
                    "model": api_data.get("model", "-").split(" ", 1)[1]
                }

                if output.get("manufacturer") == '' or output.get("registration") == '' or output.get("owner") == '' or output.get("model") == '':
                    return None

                return output

    except Exception as e:
        print(f"API error for {icao}: {e}")
    
    return None

def save_plane_to_csv(icao, plane_data):
    try:
        #Check if we have complete API data
        manufacturer = plane_data.get('manufacturer', '-')
        model = plane_data.get('model', '-')
        owner = plane_data.get('owner', '-')
        registration = plane_data.get('registration', '-')
        
        if manufacturer == "-" or model == "-" or owner == "-" or registration == "-":
            return  #Don't save incomplete data
        
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
            return  #Don't upload incomplete data
        
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
            #Update only non-empty fields
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

#THREAD 2: ADSB Data Processing
def adsb_processing_thread():
    global is_receiving, is_processing, tracker_running, offline, api_available, network_available
    
    SERVER_SBS = ("localhost", 30003)
    last_stats_upload = time.time()
    last_network_check = time.time()
    last_api_retry = time.time()
    
    while tracker_running:
        current_time = time.time()
        
        # Check network every 30 seconds
        if current_time - last_network_check > 30:
            network_available = check_network()
            if not network_available and not offline:
                add_message("WARNING: No network connection")
            last_network_check = current_time
        
        if offline:
            #Offline mode
            if current_time - last_api_retry > 60:
                last_api_retry = current_time
            
            sock = functions.connect(SERVER_SBS)
            sock.settimeout(0.5)
            buffer = ""
            
            while tracker_running and offline:
                is_receiving = True
                
                try:
                    data = sock.recv(1024)
                    if not data:
                        print("Reconnecting...")
                        sock.close()
                        time.sleep(1)
                        sock = functions.connect(SERVER_SBS)
                        continue
                    
                    buffer += data.decode(errors="ignore")
                    lines = buffer.split("\n")
                    buffer = lines[-1]
                    
                    #Process each message
                    for line in lines[:-1]:
                        plane_data = functions.split_message(line)
                        
                        if plane_data and plane_data["lon"] != "-" and plane_data["lat"] != "-":
                            icao = plane_data['icao']
                            
                            #Set defaults for offline
                            plane_data["manufacturer"] = "-"
                            plane_data["registration"] = "-"
                            plane_data["owner"] = "-"
                            plane_data["model"] = "-"

                            send_plane(icao, plane_data["lat"], plane_data["lon"], plane_data["altitude"])
                            
                            #Track position
                            with data_lock:
                                if icao in active_planes:
                                    if "last_lat" in active_planes[icao]:
                                        plane_data["prev_lat"] = active_planes[icao]["last_lat"]
                                        plane_data["prev_lon"] = active_planes[icao]["last_lon"]
                                
                                plane_data["last_lat"] = float(plane_data["lat"])
                                plane_data["last_lon"] = float(plane_data["lon"])
                                plane_data["last_update_time"] = time.time()
                                
                                active_planes[icao] = plane_data
                                displayed_planes[icao] = {
                                    "plane_data": plane_data,
                                    "display_until": time.time() + display_duration
                                }
                    
                    #Clean old planes every few seconds
                    current_time = time.time()
                    with data_lock:
                        old_planes = []
                        for icao in displayed_planes:
                            if displayed_planes[icao]["display_until"] < current_time:
                                old_planes.append(icao)
                        for icao in old_planes:
                            del displayed_planes[icao]
                            
                except socket.timeout:
                    is_receiving = False
                    continue
                except Exception as e:
                    print(f"Offline error: {e}")
                    is_receiving = False
                    time.sleep(1)
                    
            sock.close()
            is_receiving = False
            
        else:
            #Online mode:
            #Listen to messages for 1 second from the radio antenna
            sock = functions.connect(SERVER_SBS)
            sock.settimeout(0.1)
            buffer = ""
            collected_planes = {}
            end_time = time.time() + 1
            is_receiving = True
            
            while time.time() < end_time and tracker_running:
                try:
                    data = sock.recv(1024)
                    if data:
                        buffer += data.decode(errors="ignore")
                        lines = buffer.split("\n")
                        buffer = lines[-1]
                        
                        for line in lines[:-1]:
                            plane_data = functions.split_message(line)
                            if plane_data and plane_data["lon"] != "-" and plane_data["lat"] != "-":
                                collected_planes[plane_data['icao']] = plane_data
                                
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"Collection error: {e}")
                    break
            
            sock.close()
            is_receiving = False
            
            if not tracker_running:
                break
            
            #Process collected planes
            if len(collected_planes) > 0:
                is_processing = True
                add_message(f"Processing {len(collected_planes)} messages")
                
                api_failures = 0
                planes_with_data = 0
                
                #For each plane
                for icao in collected_planes:
                    if not tracker_running:
                        break
                    
                    plane_data = collected_planes[icao]

                    send_plane(icao, plane_data["lat"], plane_data["lon"], plane_data["altitude"])
                    
                    #Check if we need API data
                    need_api = True
                    with data_lock:
                        if icao in active_planes:
                            cached = active_planes[icao]
                            if cached.get("manufacturer") != "-" and cached.get("model") != "-":
                                need_api = False
                                #Copy cached data
                                plane_data["manufacturer"] = cached["manufacturer"]
                                plane_data["registration"] = cached["registration"]
                                plane_data["owner"] = cached["owner"]
                                plane_data["model"] = cached["model"]
                                planes_with_data += 1
                    
                    #Fetch plane data from API if we only have ICAO code
                    if need_api:
                        if network_available:
                            api_data = fetch_plane_info(icao)
                            if api_data:
                                plane_data["manufacturer"] = api_data["manufacturer"]
                                plane_data["registration"] = api_data["registration"]
                                plane_data["owner"] = api_data["owner"]
                                plane_data["model"] = api_data["model"]
                                add_message(f"NEW: {api_data['manufacturer']} {api_data['model']}")
                                planes_with_data += 1
                                api_available = True
                            else:
                                # API failed so set offline data
                                plane_data["manufacturer"] = "-"
                                plane_data["registration"] = "-"
                                plane_data["owner"] = "-"
                                plane_data["model"] = "-"
                                api_failures += 1
                                api_available = False
                        else:
                            #No network so set offline data
                            plane_data["manufacturer"] = "-"
                            plane_data["registration"] = "-"
                            plane_data["owner"] = "-"
                            plane_data["model"] = "-"
                    
                    #Track position
                    with data_lock:
                        if icao in active_planes:
                            if "last_lat" in active_planes[icao]:
                                plane_data["prev_lat"] = active_planes[icao]["last_lat"]
                                plane_data["prev_lon"] = active_planes[icao]["last_lon"]
                        
                        plane_data["last_lat"] = float(plane_data["lat"])
                        plane_data["last_lon"] = float(plane_data["lon"])
                        plane_data["last_update_time"] = time.time()
                        
                        active_planes[icao] = plane_data
                        displayed_planes[icao] = {
                            "plane_data": plane_data,
                            "display_until": time.time() + display_duration
                        }
                    
                    #Only save if we have all plane data
                    if plane_data.get("manufacturer") != "-" and plane_data.get("model") != "-":
                        save_plane_to_csv(icao, plane_data)
                        upload_to_firebase(plane_data)
                
                #API error warnings
                if api_failures > 0:
                    add_message(f"WARNING: {api_failures} API requests failed")
                    api_available = False
                
                if planes_with_data > 0:
                    add_message(f"SAVED: {planes_with_data} planes")
                
                #Clean old planes
                current_time = time.time()
                with data_lock:
                    old_planes = []
                    for icao in displayed_planes:
                        if displayed_planes[icao]["display_until"] < current_time:
                            old_planes.append(icao)
                    for icao in old_planes:
                        del displayed_planes[icao]
                
                is_processing = False
                add_message("Procesing complete")
                
            #Upload device stats periodically to Firebase
            if time.time() - last_stats_upload > 30:
                try:
                    cpu_temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
                    ram_percentage = psutil.virtual_memory()[2]
                    
                    stats_ref = db.reference("device_stats")
                    stats_ref.update({
                        "cpu_temp": cpu_temp,
                        "ram_percentage": ram_percentage,
                        "run": True
                    })
                    last_stats_upload = time.time()
                except Exception as e:
                    print(f"Stats upload error: {e}")
            
            time.sleep(0.1)

#Start ADSB processing thread
processing_thread = threading.Thread(target=adsb_processing_thread, daemon=True)
processing_thread.start()

#THREAD 1: Main UI Thread
def main():
    global tracker_running, offline, api_available
    
    start_time = time.time()
    update_time = time.time()
    last_tap_time = time.time()
    menu_open = False
    range_km = 50
    map_enabled = False
    
    while True:
        current_time = time.time()
        
        #Restart every 30 minutes
        if current_time - start_time > 1800:
            print("Restarting...")
            functions.restart_script()
        
        #Upload stats every minute to Firebase
        if current_time - update_time > 60 and not offline:
            today = datetime.today().strftime("%Y-%m-%d")
            ref = db.reference(f"{today}/stats")
            ref.set(functions.get_stats())
            update_time = time.time()
        
        #Get CPU and RAM stats
        cpu_temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
        ram_percentage = psutil.virtual_memory()[2]
        
        #Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                tracker_running = False
                pygame.quit()
                exit()
                
            elif event.type == MOUSEBUTTONDOWN:
                last_tap_time = time.time()
                mouse_x, mouse_y = pygame.mouse.get_pos()
                
                #Open menu button
                if mouse_x > 755 and mouse_y > 230 and mouse_x < 795 and mouse_y < 260 and not menu_open:
                    menu_open = True
                    
                #Close menu button
                elif mouse_x > 540 and mouse_y > 230 and mouse_x < 570 and mouse_y < 260 and menu_open:
                    menu_open = False
                    
                #Menu buttons
                if menu_open:
                    #Zoom out
                    if mouse_x > 585 and mouse_y > 415 and mouse_x < 625 and mouse_y < 455:
                        if range_km > 25:
                            range_km -= 25
                    
                    #Zoom in
                    elif mouse_x > 635 and mouse_y > 415 and mouse_x < 675 and mouse_y < 455:
                        if range_km < 250:
                            range_km += 25
                    
                    #Toggle offline/online 
                    elif mouse_x > 685 and mouse_y > 415 and mouse_x < 725 and mouse_y < 455:
                        #Flip offline mode
                        offline = not offline

                        #Save new offline state to config file
                        _config['mode']['offline'] = offline
                        functions.save_config(_config)
                
                        if offline:
                            add_message("Switched to offline mode")
                        else:
                            add_message("Switched to online mode")
                    
                    #Quit button
                    elif mouse_x > 735 and mouse_y > 415 and mouse_x < 775 and mouse_y < 455:
                        tracker_running = False
                        pygame.quit()
                        exit()
        
        #Enable screen saver after 3 minutes
        if current_time - last_tap_time < 180:
            #Clear screen
            pygame.draw.rect(window, (0, 0, 0), (0, 0, width, height))
            
            #Draw map if enabled
            if map_enabled and range_km in map_images:
                window.blit(map_images[range_km], (0, 0))
            
            #Draw radar circles
            pygame.draw.circle(window, (225, 225, 225), (400, 240), 100, 1)
            pygame.draw.circle(window, (225, 225, 225), (400, 240), 200, 1)
            pygame.draw.circle(window, (225, 225, 225), (400, 240), 300, 1)
            pygame.draw.circle(window, (225, 225, 225), (400, 240), 400, 1)
            
            #Draw range labels
            draw_text.normal(window, str(round(range_km * 0.25)), text_font3, (225, 225, 225), 305, 235)
            draw_text.normal(window, str(round(range_km * 0.5)), text_font3, (225, 225, 225), 205, 235)
            draw_text.normal(window, str(round(range_km * 0.75)), text_font3, (225, 225, 225), 105, 235)
            draw_text.normal(window, str(round(range_km)), text_font3, (225, 225, 225), 5, 235)
            
            #Draw center point
            if not map_enabled:
                pygame.draw.polygon(window, (0, 255, 255), [(400, 238), (402, 240), (400, 242), (398, 240)])
            
            #Draw airports
            for key in airport_db.airports_uk:
                airport = airport_db.airports_uk[key]
                x, y = functions.coords_to_xy(airport["lat"], airport["lon"], range_km, _config['home_coordinates']['latitude'], _config['home_coordinates']['longitude'], width, height)
                pygame.draw.polygon(window, (0, 0, 255), [(x, y - 2), (x + 2, y), (x, y + 2), (x - 2, y)])
                draw_text.center(window, airport["airport_name"], text_font3, (255, 255, 255), x, y - 10)
            
            #Draw planes
            displayed_count = 0
            incomplete_count = 0
            
            with data_lock:
                for icao in list(displayed_planes.keys()):
                    display_data = displayed_planes[icao]
                    plane = display_data["plane_data"]
                    
                    lat = plane.get("last_lat")
                    lon = plane.get("last_lon")
                    
                    if lat is None or lon is None:
                        continue
                    
                    displayed_count += 1
                    
                    #Check if plane has complete data
                    has_complete_data = True
                    if not offline:
                        owner = plane.get("owner", "-")
                        model = plane.get('model', '-')
                        manufacturer = plane.get('manufacturer', '-')
                        if owner == "-" or model == "-" or manufacturer == "-":
                            has_complete_data = False
                            incomplete_count += 1
                    
                    #Calculate fade
                    time_remaining = display_data["display_until"] - current_time
                    if time_remaining <= 0:
                        continue
                    
                    fade_value = 255
                    if time_remaining < fade_duration:
                        fade_value = int(255 * (time_remaining / fade_duration))
                        if fade_value < 10:
                            fade_value = 10
                    
                    #Draw plane
                    try:
                        x, y = functions.coords_to_xy(float(lat), float(lon), range_km, _config['home_coordinates']['latitude'], _config['home_coordinates']['longitude'], width, height)
                        
                        prev_lat = plane.get("prev_lat")
                        prev_lon = plane.get("prev_lon")
                        
                        if prev_lat is not None and prev_lon is not None:
                            heading = functions.calculate_heading(prev_lat, prev_lon, lat, lon)
                            
                            colored_icon = plane_icon.copy()
                            colored_icon.fill((255, 202, 0), special_flags=pygame.BLEND_RGB_MULT)
                            colored_icon.set_alpha(fade_value)
                            
                            rotated_image = pygame.transform.rotate(colored_icon, heading)
                            new_rect = rotated_image.get_rect(center=(x, y))
                            window.blit(rotated_image, new_rect)
                            
                            #Draw labels based on data availability
                            if has_complete_data and not offline:
                                manufacturer = plane.get('manufacturer', '-')
                                model = plane.get('model', '-')
                                owner = plane.get("owner", "-")
                                
                                plane_string = f"{manufacturer} {model}"
                                
                                draw_text.fading(window, owner, text_font3, (255, 202, 0), x, y - 13, fade_value)
                                draw_text.fading(window, plane_string, text_font3, (255, 202, 0), x, y + 13, fade_value)
                            else:
                                #Show ICAO and altitude only (offline data)
                                altitude = plane.get("altitude", "-")
                                draw_text.fading(window, icao, text_font3, (255, 202, 0), x, y - 13, fade_value)
                                draw_text.fading(window, f"{altitude}ft", text_font3, (255, 202, 0), x, y + 13, fade_value)
                                
                    except Exception as e:
                        print(f"Draw error for {icao}: {e}")
            
            #Draw menu
            if menu_open:
                current_time_str = strftime("%H:%M:%S", localtime())
                
                pygame.draw.rect(window, (0, 0, 0), (570, 10, 220, 460), 0, 5)
                
                draw_text.center(window, current_time_str, text_font2, (255, 0, 0), 675, 40)
                draw_text.center(window, f"CPU:{round(cpu_temp)}°C  RAM:{ram_percentage}%", text_font1, (255, 255, 255), 675, 75)
                
                #Status
                if is_receiving:
                    status = "Receiving"
                elif is_processing:
                    status = "Processing"
                else:
                    status = "Idle"
                
                display_rgb = (255, 255, 255)
                if displayed_count < 10:
                    display_rgb = (255, 0, 0)
                elif displayed_count < 20:
                    display_rgb = (255, 255, 0)
                else:
                    display_rgb = (0, 255, 0)
                
                draw_text.center(window, f"Status: {status}", text_font1, (255, 255, 255), 675, 100)
                draw_text.center(window, f"Active: {displayed_count}", text_font1, display_rgb, 675, 135)
                
                #Message log
                pygame.draw.rect(window, (255, 255, 255), (580, 155, 200, 240), 2)
                
                y = 159
                with data_lock:
                    for message in message_queue[-23:]:
                        if "WARNING" in message:
                            draw_text.normal(window, str(message), text_font3, (255, 0, 0), 585, y)
                        elif "NEW" in message:
                            draw_text.normal(window, str(message), text_font3, (0, 255, 0), 585, y)
                        else:
                            draw_text.normal(window, str(message), text_font3, (255, 255, 255), 585, y)
                            
                        y += 10
                
                #Buttons
                window.blit(image2, close_menu_image)
                window.blit(image3, zoom_in_image)
                window.blit(image4, zoom_out_image)
                window.blit(image7, off_image)
                
                if not offline:
                    window.blit(image5, online_image)
                else:
                    window.blit(image6, offline_image)
            else:
                window.blit(image1, open_menu_image)
        else:
            #Enable screen saver 
            pygame.draw.rect(window, (0, 0, 0), (0, 0, width, height))
        
        pygame.display.update()
        time.sleep(0.05)

if __name__ == "__main__":
    main()
    