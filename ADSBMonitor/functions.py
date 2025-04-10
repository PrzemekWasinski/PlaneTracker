#!/usr/bin/env python3

import socket
import time
import os
import sys
from datetime import datetime
import firebase_admin
from firebase_admin import db
import requests

def restart_script():
    print("Restarting script")
    time.sleep(2)
    os.execv(sys.executable, ["python3"] + sys.argv)

def connect(server, message_queue):
    while True:
        try:
            sock = socket.create_connection(server)
            message_queue.put(f"Connected to {server}")
            return sock
        except Exception as error:
            message_queue.put(f"Failed to connect: {error}. Attempting to reconnect")
            time.sleep(3)

def split_message(message, message_queue, plane_stats):
    plane_info = message.split(",")
    response = ""

    try:
        url = f"https://hexdb.io/api/v1/aircraft/{plane_info[4]}"
        response = requests.get(url)

        if response.status_code == 404:
            message_queue.put("Unidentified")
            return None

        elif response.status_code != 200:
            message_queue.put(f"API Response: {response.status_code}")
            return None


        message_queue.put(f"{response.json()['RegisteredOwners']} {response.json()['Manufacturer']} {response.json()['Type']} {response.json()['Registration']}")

        if response.json()["Manufacturer"] in plane_stats:
            plane_stats[response.json()["Manufacturer"]] += 1
        elif response.json()["Manufacturer"] == "Avions de Transport Regional":
            plane_stats["ATR"] += 1
        else:
            plane_stats["Other"] += 1


    except Exception as error:
        message_queue.put(f"API Error: {error}")

    if len(plane_info) < 15 or plane_info[0] != "MSG":
        return None
    
    plane_stats["Total"] += 1
    model = str(response.json()["Type"]).replace(".", "")
    model_stripped = model.replace("/", "")

    return {
        "icao": plane_info[4] or "-", 
        "altitude": plane_info[11] or "-",
        "speed": plane_info[12] or "-",
        "track": plane_info[13] or "-",
        "lat": plane_info[14] or "-",
        "lon": plane_info[15] or "-",
        "manufacturer": str(response.json()["Manufacturer"]) or "-",
        "registration": str(response.json()["Registration"]) or "-",
        "icao_type_code": str(response.json()["ICAOTypeCode"]) or "-",
        "code_mode_s": str(response.json()["ModeS"]) or "-",
        "operator_flag": str(response.json()["OperatorFlagCode"]) or "-",
        "owner": str(response.json()["RegisteredOwners"]) or "-",
        "model": model_stripped or "-",
        "spotted_at": datetime.now().strftime("%H:%M:%S") or "-",
        "location_history": {}
    }    
        
def upload_data(data, message_queue, cpu_temp, ram_percentage, run):
    try:
        today = datetime.today().strftime("%Y-%m-%d")
        ref = db.reference(f"{today}/{data['manufacturer']} {data['model']} ({data['registration']}) {data['owner']}")
        stats_ref = db.reference("device_stats")
        
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
        message_queue.put(f"Firebase Error: {error}")
