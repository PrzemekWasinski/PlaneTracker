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

if not firebase_admin._apps: #Initialise Firebase
    cred = credentials.Certificate("./rpi-flight-tracker-firebase-adminsdk-fbsvc-a6afd2b5b0.json")
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app"
    })

SERVER_SBS = ("localhost", 30003) #ADSB port

pygame.init()
run = True

width = 800 #Display dimensions
height = 480
window = pygame.display.set_mode((width, height), pygame.FULLSCREEN)

text_font1 = pygame.font.Font(os.path.join("textures", "NaturalMono-Bold.ttf"), 16) #Fonts
text_font2 = pygame.font.Font(os.path.join("textures", "DS-DIGI.TTF"), 40)
text_font3 = pygame.font.Font(os.path.join("textures", "NaturalMono-Bold.ttf"), 9)

active_planes = {} #Stores planes received in the last 30 seconds

message_queue = queue.Queue(maxsize=20) #Messages that will be displayed in the menu get stored here
display_messages = []

upload_threads = [] #Threads to decrease CPU usage
MAX_UPLOAD_THREADS = 5

def draw_text(text, font, text_col, x, y): #Functoins to display text
    img = font.render(text, True, text_col)
    window.blit(img, (x, y))

def draw_text_centered(text, font, color, x, y):
    img = font.render(text, True, color)
    rect = img.get_rect(center=(x, y))
    window.blit(img, rect)

def fetch_planes(): #Function that receives and handles ADSB signals
    global run
    
    while True: #Check if tracker is paused
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

                for message in messages: #Seperate message data
                    plane_data = split_message(message, message_queue)
                    if plane_data:
                        add_upload_task(plane_data, cpu_temp, ram_percentage, run, active_planes, message_queue) #Upload message to Firebase
                        new_data = True

                if new_data: #Update the last time the receiver received data
                    last_data_time = time.time()
                else:
                    if time.time() - last_data_time > 10:
                        print("No New Data")
                        last_data_time = time.time()

                time.sleep(0.05)

        except (socket.error, ConnectionError) as error: #Error handling
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

def add_upload_task(plane_data, cpu_temp, ram_percentage, run, active_planes, message_queue): #Starts uploading data on a seperate thread
    global upload_threads
    upload_threads = [t for t in upload_threads if t.is_alive()]

    while len(upload_threads) >= MAX_UPLOAD_THREADS: #Wait for an available thread
        time.sleep(0.1)
        upload_threads = [t for t in upload_threads if t.is_alive()]
    
    t = threading.Thread( #Upload data if a thread becomes available
        target=upload_data, 
        args=(plane_data, cpu_temp, ram_percentage, run, active_planes, message_queue)
    )
    t.daemon = True
    t.start()
    upload_threads.append(t)

def start_fetching_planes(): #Starts receiving ADSB signals on a seperate thread
    t = threading.Thread(target=fetch_planes, daemon=True)
    t.start()

def process_message_queue(): #Manages amount of messages so we only store the amount that we can display
    global display_messages
    
    while not message_queue.empty():
        try:
            message = message_queue.get(block=False)
            display_messages.append(message)
            message_queue.task_done()
        except queue.Empty:
            break
    
    if len(display_messages) > 26:
        display_messages = display_messages[-26:]

image1 = pygame.image.load(os.path.join("textures", "icons", "open_menu.png")) #Load images
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

def main(): #Main loop
    global cpu_temp
    global ram_percentage
    global run
    start_time = time.time()

    start_fetching_planes() #Start receiving ADSB signals
    last_update_time = time.time()
    menu_open = False
    range = 50 #Default range on the display

    while True:
        if time.time() - start_time > 1800: #Reset tracker every 30min 
            print("Restarting plane tracker...")
            restart_script()

        ram_percentage = psutil.virtual_memory()[2] #Get RAM usage

        with open("/sys/class/thermal/thermal_zone0/temp", "r") as temp: #Get CPU temp
            cpu_temp = int(temp.read()) / 1000 

        mouse_x, mouse_y = pygame.mouse.get_pos() #Get mouse position
        #print(mouse_x, mouse_y)

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
                    elif mouse_x > 635 and mouse_y > 415 and mouse_x < 675 and mouse_y < 455 and range < 1000: #Increase range button
                        range += 25
                    elif mouse_x > 685 and mouse_y > 415 and mouse_x < 725 and mouse_y < 455: #Pause/resume button
                        run = not run 
                        ref = db.reference(f"device_stats")
                        ref.set({"run": run})
                    elif mouse_x > 735 and mouse_y > 415 and mouse_x < 775 and mouse_y < 455: #Quit button
                        run = False 
                        ref = db.reference(f"device_stats")
                        ref.set({"run": run})
                        pygame.quit()

        process_message_queue() #Handle messages   

        now = time.time()
        expired_keys = [] #Stores planes that havent been updated in th elast 30 seconds

        for icao, plane in list(active_planes.items()): #For every plane
            last_pos_update = plane.get("last_pos_update", 0) #Check if it was located in th elast 30 seconds to keep radar up to date

            if now - last_pos_update > 30: #Remove planes from more than 30 seconds ago
                expired_keys.append(icao)
                continue

            lat = plane.get("last_lat") #Check if received plane data contains coordinates
            lon = plane.get("last_lon")
            if lat is None or lon is None:
                continue #If it doesnt dont display it
            
            owner = plane.get("owner") #Get plane's airline and model
            model = plane.get('model', '-')
            if ("Air Force" in owner): #Highlights military planes in red
                rgb_value = (255, 0, 0)
            elif "747" in model or "340" in model: #Highlights A340s and 747s in purple because theyre my favourite
                rgb_value = (255, 0, 255)
            else:
                rgb_value = (255, 255, 255)

            try: #Draw plane on the radar
                plane_string = f"{plane.get('manufacturer', '-') or '-'} {model}"
                x, y = coords_to_xy(float(lat), float(lon), range)

                pygame.draw.polygon(window, rgb_value, [(x, y - 2), (x + 2, y), (x, y + 2), (x - 2, y)])
                draw_text_centered(owner, text_font3, (255, 255, 255), x, y - 9)
                draw_text_centered(plane_string, text_font3, (255, 255, 255), x, y + 9)
                #draw_text_centered(datetime.fromtimestamp(last_pos_update).strftime("%H:%M:%S"), text_font3, (255, 255, 255), x, y + 9)
            except Exception as error:
                print(f"Drawing error for {icao}: {error}")

        for key in expired_keys: #Remove planes that havent been updated in the last 30sec
            del active_planes[key]
        
        if menu_open: #Draw the menu
            current_time = strftime("%H:%M:%S", gmtime())   

            pygame.draw.rect(window, (0, 0, 0), (570, 10, 220, 460), 0, 5)

            draw_text_centered(current_time, text_font2, (255, 0, 0), 675, 40)
            draw_text_centered(f"CPU:{str(round(cpu_temp))}°C  RAM:{str(ram_percentage)}%", text_font1, (255, 255, 255), 675, 75)

            pygame.draw.rect(window, (255, 255, 255), (580, 90, 200, 275), 2)

            draw_text(f"Range: {range}KM", text_font1, (255, 255, 255), 580, 365)

            y = 94
            for i, message in enumerate(display_messages):
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