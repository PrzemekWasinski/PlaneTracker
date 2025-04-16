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
from functions import restart_script, connect, split_message, upload_data, coords_to_xy

if not firebase_admin._apps:
    cred = credentials.Certificate("./rpi-flight-tracker-firebase-adminsdk-fbsvc-a6afd2b5b0.json")
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app"
    })

SERVER_SBS = ("localhost", 30003)

pygame.init()

width = 800
height = 480
run = True

window = pygame.display.set_mode((width, height), pygame.FULLSCREEN)

text_font1 = pygame.font.Font(os.path.join("textures", "DS-DIGI.TTF"), 50)
text_font2 = pygame.font.Font(os.path.join("textures", "DS-DIGI.TTF"), 40)
text_font3 = pygame.font.Font(os.path.join("textures", "NaturalMono-Bold.ttf"), 9)

active_planes = {}

message_queue = queue.Queue(maxsize=20)
display_messages = []
plane_stats = {
    "Boeing": 0, 
    "Airbus": 0, 
    "Embraer": 0,
    "ATR": 0,
    "Lockheed Martin": 0,
    "Bombardier": 0,
    "Gulfstream": 0,
    "Cessna": 0,
    "Piper": 0,
    "Other": 0,
    "Total": 0
}

upload_threads = []
MAX_UPLOAD_THREADS = 5

def draw_text(text, font, text_col, x, y):
    img = font.render(text, True, text_col)
    window.blit(img, (x, y))

def draw_text_centered(text, font, color, x, y):
    img = font.render(text, True, color)
    rect = img.get_rect(center=(x, y))
    window.blit(img, rect)

def fetch_planes():
    global run
    
    while True:
        today = datetime.today().strftime("%Y-%m-%d")
        ref = db.reference(f"device_stats")
        
        try:
            data = ref.get()
            if data is not None and "run" in data:
                run = data["run"]
            else:
                ref.update({"run": run})
        except Exception as e:
            print(f"Firebase error: {e}")
        
        if not run:
            print("Tracker paused, waiting for Firebase update or manual resume...")
            time.sleep(3)
            continue  
        
        print("Starting plane tracking...")
        sock = connect(SERVER_SBS)
        buffer = ""
        last_data_time = time.time()
        firebase_check_time = time.time()

        try:
            while run:
                if time.time() - firebase_check_time > 2:
                    try:
                        fb_data = ref.get()
                        if fb_data and "run" in fb_data:
                            new_run_value = fb_data["run"]
                            if run != new_run_value:  
                                run = new_run_value
                                if not run:
                                    print("Tracking paused from Firebase")
                                    break  
                    except Exception as e:
                        print(f"Firebase check error: {e}")
                    
                    firebase_check_time = time.time() 

                data = sock.recv(1024)
                if not data:
                    print("ADSB Server disconnected")
                    break

                buffer += data.decode(errors="ignore")
                messages = buffer.split("\n")
                buffer = messages.pop()
                new_data = False

                for message in messages:
                    plane_data = split_message(message, message_queue)
                    if plane_data:
                        add_upload_task(plane_data, cpu_temp, ram_percentage, run, plane_stats)
                        new_data = True

                if new_data:
                    last_data_time = time.time()
                else:
                    if time.time() - last_data_time > 10:
                        print("No New Data")
                        last_data_time = time.time()

                time.sleep(0.05)

        except (socket.error, ConnectionError) as error:
            print(f"Connection lost: {error}. Attempting to reconnect")
            time.sleep(3)
        except KeyboardInterrupt:
            print("Stopping Script")
            break
        except Exception as error:
            print(f"Unexpected error: {error}")
            time.sleep(3)
        finally:
            sock.close()

def add_upload_task(plane_data, cpu_temp, ram_percentage, run, plane_stats):
    global upload_threads
    upload_threads = [t for t in upload_threads if t.is_alive()]

    while len(upload_threads) >= MAX_UPLOAD_THREADS:
        time.sleep(0.1)
        upload_threads = [t for t in upload_threads if t.is_alive()]
    
    t = threading.Thread(
        target=upload_data, 
        args=(plane_data, cpu_temp, ram_percentage, run, plane_stats, active_planes)
    )
    t.daemon = True
    t.start()
    upload_threads.append(t)

def start_fetching_planes():
    t = threading.Thread(target=fetch_planes, daemon=True)
    t.start()

def process_message_queue():
    global display_messages
    
    while not message_queue.empty():
        try:
            message = message_queue.get(block=False)
            display_messages.append(message)
            message_queue.task_done()
        except queue.Empty:
            break
    
    if len(display_messages) > 15:
        display_messages = display_messages[-15:]

bright = pygame.image.load(os.path.join("textures", "icons", "bright.png"))
dark = pygame.image.load(os.path.join("textures", "icons", "dark.png"))
pause = pygame.image.load(os.path.join("textures", "icons", "pause.png"))
resume = pygame.image.load(os.path.join("textures", "icons", "resume.png"))
off = pygame.image.load(os.path.join("textures", "icons", "off.png"))

bright_image = bright.get_rect(topleft=(590, 415))
dark_image = dark.get_rect(topleft=(640, 415))
pause_image = pause.get_rect(topleft=(690, 415))
resume_image = resume.get_rect(topleft=(690, 415))
off_image = off.get_rect(topleft=(740, 415))

def main():
    global cpu_temp
    global ram_percentage
    global run
    start_time = time.time()

    start_fetching_planes()
    last_update_time = time.time()
    
    while True:
        if time.time() - start_time > 1800:
            print("Restarting plane tracker...")
            restart_script()

        mouse_x, mouse_y = pygame.mouse.get_pos()
        range = 100

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()
            elif event.type == MOUSEBUTTONDOWN:
                ...


        process_message_queue()

        current_time = strftime("%H:%M:%S", gmtime())
        current_date = strftime("%d/%m/%Y", gmtime())
        ram_percentage = psutil.virtual_memory()[2]

        with open("/sys/class/thermal/thermal_zone0/temp", "r") as temp:
            cpu_temp = int(temp.read()) / 1000 

        pygame.draw.rect(window, (0, 0, 0), (0, 0, width, height))
        pygame.draw.polygon(window, (255, 0, 0), [(400, 238), (402, 240), (400, 242), (398, 240)])

        now = time.time()
        expired_keys = []

        for icao, plane in list(active_planes.items()):
            last_seen = plane.get("last_seen", 0)

            # Remove planes that haven't updated in 30 seconds
            if now - last_seen > 30:
                expired_keys.append(icao)
                continue

            # Use the last known good position
            lat = plane.get("last_lat")
            lon = plane.get("last_lon")

            if lat is None or lon is None:
                continue

            try:
                plane_string = f"{plane.get('manufacturer', '-') or '-'} {plane.get('model', '-') or '-'}"
                spotted_at = plane.get("spotted_at", "-")
                x, y = coords_to_xy(float(lat), float(lon), range)

                pygame.draw.polygon(window, (255, 255, 255), [(x, y - 2), (x + 2, y), (x, y + 2), (x - 2, y)])

                draw_text(str(cpu_temp), text_font1, (255, 0, 0), 20, 20)
                draw_text(str(ram_percentage), text_font1, (255, 0, 0), 20, 70)

                draw_text_centered(plane_string, text_font3, (255, 255, 255), x, y - 9)
                draw_text_centered(spotted_at, text_font3, (255, 255, 255), x, y + 9)
            except Exception as e:
                print(f"Drawing error for {icao}: {e}")

        # Remove stale planes
        for key in expired_keys:
            del active_planes[key]


        pygame.display.update()

        if time.time() - last_update_time > 10:
            gc.collect()
            last_update_time = time.time()

        time.sleep(0.05)

if __name__ == "__main__":
    main()