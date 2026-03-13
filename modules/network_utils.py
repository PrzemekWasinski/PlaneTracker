import socket
import time
from datetime import datetime
from time import localtime, strftime

import requests

from .core_utils import clean_string
from collections import deque


def make_json_safe(value):
    if isinstance(value, deque):
        return [make_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]
    return value



def connect(server):
    while True:
        try:
            sock = socket.create_connection(server)
            return sock
        except Exception as error:
            print(f"Failed to connect: {error}. Attempting to reconnect")
            time.sleep(3)


def check_network(url='https://hexdb.io', timeout=2):
    try:
        requests.get(url, timeout=timeout)
        return True
    except Exception:
        return False


def can_retry_plane_api(plane_data, retry_delay):
    last_error = plane_data.get('last_api_error', 0)
    if last_error == 0:
        return True
    return (time.time() - last_error) >= retry_delay


def try_backup_api(icao):
    try:
        url = f'https://opensky-network.org/api/metadata/aircraft/icao/{icao}'
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            api_data = response.json()
            output = {
                'manufacturer': api_data.get('model', '-').split(' ', 1)[0],
                'registration': api_data.get('registration', '-'),
                'owner': api_data.get('operator', '-'),
                'model': api_data.get('model', '-').split(' ', 1)[1] if ' ' in api_data.get('model', '') else '-',
                'last_api_error': 0,
            }

            if output.get('manufacturer') == '' or output.get('registration') == '' or output.get('owner') == '' or output.get('model') == '':
                return None
            return output

        if response.status_code == 404:
            return None
        if response.status_code >= 500:
            print(f"Backup server error {response.status_code}")
            return {'last_api_error': time.time()}
    except Exception as e:
        print(f"Backup API error: {e}")

    return None


def fetch_plane_info(icao):
    try:
        url = f'https://hexdb.io/api/v1/aircraft/{icao}'
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            api_data = response.json()
            manufacturer = clean_string(str(api_data.get('Manufacturer', '-')))
            if manufacturer == 'Avions de Transport Regional':
                manufacturer = 'ATR'
            elif manufacturer == 'Honda Aircraft Company':
                manufacturer = 'Honda'

            return {
                'manufacturer': manufacturer,
                'registration': clean_string(str(api_data.get('Registration', '-'))),
                'owner': clean_string(str(api_data.get('RegisteredOwners', '-'))),
                'model': clean_string(str(api_data.get('Type', '-'))),
                'last_api_error': 0,
            }

        if response.status_code == 404:
            return None
        if response.status_code == 429:
            print(f"Rate limited for {icao}")
            return {'last_api_error': time.time()}
        if response.status_code >= 500:
            print(f"Server error {response.status_code} for {icao}")
            backup_result = try_backup_api(icao)
            if backup_result:
                return backup_result
            return {'last_api_error': time.time()}
        return try_backup_api(icao)
    except requests.exceptions.Timeout:
        print(f"API timeout for {icao}")
        return {'last_api_error': time.time()}
    except requests.exceptions.ConnectionError:
        print(f"API connection error for {icao}")
        return {'last_api_error': time.time()}
    except Exception as e:
        print(f"API error for {icao}: {e}")
        return {'last_api_error': time.time()}


def upload_to_firebase(plane_data):
    try:
        manufacturer = plane_data.get('manufacturer', '-')
        model = plane_data.get('model', '-')
        registration = plane_data.get('registration', '-')
        owner = plane_data.get('owner', '-')

        if manufacturer == '-' or model == '-' or registration == '-' or owner == '-':
            return

        firebase_data = {}
        for key in plane_data:
            if key not in ['location_history', 'last_update_time', 'last_lat', 'last_lon', 'last_api_error']:
                firebase_data[key] = make_json_safe(plane_data[key])

        min_str = strftime('%M', localtime())
        hour = strftime('%H', localtime())
        time_10 = f"{hour}:{min_str[:-1]}0"
        today = datetime.today().strftime('%Y-%m-%d')

        from firebase_admin import db

        path = f"{today}/{time_10}/{manufacturer}-{model}-({registration})-{owner}"
        ref = db.reference(path)
        current_data = ref.get()
        if current_data is None:
            ref.set(firebase_data)
        else:
            new_data = {}
            for key in firebase_data:
                value = firebase_data[key]
                if value != '-' and value != []:
                    new_data[key] = value
                elif key in current_data:
                    new_data[key] = current_data[key]
            ref.update(new_data)
    except Exception as e:
        print(f"Firebase error: {e}")


def send_to_tracker(lat, lon, alt_ft, add_message=None, host='192.168.0.145', port=12345):
    try:
        alt_m = alt_ft * 0.3048
        if add_message:
            add_message('Sending position data to camera module')

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, port))
        message = f"{lat},{lon},{alt_m}"
        sock.send(message.encode())
        response = sock.recv(1024).decode().strip()
        sock.close()

        if add_message:
            add_message(f"Camera module response: {response or 'no response'}")
    except Exception as e:
        if add_message:
            add_message(f"Camera module error: {e}")
