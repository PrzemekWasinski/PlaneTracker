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

def restart_script():
    print("Restarting script")
    time.sleep(2)
    os.execv(sys.executable, ["python3"] + sys.argv)

def connect(server):
    while True:
        try:
            sock = socket.create_connection(server)
            print(f"Connected to {server}")
            return sock
        except Exception as error:
            print(f"Failed to connect: {error}. Attempting to reconnect")
            time.sleep(3)

def coords_to_xy(lat, lon, range_km):
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

def split_message(message, message_queue):
    plane_info = message.split(",")
    
    if len(plane_info) < 15 or plane_info[0] != "MSG":
        return None
    
    message_queue.put({
        "icao": plane_info[4],
        "lat": plane_info[14],
        "lon": plane_info[15]
    })
    
    return {
        "icao": plane_info[4] or "-", 
        "altitude": plane_info[11] or "-",
        "speed": plane_info[12] or "-",
        "track": plane_info[13] or "-",
        "lat": plane_info[14] or "-",
        "lon": plane_info[15] or "-",
        #Rest will be populated by the API response
        "manufacturer": "-",
        "registration": "-",
        "icao_type_code": "-",
        "code_mode_s": "-",
        "operator_flag": "-",
        "owner": "-",
        "model": "-",
        "spotted_at": datetime.now().strftime("%H:%M:%S") or "-",
        "location_history": {}
    }
        
def upload_data(data, cpu_temp, ram_percentage, run, plane_stats, active_planes):
    manufacturer = "-"
    model = "-"
    registration = "-"
    owner = "-"
    
    try:
        url = f"https://hexdb.io/api/v1/aircraft/{data['icao']}"
        response = requests.get(url, timeout=5)  # Add timeout to prevent hanging
        
        if response.status_code == 200:
            api_data = response.json()
            manufacturer = str(api_data.get("Manufacturer", "-"))
            registration = str(api_data.get("Registration", "-"))
            owner = str(api_data.get("RegisteredOwners", "-"))
            
            model = str(api_data.get("Type", "-")).replace(".", "")
            model = model.replace("/", "")
            
            # Update plane stats counters
            if manufacturer in plane_stats:
                plane_stats[manufacturer] += 1
            elif manufacturer == "Avions de Transport Regional":
                plane_stats["ATR"] += 1
            else:
                plane_stats["Other"] += 1
                
            plane_stats["Total"] += 1
            
            data["manufacturer"] = manufacturer
            data["registration"] = registration
            data["icao_type_code"] = str(api_data.get("ICAOTypeCode", "-"))
            data["code_mode_s"] = str(api_data.get("ModeS", "-"))
            data["operator_flag"] = str(api_data.get("OperatorFlagCode", "-"))
            data["owner"] = owner
            data["model"] = model
            
    except requests.exceptions.RequestException as e:
        print(f"API timeout: {data['icao']}")
    except Exception as error:
        print(f"API Error: {error}")

    try:
        today = datetime.today().strftime("%Y-%m-%d")
        ref = db.reference(f"{today}/{manufacturer} {model} ({registration}) {owner}")
        stats_ref = db.reference("device_stats")
        if (manufacturer != "-" and model != "-" and registration != "-" and owner != "-"):
            
            current_data = ref.get()
            if current_data is None:
                data["location_history"] = {}
                ref.set(data)
            else:
                location_history = current_data.get("location_history", {})

                if data["lat"] != "-" and data["lon"] != "-":
                    location_history[data["spotted_at"]] = [data["lat"], data["lon"]]
                    data["location_history"] = location_history
                else:
                    data["location_history"] = location_history

                new_data = {}
                for key, value in data.items():
                    current_value = current_data.get(key)
                    if value == "-" or []:
                        new_data[key] = current_value
                    else:
                        new_data[key] = value
                ref.set(new_data)

                icao = data["icao"]
                lat = data.get("lat")
                lon = data.get("lon")

                # Only update lat/lon if they're valid
                if lat not in [None, "-", ""] and lon not in [None, "-", ""]:
                    data["last_lat"] = float(lat)
                    data["last_lon"] = float(lon)

                # Always update last_seen
                data["last_seen"] = time.time()

                # Keep the existing lat/lon if new ones are invalid
                if icao in active_planes:
                    if "last_lat" in active_planes[icao] and (lat in [None, "-", ""] or lon in [None, "-", ""]):
                        data["last_lat"] = active_planes[icao]["last_lat"]
                        data["last_lon"] = active_planes[icao]["last_lon"]

                active_planes[icao] = data

        
        current_stats = stats_ref.get() or {}
        
        device_stats = {}
        if "cpu_temp" not in current_stats or current_stats["cpu_temp"] != cpu_temp:
            device_stats["cpu_temp"] = cpu_temp
            
        if "ram_percentage" not in current_stats or current_stats["ram_percentage"] != ram_percentage:
            device_stats["ram_percentage"] = ram_percentage
            
        if "run" not in current_stats:
            device_stats["run"] = run
        
        if device_stats:
            stats_ref.update(device_stats)
            
    except Exception as error:
        print(f"Firebase Error: {error}")