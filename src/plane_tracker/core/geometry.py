import math


def coords_to_xy(lat, lon, range_km, centre_lat, centre_lon, screen_width, screen_height, center_x=None, center_y=None, projection_lat=None):
    if center_x is None:
        center_x = screen_width // 2
    if center_y is None:
        center_y = screen_height // 2

    km_per_px = (range_km * 2) / 1024
    delta_lat = lat - centre_lat
    delta_lon = lon - centre_lon
    dy = delta_lat * 111
    if projection_lat is None:
        projection_lat = centre_lat
    dx = delta_lon * 111 * math.cos(math.radians(projection_lat))
    x = center_x + int(dx / km_per_px)
    y = center_y - int(dy / km_per_px)
    return x, y


def calculate_distance(lat1, lon1, lat2, lon2):
    try:
        earth_radius_km = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return round(earth_radius_km * c, 1)
    except Exception:
        return 0.0


def calculate_heading(lat1, lon1, lat2, lon2):
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    y = math.sin(lon2_rad - lon1_rad) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(lon2_rad - lon1_rad)
    return -math.degrees(math.atan2(y, x))


def calculate_bearing(lat1, lon1, lat2, lon2):
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lon_rad = math.radians(lon2 - lon1)
    y = math.sin(delta_lon_rad) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon_rad)
    return (math.degrees(math.atan2(y, x)) + 360) % 360
