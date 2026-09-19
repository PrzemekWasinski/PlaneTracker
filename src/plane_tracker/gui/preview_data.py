def initialise_preview_state():

    global active_planes, displayed_planes, message_queue
    global _flight_stats_cache
    now = time.time()

    base_lat = float(_config['myLat'])
    base_lon = float(_config['myLon'])

    def preview_model_for_rating(target_rating, fallback):
        candidates = [
            model for model, rating in model_ratings.items()
            if rating == target_rating
        ]
        if not candidates:
            return fallback
        return min(candidates, key=lambda model: (-model_counts.get(model, 0), model))

    standard_model = preview_model_for_rating(1, "737-800")
    common_model = preview_model_for_rating(4, "A320")
    uncommon_model = preview_model_for_rating(6, "A321neo")
    rare_model = preview_model_for_rating(8, "172")
    samples = (
        ("4CA123", "BAW123", 0.25, 0.15, 35000, 450, 90, "Boeing", standard_model, "G-TEST1", "British Airways", 28.5),
        ("3C4567", "DLH456", -0.10, 0.30, 12000, 280, 180, "Airbus", common_model, "D-AIAB", "Lufthansa", 23.4),
        ("407ABC", "EZY789", 0.08, -0.20, 24000, 390, 315, "Airbus", uncommon_model, "G-UZHA", "easyJet", 18.1),
        ("A1B2C3", "N123EX", -0.30, -0.12, 6500, 145, 45, "Cessna", rare_model, "N123EX", "Private", 35.8),
    )
    preview_planes = {}
    for index, (icao, flight, lat_delta, lon_delta, altitude, speed, track, manufacturer, model, registration, owner, distance) in enumerate(samples):
        history = {
            f"{now - seconds:.6f}": [base_lat + lat_delta - lat_delta * seconds / 900, base_lon + lon_delta - lon_delta * seconds / 900]
            for seconds in (240, 180, 120, 60, 0)
        }
        plane = {
            "icao": icao, "flight": flight, "callsign": flight,
            "lat": base_lat + lat_delta, "lon": base_lon + lon_delta,
            "last_lat": base_lat + lat_delta, "last_lon": base_lon + lon_delta,
            "prev_lat": base_lat + lat_delta * 0.98, "prev_lon": base_lon + lon_delta * 0.98,
            "last_update_time": now,
            "altitude": str(altitude), "speed": str(speed), "track": str(track),
            "vertical_rate": str((index - 1) * 320), "squawk": "7000",
            "manufacturer": manufacturer, "model": model,
            "registration": registration, "owner": owner,
            "distance": distance, "location_history": history,
            "altitude_history": deque((now - i * 60, altitude - i * 250) for i in range(8, -1, -1)),
            "hit_history": deque((int(now // 60) * 60 - i * 60, 3 + ((i + index) % 8)) for i in range(8, -1, -1)),
            "last_hit_bucket": int(now // 60) * 60, "last_hit_count": 7 + index,
            "total_hit_count": 84 - index * 13,
        }
        preview_planes[icao] = plane
    active_planes = preview_planes
    displayed_planes = {
        icao: {"plane_data": plane, "display_until": now + 86400}
        for icao, plane in preview_planes.items()
    }
    message_queue.clear()
    for text in (
        "Connected to readsb receiver",
        "NEW plane 4CA123",
        "NEW plane 3C4567",
        "NEW plane 407ABC",
    ):
        add_message(text)
    active_count_history.clear()
    total_seen_history.clear()
    for i in range(24, -1, -1):
        active_count_history.append((now - i * 180, 2 + (i * 3) % 13))
        total_seen_history.append((now - i * 180, 96 + (24 - i) * 3))
    _flight_stats_cache = {
        'total': 168, 'top_model': {'name': 'A320', 'count': 31},
        'top_manufacturer': {'name': 'Airbus', 'count': 72},
        'top_aircraft': {'name': 'A320', 'count': 31},
        'top_airline': {'name': 'British Airways', 'count': 28},
        'manufacturer_breakdown': {'Airbus': 72, 'Boeing': 61},
        'furthest_detected': 241.8, 'highest_detected': 41000,
        'unique_airlines': 22, 'unique_models': 34, 'unique_manufacturers': 12,
        'emergencies_count': 0, 'avg_altitude': 26750, 'avg_speed': 384,
        'max_speed': 552, 'max_hits': 84, 'avg_mach': 0.67, 'last_updated': datetime.now().isoformat(),
    }

