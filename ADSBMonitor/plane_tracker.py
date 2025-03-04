#!/usr/bin/env python3

import socket
import json
import time
import urllib.request
from datetime import datetime
import firebase
from firebase_admin import firebase_admin, credentials, db

#Connecting to Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("./rpi-flight-tracker-firebase-adminsdk-fbsvc-a6afd2b5b0.json")
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app"
    })

#Connecting to ADSB Receiver
SERVER_JSON = "http://localhost:8080/data/aircraft.json"
SERVER_SBS = ("localhost", 30003)

def connect(server):
    while True:
        try:
            sock = socket.create_connection(server)
            print(f"Connected to {server}")
            return sock
        except Exception as error:
            print(f"Failed to conect to server: {error}, retrying in 3 seconds.")
            time.sleep(3)

#Turn message into a dict
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

#Upload the dict to Firebase
def upload_data(path, data):
    try:
        #Get data
        ref = db.reference(path)
        current_data = ref.get()

        #If data is empty upload plane data
        if current_data is None:
            ref.set(data)
            print(f"Data added at {path}")
            return
        
        #Otherwise check for "N/A" values and replace them with new data
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
        print(f"Error uploading data: {error}")

#Receive planes
def fetch_planes():
    sock = connect(SERVER_SBS)
    buffer = ""
    run = True

    while run:
        try:
            buffer += sock.recv(1024).decode(errors="ignore")
            messages = buffer.split("\n")
            buffer = messages.pop()
            today = datetime.today().strftime("%Y-%m-%d")

            for i in messages:
                plane_data = split_message(i)
                if plane_data:
                    upload_data(f"/{today}/{plane_data['icao']}", plane_data)

            time.sleep(0.1)
        except (socket.error, KeyboardInterrupt):
            run = False

if __name__ == "__main__":
    fetch_planes()

