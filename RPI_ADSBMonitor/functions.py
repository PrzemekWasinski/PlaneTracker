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
        "location_history": {},
        "last_update_time": time.time()  #When this plane was last updated
    }

def clean_string(string):
    return re.sub(r"[\/\\\.,:]", " ", string)

def get_stats():
    today = datetime.today().strftime("%Y-%m-%d")
    csv_path = os.path.join('./stats_history', f'{today}.csv')

    default_stats = {
        'total': 0,
        'top_model': {'name': None, 'count': 0},
        'top_manufacturer': {'name': None, 'count': 0},
        'top_airline': {'name': None, 'count': 0},
        'manufacturer_breakdown': {},
        'last_updated': strftime("%H:%M:%S", localtime())
    }

    if not os.path.exists(csv_path):
        return default_stats

    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            planes = []

            for row in reader:
                if not row.get('icao'):
                    continue

                manufacturer = row.get('manufacturer', '').strip()
                model = row.get('model', '').strip()
                airline = row.get('airline', '').strip()

                # Skip row if any key field is "-"
                if '-' in (manufacturer, model, airline):
                    continue

                planes.append({
                    'manufacturer': manufacturer,
                    'model': model,
                    'airline': airline
                })

            if not planes:
                return default_stats

            # Count occurrences
            model_counter = Counter(p['model'] for p in planes)
            manufacturer_counter = Counter(p['manufacturer'] for p in planes)
            airline_counter = Counter(p['airline'] for p in planes)

            top_model = model_counter.most_common(1)[0] if model_counter else (None, 0)
            top_manufacturer = manufacturer_counter.most_common(1)[0] if manufacturer_counter else (None, 0)
            top_airline = airline_counter.most_common(1)[0] if airline_counter else (None, 0)

            return {
                'total': len(planes),
                'top_model': {'name': top_model[0], 'count': top_model[1]},
                'top_manufacturer': {'name': top_manufacturer[0], 'count': top_manufacturer[1]},
                'top_airline': {'name': top_airline[0], 'count': top_airline[1]},
                'manufacturer_breakdown': dict(manufacturer_counter),
                'last_updated': strftime("%H:%M:%S", localtime())
            }

    except (FileNotFoundError, PermissionError, csv.Error, UnicodeDecodeError) as e:
        print(f"Error reading stats file: {e}")
        return default_stats
    except Exception as e:
        print(f"Unexpected error getting stats: {e}")
        return default_stats
