#!/usr/bin/env python3

import socket
import json
import time
import urllib.request
import os
import sys
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db

if not firebase_admin._apps:
    cred = credentials.Certificate("./rpi-flight-tracker-firebase-adminsdk-fbsvc-a6afd2b5b0.json")
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app"
    })

SERVER_SBS = ("localhost", 30003)

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

def split_message(message):
    plane_info = message.split(",")

    if len(plane_info) < 15 or plane_info[0] != "MSG":
        return None
    return {
        "icao": plane_info[4], 
        "date": plane_info[6] or "N/A",
        "altitude": plane_info[11] or "N/A",
        "speed": plane_info[12] or "N/A",
        "track": plane_info[13] or "N/A",
        "lat": plane_info[14] or "N/A",
        "lon": plane_info[15] or "N/A"
    }

def upload_data(path, data):
    try:
        ref = db.reference(path)
        current_data = ref.get()

        if current_data is None:
            ref.set(data)
            print(f"Data added at {path}")
        else:
            new_data = {}

            for key, value in data.items():
                current_value = current_data.get(key, "N/A")

                if value == "N/A":
                    new_data[key] = current_value
                else:
                    new_data[key] = value

            ref.set(new_data)
            print(f"Data updated at {path}")
    except Exception as error:
        print(f"Firebase Error: {error}")

def fetch_planes():
    start_time = time.time() 

    while True:
        sock = connect(SERVER_SBS)
        buffer = ""
        last_data_time = time.time()

        try:
            while True:
                if time.time() - start_time > 600:
                    print("Restarting script")
                    restart_script()

                data = sock.recv(1024)
                if not data:
                    raise ConnectionError("ADS-B Server disconnected")

                buffer += data.decode(errors="ignore")
                messages = buffer.split("\n")
                buffer = messages.pop()
                today = datetime.today().strftime("%Y-%m-%d")
                new_data = False

                for message in messages:
                    plane_data = split_message(message)
                    if plane_data:
                        upload_data(f"/{today}/{plane_data['icao']}", plane_data)
                        new_data = True

                if new_data:
                    last_data_time = time.time()  
                else:
                    if time.time() - last_data_time > 10:  
                        print("No new data")
                        last_data_time = time.time()

                time.sleep(0.1) 

        except (socket.error, ConnectionError) as error:
            print(f"Connection lost: {error}. Attempting to reconnect")
            time.sleep(3)
        except KeyboardInterrupt:
            print("\nStopping script")
            break
        except Exception as error:
            print(f"Unexpected error: {error}")
            time.sleep(3)  
        finally:
            sock.close()

if __name__ == "__main__":
    fetch_planes()
