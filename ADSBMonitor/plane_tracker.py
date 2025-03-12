#!/usr/bin/env python3

import socket
import time
from datetime import datetime
import firebase_admin
from firebase_admin import credentials
import pygame
from pygame.locals import *
from time import gmtime, strftime
import psutil
import os
import threading
import gc 
import queue
import requests
from functions import *

if not firebase_admin._apps:
    cred = credentials.Certificate("./rpi-flight-tracker-firebase-adminsdk-fbsvc-a6afd2b5b0.json")
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app"
    })

SERVER_SBS = ("localhost", 30003)

pygame.init()

width = 800
height = 480

window = pygame.display.set_mode((width, height), pygame.FULLSCREEN)

text_font1 = pygame.font.Font(os.path.join("textures", "DS-DIGI.TTF"), 50)
text_font2 = pygame.font.Font(os.path.join("textures", "DS-DIGI.TTF"), 40)
text_font3 = pygame.font.Font(os.path.join("textures", "NaturalMono-Bold.ttf"), 14)

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

def fetch_planes():
    start_time = time.time()
    
    while run:
        sock = connect(SERVER_SBS, message_queue)
        buffer = ""
        last_data_time = time.time()

        try:
            while run:
                if time.time() - start_time > 600:
                    message_queue.put("Restarting Plane Tracker...")
                    restart_script()

                data = sock.recv(1024)
                if not data:
                    message_queue.put("ADSB Server disconnected")
                    break

                buffer += data.decode(errors="ignore")
                messages = buffer.split("\n")
                buffer = messages.pop()
                today = datetime.today().strftime("%Y-%m-%d")
                new_data = False

                for message in messages:
                    plane_data = split_message(message, message_queue, plane_stats)
                    if plane_data:
                        add_upload_task(today, plane_data)
                        new_data = True

                if new_data:
                    last_data_time = time.time()
                else:
                    if time.time() - last_data_time > 10:
                        message_queue.put("No New Data")
                        last_data_time = time.time()

                time.sleep(0.05)

        except (socket.error, ConnectionError) as error:
            message_queue.put(f"Connection lost: {error}. Attempting to reconnect")
            time.sleep(3)
        except KeyboardInterrupt:
            message_queue.put("Stopping Script")
            break
        except Exception as error:
            message_queue.put(f"Unexpected error: {error}")
            time.sleep(3)
        finally:
            sock.close()

def add_upload_task(today, plane_data):
    global upload_threads
    upload_threads = [t for t in upload_threads if t.is_alive()]

    while len(upload_threads) >= MAX_UPLOAD_THREADS:
        time.sleep(0.1)
        upload_threads = [t for t in upload_threads if t.is_alive()]
    
    t = threading.Thread(
        target=upload_data, 
        args=(plane_data, message_queue)
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
    global run
    run = True
    drk = 0

    start_fetching_planes()
    last_update_time = time.time()
    
    while True:
        mouse_x, mouse_y = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()
            elif event.type == MOUSEBUTTONDOWN:
                if mouse_x > 585 and mouse_y > 410 and mouse_x < 625 and mouse_y < 450:
                    if drk > 10:
                        drk -= 10
                elif mouse_x > 635 and mouse_y > 410 and mouse_x < 685 and mouse_y < 450:
                    if drk < 250:
                        drk += 10
                elif mouse_x > 685 and mouse_y > 410 and mouse_x < 725 and mouse_y < 450:
                    if run:
                        run = False
                    else:
                        run = True
                        start_fetching_planes()
                elif mouse_x > 735 and mouse_y > 410 and mouse_x < 785 and mouse_y < 450:
                    pygame.quit()


        process_message_queue()

        pygame.draw.rect(window, (0, 0, 0), (0, 0, width, height))

        current_time = strftime("%H:%M:%S", gmtime())
        current_date = strftime("%d/%m/%Y", gmtime())
        ram_percentage = psutil.virtual_memory()[2]

        with open("/sys/class/thermal/thermal_zone0/temp", "r") as temp:
            cpu_temp = int(temp.read()) / 1000 
        
        pygame.draw.rect(window, (255 - drk, 255 - drk, 255 - drk), (585, 410, 40, 40))
        pygame.draw.rect(window, (255 - drk, 255 - drk, 255 - drk), (635, 410, 40, 40))

        if run:
            pygame.draw.rect(window, (255 - drk, 255 - drk, 255 - drk), (685, 410, 40, 40))
            window.blit(pause, (pause_image))
        else:
            pygame.draw.rect(window, (255 - drk, 255 - drk, 255 - drk), (685, 410, 40, 40))
            window.blit(resume, (resume_image))

        pygame.draw.rect(window, (255 - drk, 0, 0), (735, 410, 40, 40)) 

        window.blit(bright, (bright_image))
        window.blit(dark, (dark_image))
        window.blit(off, (off_image))

        draw_text(str(current_time), text_font1, (255 - drk, 0, 0), 585, 10)
        draw_text(str(current_date), text_font2, (255 - drk, 0, 0), 585, 50)
        draw_text("RAM: " + str(ram_percentage) + "%", text_font2, (255 - drk, 255 - drk, 255 - drk), 585, 100)
        draw_text("CPU: " + str(int(cpu_temp)) + "*C", text_font2, (255 - drk, 255 - drk, 255 - drk), 585, 135)

        start = 177
        for i in plane_stats:
            draw_text(f"{i}: {str(plane_stats[i])}", text_font3, (255 - drk, 255 - drk, 255 - drk), 585, start)
            start += 20



        start = 20
        for i, message in enumerate(display_messages):
            draw_text(message, text_font3, (255 - drk, 255 - drk, 255 - drk), 20, start)
            start += 30

        pygame.display.update()

        if time.time() - last_update_time > 10:
            gc.collect()
            last_update_time = time.time()

        time.sleep(0.05)

if __name__ == "__main__":
    main()
