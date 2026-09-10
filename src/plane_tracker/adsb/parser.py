import time
from datetime import datetime



def parse_aircraft(aircraft):
    hex_code = aircraft.get("hex", "").upper().strip()
    if not hex_code:
        return None

    lat = aircraft.get("lat")
    lon = aircraft.get("lon")
    if lat is None or lon is None:
        lat = "-"
        lon = "-"
    else:
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            lat = "-"
            lon = "-"

    altitude = aircraft.get("alt_baro")
    if altitude is None:
        altitude = aircraft.get("alt_geom")
    if altitude is not None:
        try:
            altitude = int(altitude)
        except (TypeError, ValueError):
            altitude = "-"
    else:
        altitude = "-"

    speed = aircraft.get("gs")
    if speed is not None:
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            speed = "-"
    else:
        speed = "-"

    track = aircraft.get("track")
    if track is not None:
        try:
            track = float(track)
        except (TypeError, ValueError):
            track = "-"
    else:
        track = "-"

    flight = aircraft.get("flight", "-")
    if flight is not None:
        flight = str(flight).strip() or "-"
    else:
        flight = "-"

    baro_rate = aircraft.get("baro_rate")
    if baro_rate is not None:
        try:
            baro_rate = int(baro_rate)
        except (TypeError, ValueError):
            baro_rate = "-"
    else:
        baro_rate = "-"

    def _num(val, cast=float):
        if val is None:
            return "-"
        try:
            return cast(val)
        except (TypeError, ValueError):
            return "-"

    return {
        'icao': hex_code,
        'flight': flight,
        'squawk': aircraft.get('squawk') or '-',
        'category': aircraft.get('category') or '-',
        'emergency': aircraft.get('emergency') or '-',
        'altitude': altitude,
        'alt_geom': _num(aircraft.get('alt_geom'), int),
        'baro_rate': baro_rate,
        'geom_rate': _num(aircraft.get('geom_rate'), int),
        'speed': speed,
        'ias': _num(aircraft.get('ias'), int),
        'tas': _num(aircraft.get('tas'), int),
        'mach': _num(aircraft.get('mach')),
        'track': track,
        'track_rate': _num(aircraft.get('track_rate')),
        'mag_heading': _num(aircraft.get('mag_heading')),
        'true_heading': _num(aircraft.get('true_heading')),
        'nav_heading': _num(aircraft.get('nav_heading')),
        'nav_altitude_fms': _num(aircraft.get('nav_altitude_fms'), int),
        'nav_altitude_mcp': _num(aircraft.get('nav_altitude_mcp'), int),
        'nav_qnh': _num(aircraft.get('nav_qnh')),
        'nav_modes': str(aircraft.get('nav_modes') or '-'),
        'roll': _num(aircraft.get('roll')),
        'oat': _num(aircraft.get('oat'), int),
        'tat': _num(aircraft.get('tat'), int),
        'wd': _num(aircraft.get('wd'), int),
        'ws': _num(aircraft.get('ws'), int),
        'rssi': _num(aircraft.get('rssi')),
        'seen': _num(aircraft.get('seen')),
        'seen_pos': _num(aircraft.get('seen_pos')),
        'messages': _num(aircraft.get('messages'), int),
        'lat': lat,
        'lon': lon,
        'manufacturer': '-',
        'registration': '-',
        'owner': '-',
        'model': '-',
        'icao_type_code': '-',
        'code_mode_s': '-',
        'operator_flag': '-',
        'spotted_at': datetime.now().strftime('%H:%M:%S'),
        'last_update_time': time.time(),
    }

