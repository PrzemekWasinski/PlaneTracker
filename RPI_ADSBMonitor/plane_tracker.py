#!/usr/bin/env python3

import socket
import time
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db
import pygame
from pygame.locals import *
from time import gmtime, strftime
import psutil
import os
import threading
import gc 
import queue
import requests
import math
import re
from functions import restart_script, connect, coords_to_xy, split_message, clean_string

if not firebase_admin._apps: #Initialise Firebase
    cred = credentials.Certificate("./rpi-flight-tracker-firebase-adminsdk-fbsvc-a6afd2b5b0.json")
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app"
    })

SERVER_SBS = ("localhost", 30003) #ADSB port

pygame.init()
run = False #Initialize as False until we check Firebase

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

# Event to control the data collection thread
tracker_running_event = threading.Event()

def draw_text(text, font, text_col, x, y):
    img = font.render(text, True, text_col)
    window.blit(img, (x, y))

def draw_text_centered(text, font, rgb_val, x, y):
    img = font.render(text, True, rgb_val)
    rect = img.get_rect(center=(x, y))
    window.blit(img, rect)

def draw_fading_text(text, font, rgb_val, x, y, alpha):
    img = font.render(text, True, rgb_val)
    img.set_alpha(alpha)
    rect = img.get_rect(center=(x, y))
    window.blit(img, rect)

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
            #Set default value if not found
            ref.update({"run": run})
            if run:
                tracker_running_event.set()
            else:
                tracker_running_event.clear()
    except Exception as error:
        print(f"Firebase error checking run status: {error}")
    
    return run

def firebase_watcher(): #Keep checking Firebase if run is true
    global run
    while True:
        prev_run_state = run
        current_run_state = check_run_status()
        
        if prev_run_state != current_run_state:
            if current_run_state:
                message_queue.put("Tracker activated - Starting data collection")
                print("Tracker activated via Firebase")
            else:
                message_queue.put("Tracker paused via Firebase")
                print("Tracker paused via Firebase")
        
        time.sleep(3) #Check every 3 seconds

def collect_and_process_data():
    global active_planes, displayed_planes, is_receiving, is_processing, cpu_temp, ram_percentage

    while True:
        #Wait until the tracker is set to running
        tracker_running_event.wait()
        
        collected_messages = []
        is_receiving = True
        
        print("Collecting ADSB data for 1 second...")
        sock = connect(SERVER_SBS)
        sock.settimeout(0.1)
        
        buffer = ""
        end_time = time.time() + 1.0  
        
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
            print(f"Processing {len(collected_messages)} ADSB messages")
            
            #Group by ICAO code to avoid processing the same plane multiple times
            planes_by_icao = {}
            for plane_data in collected_messages:
                planes_by_icao[plane_data['icao']] = plane_data
                
            for icao, plane_data in planes_by_icao.items():
                if not tracker_running_event.is_set():
                    print("Tracker paused during processing")
                    is_processing = False
                    break
                #Only process the planes that have coordinates
                try:
                    #Call API to get aircraft details
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
                            
                        plane_data["manufacturer"] = manufacturer
                        plane_data["registration"] = registration
                        plane_data["icao_type_code"] = clean_string(str(api_data.get("ICAOTypeCode", "-")))
                        plane_data["code_mode_s"] = clean_string(str(api_data.get("ModeS", "-")))
                        plane_data["operator_flag"] = clean_string(str(api_data.get("OperatorFlagCode", "-")))
                        plane_data["owner"] = owner
                        plane_data["model"] = model
                        
                        message_queue.put(f"{manufacturer} {model}")
                except Exception as e:
                    print(f"API error for {icao}: {e}")
                    
                lat = plane_data.get("lat")
                lon = plane_data.get("lon")
                
                if lat not in [None, "-", ""] and lon not in [None, "-", ""]:
                    plane_data["last_lat"] = float(lat)
                    plane_data["last_lon"] = float(lon)
                    current_time = time.time()
                    plane_data["last_update_time"] = current_time
                    
                    displayed_planes[icao] = {
                        "plane_data": plane_data,
                        "display_until": current_time + display_duration
                    }
                
                active_planes[icao] = plane_data
                
                #Upload to Firebase
                try:
                    today = datetime.today().strftime("%Y-%m-%d")
                    manufacturer = plane_data.get("manufacturer", "-")
                    model = plane_data.get("model", "-")
                    registration = plane_data.get("registration", "-")
                    owner = plane_data.get("owner", "-")
                    
                    if manufacturer != "-" and model != "-" and registration != "-" and owner != "-":
                        ref = db.reference(f"{today}/{manufacturer} {model} ({registration}) {owner}")
                        
                        current_data = ref.get()
                        if current_data is None:
                            plane_data["location_history"] = {}
                            ref.set(plane_data)
                        else:
                            location_history = current_data.get("location_history", {})
                            
                            if plane_data["lat"] != "-" and plane_data["lon"] != "-":
                                location_history[plane_data["spotted_at"]] = [plane_data["lat"], plane_data["lon"]]
                                plane_data["location_history"] = location_history
                            else:
                                plane_data["location_history"] = location_history
                                
                            new_data = {}
                            for key, value in plane_data.items():
                                if key in ["last_update_time"]:  
                                    continue
                                current_value = current_data.get(key)
                                if value == "-" or value == []:
                                    new_data[key] = current_value
                                else:
                                    new_data[key] = value
                            ref.set(new_data)
                except Exception as e:
                    print(f"Firebase upload error for {icao}: {e}")
            
            #Update device stats only if run is true
            if tracker_running_event.is_set():
                try:
                    stats_ref = db.reference("device_stats")
                    stats_ref.update({
                        "cpu_temp": cpu_temp,
                        "ram_percentage": ram_percentage,
                        "run": run
                    })
                except Exception as e:
                    print(f"Error updating device stats: {e}")
                
            is_processing = False
            if tracker_running_event.is_set():
                print("Processing complete")
            
        #Clean up expired planes from display 
        current_time = time.time()
        for icao in list(displayed_planes.keys()):
            if displayed_planes[icao]["display_until"] < current_time:
                del displayed_planes[icao]

        time.sleep(0.1)

def start_data_cycle():
    #Start the Firebase watching thread
    watcher_thread = threading.Thread(target=firebase_watcher, daemon=True)
    watcher_thread.start()
    
    #Start the data collection thread
    data_thread = threading.Thread(target=collect_and_process_data, daemon=True)
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

#Load images
image1 = pygame.image.load(os.path.join("textures", "icons", "open_menu.png"))
image2 = pygame.image.load(os.path.join("textures", "icons", "close_menu.png"))
image3 = pygame.image.load(os.path.join("textures", "icons", "zoom_in.png"))
image4 = pygame.image.load(os.path.join("textures", "icons", "zoom_out.png"))
image5 = pygame.image.load(os.path.join("textures", "icons", "pause.png"))
image6 = pygame.image.load(os.path.join("textures", "icons", "resume.png"))
image7 = pygame.image.load(os.path.join("textures", "icons", "off.png"))

open_menu_image = image1.get_rect(center=(765, 240))
close_menu_image = image2.get_rect(center=(550, 240))
zoom_in_image = image3.get_rect(topleft=(585, 415))
zoom_out_image = image4.get_rect(topleft=(635, 415))
pause_image = image5.get_rect(topleft=(685, 415))
resume_image = image6.get_rect(topleft=(685, 415))
off_image = image7.get_rect(topleft=(735, 415))

def main():
    global cpu_temp
    global ram_percentage
    global run
    start_time = time.time()

    #Check run status and start threads
    check_run_status()
    start_data_cycle()

    last_update_time = time.time()
    menu_open = False
    range = 50  
    display_incomplete = False  

    while True:
        if time.time() - start_time > 1800: #Reset tracker every 30min 
            print("Restarting plane tracker...")
            restart_script()

        ram_percentage = psutil.virtual_memory()[2] #Get RAM usage

        with open("/sys/class/thermal/thermal_zone0/temp", "r") as temp: #Get CPU temp
            cpu_temp = int(temp.read()) / 1000 

        mouse_x, mouse_y = pygame.mouse.get_pos() #Get mouse position

        pygame.draw.rect(window, (65, 65, 65), (0, 0, width, height)) #Draw radar display

        pygame.draw.circle(window, (255, 255, 255), (400, 240), 100, 1)
        pygame.draw.circle(window, (255, 255, 255), (400, 240), 200, 1)
        pygame.draw.circle(window, (255, 255, 255), (400, 240), 300, 1)
        pygame.draw.circle(window, (255, 255, 255), (400, 240), 400, 1)

        draw_text(str(round(range * 0.25)), text_font3, (255, 255, 255), 305, 235)
        draw_text(str(round(range * 0.5)), text_font3, (255, 255, 255), 205, 235)
        draw_text(str(round(range * 0.75)), text_font3, (255, 255, 255), 105, 235)
        draw_text(str(round(range)), text_font3, (255, 255, 255), 5, 235) 

        pygame.draw.polygon(window, (0, 255, 255), [(400, 238), (402, 240), (400, 242), (398, 240)])  

        for event in pygame.event.get(): #Listen for events
            if event.type == pygame.QUIT: #Quit event
                pygame.quit()
                exit()
            elif event.type == MOUSEBUTTONDOWN: #Listen for mouse clicks
                if mouse_x > 755 and mouse_y > 230 and mouse_x < 795 and mouse_y < 260 and not menu_open: #Open menu button
                    menu_open = True
                elif mouse_x > 540 and mouse_y > 230 and mouse_x < 570 and mouse_y < 260 and menu_open: #Close menu button
                    menu_open = False
                if menu_open: #Menu buttons
                    if mouse_x > 585 and mouse_y > 415 and mouse_x < 625 and mouse_y < 455 and range > 25: #Decrease range button
                        range -= 25
                    elif mouse_x > 635 and mouse_y > 415 and mouse_x < 675 and mouse_y < 455 and range < 400: #Increase range button
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
        
        #Draw all planes that should be displayed
        for icao, display_data in list(displayed_planes.items()):
            plane = display_data["plane_data"]
            
            lat = plane.get("last_lat")
            lon = plane.get("last_lon")
            
            #Skip planes without coordinates 
            if lat is None or lon is None:
                continue
                
            potential_count += 1
            
            #Check if we have complete information 
            owner = plane.get("owner", "-") 
            model = plane.get('model', '-')
            manufacturer = plane.get('manufacturer', '-')
            
            if not display_incomplete and (owner == "-" or model == "-" or manufacturer == "-"):
                continue
                
            displayed_count += 1
            
            #Calculate fade based on time remaining
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

                temp_surface = pygame.Surface((10, 10), pygame.SRCALPHA)
                temp_surface.fill((0, 0, 0, 0)) 
                pygame.draw.polygon(temp_surface, (*rgb_value, fade_value), [(5, 3), (7, 5), (5, 7), (3, 5)])
                window.blit(temp_surface, (x-5, y-5))

                draw_fading_text(owner_text, text_font3, (255, 255, 255), x, y - 9, fade_value)
                draw_fading_text(plane_string, text_font3, (255, 255, 255), x, y + 9, fade_value)
            except Exception as error:
                print(f"Drawing error for {icao}: {error}")
        
        if menu_open: #Draw the menu
            current_time = strftime("%H:%M:%S", gmtime())   

            pygame.draw.rect(window, (0, 0, 0), (570, 10, 220, 460), 0, 5)

            draw_text_centered(current_time, text_font2, (255, 0, 0), 675, 40)
            draw_text_centered(f"CPU:{str(round(cpu_temp))}°C  RAM:{str(ram_percentage)}%", text_font1, (255, 255, 255), 675, 75)

            #Show status 
            if is_receiving:
                status = "Receiving"
            elif is_processing:
                status = "Processing"
            else:
                status = "Idle"
            
            draw_text_centered(f"Status: {status}", text_font1, (255, 255, 0), 675, 100)
            draw_text_centered(f"Displaying: {displayed_count}", text_font1, (255, 255, 0), 675, 125)

            pygame.draw.rect(window, (255, 255, 255), (580, 145, 200, 250), 2)

            y = 149
            for i, message in enumerate(display_messages[-24:]): 
                draw_text(str(message), text_font3, (255, 255, 255), 585, y)
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

        pygame.display.update()

        if time.time() - last_update_time > 10: #Clean up garbage
            gc.collect()
            last_update_time = time.time()

        time.sleep(0.05)

if __name__ == "__main__":
    main()