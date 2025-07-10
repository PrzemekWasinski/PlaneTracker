#!/usr/bin/env python3

import socket
import time
import os
import sys
from datetime import datetime
import firebase_admin
from firebase_admin import db
import requests
import math
import re
import json
from time import strftime, localtime
import csv
import os
from datetime import datetime
from time import strftime, localtime
from collections import Counter
import portalocker

def restart_script(): #Function to restart the script
    print("Restarting script")
    time.sleep(2)
    os.execv(sys.executable, ["python3"] + sys.argv)

def connect(server): #Connects to ADSB receiver
    while True:
        try:
            sock = socket.create_connection(server)
            print(f"Connected to {server}")
            return sock
        except Exception as error:
            print(f"Failed to connect: {error}. Attempting to reconnect")
            time.sleep(3)

def coords_to_xy(lat, lon, range_km): #Converts coordinates to pixel positions for the radar display
    centre_lat = 0.000000
    centre_lon = 0.000000

    screen_width = 800
    screen_height = 480

    delta_lat = lat - centre_lat
    delta_lon = lon - centre_lon

    dy = delta_lat * 111  
    dx = delta_lon * 111 * math.cos(math.radians(centre_lat)) 

    km_per_px = (range_km * 2) / screen_width

    x = screen_width // 2 + int(dx / km_per_px)
    y = screen_height // 2 - int(dy / km_per_px)  

    return x, y

def split_message(message):
    plane_info = message.split(",")
    
    if len(plane_info) < 15 or plane_info[0] != "MSG":
        return None
    
    return {
        "icao": plane_info[4] or "-", 
        "altitude": plane_info[11] or "-",
        "speed": plane_info[12] or "-",
        "track": plane_info[13] or "-",
        "lat": plane_info[14] or "-",
        "lon": plane_info[15] or "-",
        "manufacturer": "-",
        "registration": "-",
        "icao_type_code": "-",
        "code_mode_s": "-",
        "operator_flag": "-",
        "owner": "-",
        "model": "-",
        "spotted_at": datetime.now().strftime("%H:%M:%S") or "-",
        "last_update_time": time.time()  #When this plane was last updated
    }

def clean_string(string):
    return re.sub(r"[\/\\\.,:]", " ", string)

def process_message_queue(message_queue, display_messages):
    while not message_queue.empty():
        try:
            message = message_queue.get(block=False)
            display_messages.append(message)
            message_queue.task_done()
        except queue.Empty:
            break
    
    if len(display_messages) > 24:
        display_messages = display_messages[-24:]

