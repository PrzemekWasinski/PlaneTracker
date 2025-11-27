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
import gc
import queue
import requests
import csv
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from functions import restart_script, connect, coords_to_xy, split_message, clean_string, get_stats, calculate_heading
from draw import draw_text, draw_fading_text, draw_text_centered
from airport_db import airports_uk

if not firebase_admin._apps: #Initialise Firebase
    cred = credentials.Certificate("./firebase.json")
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app"
    })

SERVER_SBS = ("localhost", 30003) #ADSB port

pygame.init()
pygame.mouse.set_visible(False)
run = False #Initialize as False until we check Firebase
map = False

width = 800 #Display dimensions
height = 480
window = pygame.display.set_mode((width, height), pygame.FULLSCREEN)

text_font1 = pygame.font.Font(os.path.join("textures", "NaturalMono-Bold.ttf"), 16) #Fonts
text_font2 = pygame.font.Font(os.path.join("textures", "DS-DIGI.TTF"), 40)
text_font3 = pygame.font.Font(os.path.join("textures", "NaturalMono-Bold.ttf"), 9)

active_planes = {} #Stores all recently detected planes
displayed_planes = {} #Planes that should be drawn with fading effect

message_queue = queue.Queue(maxsize=20) #Messages that will be displayed in the menu
display_messages = []

is_receiving = False
is_processing = False

display_duration = 30
fade_duration = 10    

tracker_running_event = threading.Event()

device_stats_cache = { #Cache
    "cpu_temp": 0,
    "ram_percentage": 0,
    "run": False,
    "last_upload": 0
}
DEVICE_STATS_UPDATE_INTERVAL = 30  # Update device stats every 30 seconds instead of every cycle

def check_run_status():
    global run
    try:
        ref = db.reference("device_stats")
        data = ref.get()
        if data is not None and "run" in data:
            run = data["run"]
            if run:
                tracker_running_event.set()
            else:
                tracker_running_event.clear()
        else:
            ref.update({"run": run})
            if run:
                tracker_running_event.set()
            else:
                tracker_running_event.clear()
    except Exception as error:
        print(f"Firebase error checking run status: {error}")
    
    return run

def fetch_plane_api_data(icao):
    """Fetch plane metadata from API for a single ICAO code"""
    try:
        url = f"https://hexdb.io/api/v1/aircraft/{icao}"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            api_data = response.json()
            manufacturer = clean_string(str(api_data.get("Manufacturer", "-")))
            registration = clean_string(str(api_data.get("Registration", "-")))
            owner = clean_string(str(api_data.get("RegisteredOwners", "-")))
            model = clean_string(str(api_data.get("Type", "-")))

            if manufacturer == "Avions de Transport Regional":
                manufacturer = "ATR"
            elif manufacturer == "Honda Aircraft Company":
                manufacturer = "Honda"

            return {
                "icao": icao,
                "manufacturer": manufacturer,
                "registration": registration,
                "icao_type_code": clean_string(str(api_data.get("ICAOTypeCode", "-"))),
                "code_mode_s": clean_string(str(api_data.get("ModeS", "-"))),
                "operator_flag": clean_string(str(api_data.get("OperatorFlagCode", "-"))),
                "owner": owner,
                "model": model,
                "success": True
            }
    except Exception as e:
        print(f"API error for {icao}: {e}")

    return {"icao": icao, "success": False}

def firebase_watcher(): #Keep checking Firebase if run is true
    global run
    while True:
        prev_run_state = run
        current_run_state = check_run_status()

        if prev_run_state != current_run_state:
            if current_run_state:
                message_queue.put("Tracker activated - Starting data collection")
            else:
                message_queue.put("Tracker paused via Firebase")

        time.sleep(5) #Check every 5 seconds 

def collect_and_process_data():
    global active_planes, displayed_planes, is_receiving, is_processing, cpu_temp, ram_percentage
    
    firebase_batch = []
    BATCH_SIZE = 10  # Upload every 10 planes
    last_batch_upload = time.time()
    BATCH_TIMEOUT = 10  # Upload batch if 10 seconds passed

    while True:
        tracker_running_event.wait()
        
        collected_messages = []
        is_receiving = True
        
        message_queue.put("Collecting ADSB data for 1 seconds")
        sock = connect(SERVER_SBS)
        sock.settimeout(0.1)
        
        buffer = ""
        end_time = time.time() + 1
        
        try:
            while time.time() < end_time and tracker_running_event.is_set():
                try:
                    data = sock.recv(1024)
                    if not data:
                        print("ADSB Server disconnected")
                        break
                    
                    buffer += data.decode(errors="ignore")
                    messages = buffer.split("\n")
                    buffer = messages.pop()
                    
                    for message in messages:
                        plane_data = split_message(message)
                        if plane_data:
                            if plane_data["lon"] != "-" and plane_data["lat"] != "-":
                                collected_messages.append(plane_data)
                            
                except socket.timeout:
                    continue  
                    
        except Exception as error:
            print(f"Data collection error: {error}")
        finally:
            sock.close()
            is_receiving = False
            
        #If paused skip processing
        if not tracker_running_event.is_set():
            print("Tracker paused during data collection")
            time.sleep(1)
            continue
            
        if collected_messages:
            is_processing = True
            processing_start_time = time.time()
            message_queue.put(f"Processing {len(collected_messages)} ADSB messages")

            #Group by ICAO code to avoid processing the same plane multiple times
            planes_by_icao = {}
            for plane_data in collected_messages:
                planes_by_icao[plane_data['icao']] = plane_data

            # Identify which planes need API calls
            icaos_needing_api = []
            for icao, plane_data in planes_by_icao.items():
                cached_plane = active_planes.get(icao)
                if not (cached_plane and cached_plane.get("manufacturer") != "-" and cached_plane.get("model") != "-"):
                    icaos_needing_api.append(icao)
                else:
                    # Use cached data immediately
                    plane_data["manufacturer"] = cached_plane["manufacturer"]
                    plane_data["registration"] = cached_plane["registration"]
                    plane_data["icao_type_code"] = cached_plane["icao_type_code"]
                    plane_data["code_mode_s"] = cached_plane["code_mode_s"]
                    plane_data["operator_flag"] = cached_plane["operator_flag"]
                    plane_data["owner"] = cached_plane["owner"]
                    plane_data["model"] = cached_plane["model"]

            # Fetch all new planes in parallel
            api_results = {}
            if icaos_needing_api:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    future_to_icao = {executor.submit(fetch_plane_api_data, icao): icao for icao in icaos_needing_api}
                    for future in as_completed(future_to_icao):
                        result = future.result()
                        if result["success"]:
                            api_results[result["icao"]] = result
                            message_queue.put(f"New: {result['manufacturer']} {result['model']}")

            # Apply API results to plane data
            for icao in icaos_needing_api:
                if icao in api_results:
                    result = api_results[icao]
                    plane_data = planes_by_icao[icao]
                    plane_data["manufacturer"] = result["manufacturer"]
                    plane_data["registration"] = result["registration"]
                    plane_data["icao_type_code"] = result["icao_type_code"]
                    plane_data["code_mode_s"] = result["code_mode_s"]
                    plane_data["operator_flag"] = result["operator_flag"]
                    plane_data["owner"] = result["owner"]
                    plane_data["model"] = result["model"]

            # Process all planes for display and update active_planes
            csv_updates = []
            for icao, plane_data in planes_by_icao.items():
                if not tracker_running_event.is_set():
                    message_queue.put("Tracker paused during processing")
                    is_processing = False
                    break

                lat = plane_data.get("lat")
                lon = plane_data.get("lon")

                if lat not in [None, "-", ""] and lon not in [None, "-", ""]:
                    previous_plane_data = active_planes.get(icao)
                    if previous_plane_data and "last_lat" in previous_plane_data and "last_lon" in previous_plane_data:
                        plane_data["prev_lat"] = previous_plane_data["last_lat"]
                        plane_data["prev_lon"] = previous_plane_data["last_lon"]

                    plane_data["last_lat"] = float(lat)
                    plane_data["last_lon"] = float(lon)
                    current_time = time.time()
                    plane_data["last_update_time"] = current_time

                    displayed_planes[icao] = {
                        "plane_data": plane_data,
                        "display_until": current_time + display_duration
                    }

                active_planes[icao] = plane_data
                csv_updates.append((icao, plane_data))

            # Batch CSV write - do all planes at once
            if csv_updates:
                try: #Save to CSV locally
                    today = datetime.today().strftime("%Y-%m-%d")
                    stats_dir = './stats_history'
                    csv_path = os.path.join(stats_dir, f'{today}.csv')

                    os.makedirs(stats_dir, exist_ok=True)

                    # Read existing CSV once
                    existing_rows = []
                    existing_by_icao = {}
                    if os.path.exists(csv_path):
                        try:
                            with open(csv_path, 'r', newline='', encoding='utf-8') as file:
                                reader = csv.DictReader(file)
                                for row in reader:
                                    if row.get('icao'):
                                        existing_rows.append(row)
                                        existing_by_icao[row['icao']] = row
                        except (FileNotFoundError, PermissionError, csv.Error):
                            existing_rows = []
                            existing_by_icao = {}

                    # Update/add all planes in one go
                    for icao, plane_data in csv_updates:
                        manufacturer = plane_data.get('manufacturer', '').strip()
                        model = plane_data.get('model', '').strip()
                        full_model = f"{manufacturer} {model}".strip()
                        altitude = plane_data.get("altitude")

                        # Build location history from existing data
                        location_history = {}
                        if icao in existing_by_icao:
                            existing_history = existing_by_icao[icao].get('location_history', '{}')
                            if existing_history and existing_history != '{}':
                                try:
                                    import ast
                                    location_history = ast.literal_eval(existing_history)
                                except:
                                    location_history = {}

                        if plane_data["lat"] != "-" and plane_data["lon"] != "-":
                            location_history[plane_data["spotted_at"]] = [plane_data["lat"], plane_data["lon"]]

                        row_data = {
                            "icao": icao,
                            "manufacturer": manufacturer,
                            "model": model,
                            "full_model": full_model,
                            "airline": plane_data.get("owner", "").strip(),
                            "location_history": str(location_history),
                            "altitude": altitude,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }

                        # Update existing or append new
                        if icao in existing_by_icao:
                            for i, existing_row in enumerate(existing_rows):
                                if existing_row.get('icao') == icao:
                                    existing_rows[i] = row_data
                                    break
                        else:
                            existing_rows.append(row_data)
                        existing_by_icao[icao] = row_data

                    # Write CSV once for all planes
                    temp_file = None
                    try:
                        with tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8", dir=stats_dir, delete=False) as temp_file:
                            temp_path = temp_file.name
                            fieldnames = [
                                "icao",
                                "manufacturer",
                                "model",
                                "full_model",
                                "airline",
                                "location_history",
                                "altitude",
                                "timestamp",
                            ]
                            writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
                            writer.writeheader()
                            writer.writerows(existing_rows)

                        shutil.move(temp_path, csv_path)

                    except Exception as e:
                        if temp_file:
                            try:
                                os.unlink(temp_file.name)
                            except Exception:
                                pass
                        print(f"Error saving plane data: {e}")
                except Exception as e:
                    print(f"CSV save error: {e}")

            # Prepare Firebase batch for all planes
            for icao, plane_data in planes_by_icao.items():
                manufacturer = plane_data.get("manufacturer", "-")
                model = plane_data.get("model", "-")
                registration = plane_data.get("registration", "-")
                owner = plane_data.get("owner", "-")

                if manufacturer != "-" and model != "-" and registration != "-" and owner != "-":
                    firebase_data = {key: value for key, value in plane_data.items()
                                   if key not in ["location_history", "last_update_time", "last_lat", "last_lon"]}

                    min = strftime("%M", localtime())
                    hour = strftime("%H", localtime())
                    time_10 = f"{hour}:{min[:-1] + '0'}"
                    today = datetime.today().strftime("%Y-%m-%d")

                    firebase_batch.append({
                        "path": f"{today}/{time_10}/{manufacturer}-{model}-({registration})-{owner}",
                        "data": firebase_data
                    })
            
            current_time = time.time()
            if len(firebase_batch) >= BATCH_SIZE or (firebase_batch and current_time - last_batch_upload > BATCH_TIMEOUT):
                try:
                    for item in firebase_batch:
                        ref = db.reference(item["path"])
                        current_data = ref.get()
                        
                        if current_data is None:
                            ref.set(item["data"])
                        else:
                            new_data = {}
                            for key, value in item["data"].items():
                                current_value = current_data.get(key)
                                if value == "-" or value == []:
                                    new_data[key] = current_value
                                else:
                                    new_data[key] = value
                            ref.update(new_data)
                    
                    message_queue.put(f"Uploaded {len(firebase_batch)} planes to Firebase")
                    firebase_batch = []
                    last_batch_upload = current_time
                except Exception as e:
                    print(f"Firebase batch upload error: {e}")
                    firebase_batch = []
            
            if tracker_running_event.is_set():
                device_stats_cache["cpu_temp"] = cpu_temp
                device_stats_cache["ram_percentage"] = ram_percentage
                device_stats_cache["run"] = run
                
                if current_time - device_stats_cache["last_upload"] > DEVICE_STATS_UPDATE_INTERVAL:
                    try:
                        stats_ref = db.reference("device_stats")
                        stats_ref.update({
                            "cpu_temp": device_stats_cache["cpu_temp"],
                            "ram_percentage": device_stats_cache["ram_percentage"],
                            "run": device_stats_cache["run"]
                        })
                        device_stats_cache["last_upload"] = current_time
                    except Exception as e:
                        print(f"Error updating device stats: {e}")
                
            is_processing = False
            if tracker_running_event.is_set():
                processing_duration = time.time() - processing_start_time
                message_queue.put(f"Processing complete ({processing_duration:.3f}s)")
            
        current_time = time.time()#Clean up expired planes from display 
        for icao in list(displayed_planes.keys()):
            if displayed_planes[icao]["display_until"] < current_time:
                del displayed_planes[icao]

        time.sleep(0.1)

def start_data_cycle():
    watcher_thread = threading.Thread(target=firebase_watcher, daemon=True) #Start the Firebase watching thread
    watcher_thread.start()
    
    data_thread = threading.Thread(target=collect_and_process_data, daemon=True) #Start the data collection thread
    data_thread.start()

def process_message_queue():
    global display_messages
    
    while not message_queue.empty():
        try:
            message = message_queue.get(block=False)
            display_messages.append(message)
            message_queue.task_done()
        except queue.Empty:
            break
    
    if len(display_messages) > 24:
        display_messages = display_messages[-24:]

image1 = pygame.image.load(os.path.join("textures", "icons", "open_menu.png"))
image2 = pygame.image.load(os.path.join("textures", "icons", "close_menu.png"))
image3 = pygame.image.load(os.path.join("textures", "icons", "zoom_in.png"))
image4 = pygame.image.load(os.path.join("textures", "icons", "zoom_out.png"))
image5 = pygame.image.load(os.path.join("textures", "icons", "pause.png"))
image6 = pygame.image.load(os.path.join("textures", "icons", "resume.png"))
image7 = pygame.image.load(os.path.join("textures", "icons", "off.png"))
plane_icon = pygame.image.load(os.path.join("textures", "icons", "plane.png")).convert_alpha()
dot_icon = pygame.image.load(os.path.join("textures", "icons", "dot.png")).convert_alpha()

image8 = pygame.image.load(os.path.join("textures", "images", "25.png"))
image9 = pygame.image.load(os.path.join("textures", "images", "50.png"))
image10 = pygame.image.load(os.path.join("textures", "images", "75.png"))
image11 = pygame.image.load(os.path.join("textures", "images", "100.png"))
image12 = pygame.image.load(os.path.join("textures", "images", "125.png"))
image13 = pygame.image.load(os.path.join("textures", "images", "150.png"))
image14 = pygame.image.load(os.path.join("textures", "images", "175.png"))
image15 = pygame.image.load(os.path.join("textures", "images", "200.png"))
image16 = pygame.image.load(os.path.join("textures", "images", "225.png"))
image17 = pygame.image.load(os.path.join("textures", "images", "250.png"))

open_menu_image = image1.get_rect(center=(765, 240))
close_menu_image = image2.get_rect(center=(550, 240))
zoom_in_image = image3.get_rect(topleft=(585, 415))
zoom_out_image = image4.get_rect(topleft=(635, 415))
pause_image = image5.get_rect(topleft=(685, 415))
resume_image = image6.get_rect(topleft=(685, 415))
off_image = image7.get_rect(topleft=(735, 415))

map_25km = image8.get_rect(topleft=(0, 0))
map_50km = image9.get_rect(topleft=(0, 0))
map_75km = image10.get_rect(topleft=(0, 0))
map_100km = image11.get_rect(topleft=(0, 0))
map_125km = image12.get_rect(topleft=(0, 0))
map_150km = image13.get_rect(topleft=(0, 0))
map_175km = image14.get_rect(topleft=(0, 0))
map_200km = image15.get_rect(topleft=(0, 0))
map_225km = image16.get_rect(topleft=(0, 0))
map_250km = image17.get_rect(topleft=(0, 0))

def main():
    global cpu_temp
    global ram_percentage
    global run

    start_time = time.time()
    update_time = time.time()
    last_tap_time = time.time()

    #Check run status and start threads
    check_run_status()
    start_data_cycle()

    last_update_time = time.time()
    menu_open = False
    range = 50  
    display_incomplete = False  

    while True:
        current_time = time.time()

        if current_time - start_time > 1800: #Reset tracker every 30min and upload todays stats to firebase
            print("Restarting plane tracker...")
            restart_script()

        if current_time - update_time > 60: #Update stats every 1 min
            today = datetime.today().strftime("%Y-%m-%d")
            ref = db.reference(f"{today}/stats")
            ref.set(get_stats())
            update_time = time.time()

        ram_percentage = psutil.virtual_memory()[2] #Get RAM usage

        with open("/sys/class/thermal/thermal_zone0/temp", "r") as temp: #Get CPU temp
            cpu_temp = int(temp.read()) / 1000 

        mouse_x, mouse_y = pygame.mouse.get_pos() #Get mouse position 

        for event in pygame.event.get(): #Listen for events
            if event.type == pygame.QUIT: #Quit event
                pygame.quit()
                exit()
            elif event.type == MOUSEBUTTONDOWN: #Listen for mouse clicks
                last_tap_time = time.time()
                if mouse_x > 755 and mouse_y > 230 and mouse_x < 795 and mouse_y < 260 and not menu_open: #Open menu button
                    menu_open = True
                elif mouse_x > 540 and mouse_y > 230 and mouse_x < 570 and mouse_y < 260 and menu_open: #Close menu button
                    menu_open = False
                if menu_open: #Menu buttons
                    if mouse_x > 585 and mouse_y > 415 and mouse_x < 625 and mouse_y < 455 and range > 25: #Decrease range button
                        range -= 25
                    elif mouse_x > 635 and mouse_y > 415 and mouse_x < 675 and mouse_y < 455 and range < 250: #Increase range button
                        range += 25
                    elif mouse_x > 685 and mouse_y > 415 and mouse_x < 725 and mouse_y < 455: #Pause/resume button
                        run = not run 
                        if run:
                            tracker_running_event.set()
                            message_queue.put("Tracker activated via UI")
                        else:
                            tracker_running_event.clear()
                            message_queue.put("Tracker paused via UI")
                            
                        ref = db.reference("device_stats")
                        ref.update({"run": run})
                        
                    elif mouse_x > 735 and mouse_y > 415 and mouse_x < 775 and mouse_y < 455:  #Quit button
                        run = False 
                        tracker_running_event.clear()
                        ref = db.reference("device_stats")
                        ref.update({"run": run})
                        pygame.quit()
                        exit()

        process_message_queue() #Handle messages   

        current_time = time.time()
    
        displayed_count = 0
        potential_count = 0
        
        #Draw all planes 
        if current_time - last_tap_time < 180: #Enable scrren saver after 3 minutes of inactivity to prevent burn ins
            pygame.draw.rect(window, (0, 0, 0), (0, 0, width, height)) #Draw radar display

            if map:
                if range == 25:
                    window.blit(image8, (map_25km))
                elif range == 50:
                    window.blit(image9, (map_50km))
                elif range == 75:
                    window.blit(image10, (map_75km))
                elif range == 100:
                    window.blit(image11, (map_100km))
                elif range == 125:
                    window.blit(image12, (map_125km))
                elif range == 150:
                    window.blit(image13, (map_150km))
                elif range == 175:
                    window.blit(image14, (map_175km))
                elif range == 200:
                    window.blit(image15, (map_200km))
                elif range == 225:
                    window.blit(image16, (map_225km))
                elif range == 250:
                    window.blit(image17, (map_250km))
            else: 
                pygame.draw.rect(window, (0, 0, 0), (0, 0, width, height))

            pygame.draw.circle(window, (225, 225, 225), (400, 240), 100, 1)
            pygame.draw.circle(window, (225, 225, 225), (400, 240), 200, 1)
            pygame.draw.circle(window, (225, 225, 225), (400, 240), 300, 1)
            pygame.draw.circle(window, (225, 225, 225), (400, 240), 400, 1)

            draw_text(window, str(round(range * 0.25)), text_font3, (225, 225, 225), 305, 235)
            draw_text(window, str(round(range * 0.5)), text_font3, (225, 225, 225), 205, 235)
            draw_text(window, str(round(range * 0.75)), text_font3, (225, 225, 225), 105, 235)
            draw_text(window, str(round(range)), text_font3, (225, 225, 225), 5, 235) 
           
            if not map:
                pygame.draw.polygon(window, (0, 255, 255), [(400, 238), (402, 240), (400, 242), (398, 240)]) 

            for key in airports_uk:
                airport = airports_uk[key]
                x, y = coords_to_xy(airport["lat"], airport["lon"], range)
                pygame.draw.polygon(window, (0, 0, 255), [(x, y - 2), (x + 2, y), (x, y + 2), (x - 2, y)]) 
                draw_text_centered(window, airport["airport_name"], text_font3, (255, 255, 255), x, y - 10)

            for icao, display_data in list(displayed_planes.items()):
                plane = display_data["plane_data"]
                
                lat = plane.get("last_lat")
                lon = plane.get("last_lon")
                prev_lat = plane.get("prev_lat")
                prev_lon = plane.get("prev_lon")

                if lat is None or lon is None:
                    continue
                    
                potential_count += 1
                
                owner = plane.get("owner", "-") 
                model = plane.get('model', '-')
                manufacturer = plane.get('manufacturer', '-')
                
                if not display_incomplete and (owner == "-" or model == "-" or manufacturer == "-"):
                    continue
                    
                displayed_count += 1
                
                time_remaining = display_data["display_until"] - current_time
                if time_remaining <= 0:
                    continue  
                    
                fade_value = 255
                if time_remaining < fade_duration:
                    fade_value = int(255 * (time_remaining / fade_duration))
                    if fade_value < 10: 
                        fade_value = 10
                
                #Set plane rgb_val
                if "Air Force" in owner or "Navy" in owner: #Highlights military planes in red
                    rgb_value = (255, 0, 0)
                elif "747" in model or "340" in model: #Highlights A340s and 747s in purple because theyre my favourite
                    rgb_value = (255, 0, 255)
                else:
                    rgb_value = (255, 255, 255)

                try: #Draw plane on the radar with fading effect
                    plane_string = f"{manufacturer or '-'} {model or '-'}"
                    owner_text = owner or "Unknown"
                    x, y = coords_to_xy(float(lat), float(lon), range)

                    # If we have previous coordinates, draw rotated plane, otherwise a dot
                    if prev_lat is not None and prev_lon is not None:
                        heading = calculate_heading(prev_lat, prev_lon, lat, lon)
                        
                        # Create a copy of the icon to color it
                        colored_icon = plane_icon.copy()
                        colored_icon.fill(rgb_value, special_flags=pygame.BLEND_RGB_MULT)
                        colored_icon.set_alpha(fade_value)
                        
                        rotated_image = pygame.transform.rotate(colored_icon, heading)
                        new_rect = rotated_image.get_rect(center=(x, y))
                        window.blit(rotated_image, new_rect)
                    else:
                        # Draw a yellow dot for planes with no heading info yet
                        dot_icon_copy = dot_icon.copy()
                        dot_icon_copy.set_alpha(fade_value)
                        new_rect = dot_icon_copy.get_rect(center=(x, y))
                        window.blit(dot_icon_copy, new_rect)
                        
                    draw_fading_text(window, owner_text, text_font3, (255, 202, 0), x, y - 13, fade_value)
                    draw_fading_text(window, plane_string, text_font3, (255, 202, 0), x, y + 13, fade_value)
                except Exception as error:
                    print(f"Drawing error for {icao}: {error}")
            
            if menu_open: #Draw the menu
                current_time = strftime("%H:%M:%S", localtime())   

                pygame.draw.rect(window, (0, 0, 0), (570, 10, 220, 460), 0, 5)

                draw_text_centered(window, current_time, text_font2, (255, 0, 0), 675, 40)
                draw_text_centered(window, f"CPU:{str(round(cpu_temp))}°C  RAM:{str(ram_percentage)}%", text_font1, (255, 255, 255), 675, 75)

                #Show status 
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
                elif displayed_count >= 20:
                    display_rgb = (0, 255, 0)
                
                draw_text_centered(window, f"Status: {status}", text_font1, (255, 255, 255), 675, 100)
                draw_text_centered(window, f"Active: {displayed_count}", text_font1, display_rgb, 675, 125)

                pygame.draw.rect(window, (255, 255, 255), (580, 145, 200, 250), 2)

                y = 149
                for i, message in enumerate(display_messages[-24:]): 
                    draw_text(window, str(message), text_font3, (255, 255, 255), 585, y)
                    y += 10

                window.blit(image2, (close_menu_image))
                window.blit(image3, (zoom_in_image))
                window.blit(image4, (zoom_out_image))
                window.blit(image7, (off_image))

                if run:
                    window.blit(image5, (pause_image))
                else:
                    window.blit(image6, (resume_image))
                
            else:
                window.blit(image1, (open_menu_image))
        else:
            pygame.draw.rect(window, (0, 0, 0), (0, 0, width, height)) #Make screen fully black

        pygame.display.update()

        if time.time() - last_update_time > 10: #Clean up garbage
            gc.collect()
            last_update_time = time.time()

        time.sleep(0.05)

if __name__ == "__main__":
    main()