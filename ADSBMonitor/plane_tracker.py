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
text_font3 = pygame.font.Font(os.path.join("textures", "DS-DIGI.TTF"), 26)

message_queue = queue.Queue(maxsize=20)
display_messages = []

upload_threads = []
MAX_UPLOAD_THREADS = 5

def draw_text(text, font, text_col, x, y):
    img = font.render(text, True, text_col)
    window.blit(img, (x, y))

def fetch_planes():
    start_time = time.time()

    while True:
        sock = connect(SERVER_SBS, message_queue)
        buffer = ""
        last_data_time = time.time()

        try:
            while True:
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
                    plane_data = split_message(message)
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
        args=(f"/{today}/{plane_data['icao']}", plane_data, message_queue)
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
    
def main():
    start_fetching_planes()
    
    last_update_time = time.time()
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()

        process_message_queue()

        pygame.draw.rect(window, (0, 0, 0), (0, 0, width, height))

        current_time = strftime("%H:%M:%S", gmtime())
        current_date = strftime("%d/%m/%Y", gmtime())
        ram_percentage = psutil.virtual_memory()[2]

        with open("/sys/class/thermal/thermal_zone0/temp", "r") as temp:
            cpu_temp = int(temp.read()) / 1000 

        draw_text(str(current_time), text_font1, (255, 0, 0), 628, 10)
        draw_text(str(current_date), text_font2, (255, 0, 0), 620, 50)
        draw_text("RAM: " + str(ram_percentage) + "%", text_font2, (255, 255, 255), 626, 100)
        draw_text("CPU: " + str(int(cpu_temp)) + "*C", text_font2, (255, 255, 255), 626, 135)

        start = 10
        for i, message in enumerate(display_messages):
            draw_text(message, text_font3, (255, 255, 255), 20, start)
            start += 30

        pygame.display.update()

        if time.time() - last_update_time > 10:
            gc.collect()
            last_update_time = time.time()

        time.sleep(0.05)

if __name__ == "__main__":
    main()