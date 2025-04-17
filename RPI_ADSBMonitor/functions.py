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

def coords_to_xy(lat, lon, range_km): #Cnverts coordinates to pixel positions for the radar display
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

def split_message(message, message_queue): #Seperates data in an ADSB message
    plane_info = message.split(",")
    
    if len(plane_info) < 15 or plane_info[0] != "MSG":
        return None
    
    return { #Plane JSON
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

def clean_string(string): #Removes characters that might cause problems with Firebase
    return re.sub(r"[\/\\\.,:]", " ", string)

def upload_data(data, cpu_temp, ram_percentage, run, active_planes, message_queue): #Calls an API to get more details on received plane info and sends it to Firebase
    manufacturer = "-"
    model = "-"
    registration = "-"
    owner = "-"
    
    try:
        url = f"https://hexdb.io/api/v1/aircraft/{data['icao']}" #Call API with ICAO code received in the ADSB message
        response = requests.get(url, timeout=5) 
        
        if response.status_code == 200: #If API response was successful
            api_data = response.json()
            manufacturer = clean_string(str(api_data.get("Manufacturer", "-"))) #Remove unwanted characters
            registration = clean_string(str(api_data.get("Registration", "-")))
            owner = clean_string(str(api_data.get("RegisteredOwners", "-")))
            model = clean_string(str(api_data.get("Type", "-")))

            if manufacturer == "Avions de Transport Regional": #Shorten strings which are too long to display on radar menu
                manufacturer = "ATR"
            elif manufacturer == "Honda Aircraft Company":
                manufacturer = "Honda"

            data["manufacturer"] = manufacturer #Add API reponse information to plane JSON
            data["registration"] = registration
            data["icao_type_code"] = clean_string(str(api_data.get("ICAOTypeCode", "-")))
            data["code_mode_s"] = clean_string(str(api_data.get("ModeS", "-")))
            data["operator_flag"] = clean_string(str(api_data.get("OperatorFlagCode", "-")))
            data["owner"] = owner
            data["model"] = model

            message_queue.put(f"{manufacturer} {model}") #Send manufacturer and plane model to the message queue for radar menu
            
    except requests.exceptions.RequestException as error: #Error handling
        print(f"API timeout: {data['icao']}")
    except Exception as error:
        print(f"API Error: {error}")

    try: #Upload plane data to Firebase
        today = datetime.today().strftime("%Y-%m-%d") #Firebase paths
        ref = db.reference(f"{today}/{manufacturer} {model} ({registration}) {owner}")
        stats_ref = db.reference("device_stats")

        if (manufacturer != "-" and model != "-" and registration != "-" and owner != "-"): #If no information is missing
            current_data = ref.get() #Get current plane data
            if current_data is None: #If there isnt any for that plane upload the current data
                data["location_history"] = {}
                ref.set(data)
            else: #Otherwise get the location history
                location_history = current_data.get("location_history", {})

                if data["lat"] != "-" and data["lon"] != "-": #If we have valid coordinates add them to location history
                    location_history[data["spotted_at"]] = [data["lat"], data["lon"]]
                    data["location_history"] = location_history
                else: #Otherwise keep it same
                    data["location_history"] = location_history

                new_data = {} #Store new plane data
                for key, value in data.items():
                    current_value = current_data.get(key)
                    if value == "-" or []: #If previous plane data had missing fields update them
                        new_data[key] = current_value
                    else: #If not keep them same to avoid overwriting valid data with missing data
                        new_data[key] = value
                ref.set(new_data) #Upload th enew data

                icao = data["icao"] #Get coordnates for the active planes JSON
                lat = data.get("lat")
                lon = data.get("lon")

                if lat not in [None, "-", ""] and lon not in [None, "-", ""]: #Only update coordinates if theyre valid
                    data["last_lat"] = float(lat)
                    data["last_lon"] = float(lon)
                    data["last_pos_update"] = time.time()

                data["last_seen"] = time.time() #Update last seen time

                if icao in active_planes: #Keep the existing coordinates if new ones are invalid
                    if "last_lat" in active_planes[icao] and (lat in [None, "-", ""] or lon in [None, "-", ""]):
                        data["last_lat"] = active_planes[icao]["last_lat"]
                        data["last_lon"] = active_planes[icao]["last_lon"]
                        data["last_pos_update"] = active_planes[icao].get("last_pos_update", 0)

                active_planes[icao] = data #Save plane data to active planes JSON

        
        current_stats = stats_ref.get() or {} #Get current device stats
        device_stats = {}

        if "cpu_temp" not in current_stats or current_stats["cpu_temp"] != cpu_temp: #Update CPU temp if it has changed
            device_stats["cpu_temp"] = cpu_temp
            
        if "ram_percentage" not in current_stats or current_stats["ram_percentage"] != ram_percentage: #Update ram usage if it has changed
            device_stats["ram_percentage"] = ram_percentage
            
        if "run" not in current_stats: #Update run status
            device_stats["run"] = run
        
        if device_stats: #Send device stats to Firebase
            stats_ref.update(device_stats)
            
    except Exception as error: #Catch errors
        print(f"Firebase Error: {error}")