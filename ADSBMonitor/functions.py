#!/usr/bin/env python3

import socket
import time
import os
import sys
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db

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

def split_message(message):
    plane_info = message.split(",")

    if len(plane_info) < 15 or plane_info[0] != "MSG":
        return None
    return {
        "icao": plane_info[4], 
        "altitude": plane_info[11] or "N/A",
        "speed": plane_info[12] or "N/A",
        "track": plane_info[13] or "N/A",
        "lat": plane_info[14] or "N/A",
        "lon": plane_info[15] or "N/A"
    }

def upload_data(path, data, message_queue):
    try:
        ref = db.reference(path)
        current_data = ref.get()

        if current_data is None:
            ref.set(data)
            message_queue.put(f"Data added at {path}")
        else:
            new_data = {}

            for key, value in data.items():
                current_value = current_data.get(key, "N/A")

                if value == "N/A":
                    new_data[key] = current_value
                else:
                    new_data[key] = value

            ref.set(new_data)
            message_queue.put(f"Data updated at {path}")
    except Exception as error:
        message_queue.put(f"Firebase Error: {error}")