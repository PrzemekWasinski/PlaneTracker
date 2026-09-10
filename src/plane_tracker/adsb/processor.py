
def adsb_processing_thread():
    global is_receiving, is_processing, tracker_running, offline, network_available

    last_stats_upload = time.time()
    last_network_check = time.time()
    last_flight_history_save = time.time()
    readsb_connected = False


    #Run CSV work outside the render thread
    bg_pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    flight_history_future = None
    stats_future = None

    while tracker_running:
        current_time = time.time()


        if current_time - last_network_check > 30:
            network_available = check_network()
            if not network_available and not offline:
                add_message("Network down switching to Offline")
            last_network_check = current_time

        is_receiving = True
        try:
            with open(READSB_JSON_PATH, "r") as f:
                data = json.load(f)

            if not readsb_connected:
                add_message(f"Connected to readsb at {READSB_JSON_PATH}")
                readsb_connected = True

            aircraft_list = data.get("aircraft", [])
            current_api_count = get_api_request_count_5min()

            for aircraft in aircraft_list:
                plane_data = functions.parse_aircraft(aircraft)
                if not plane_data or plane_data["lon"] == "-" or plane_data["lat"] == "-":
                    continue

                icao = plane_data['icao']
                effective_offline = offline or not network_available

                is_new_plane = False
                current_epoch = time.time()
                current_messages = plane_data.get("messages")
                current_seen = plane_data.get("seen")
                with data_lock:
                    if icao in active_planes:
                        cached = active_planes[icao]
                        plane_data["manufacturer"] = cached.get("manufacturer", "-")
                        plane_data["registration"] = cached.get("registration", "-")
                        plane_data["owner"] = cached.get("owner", "-")
                        plane_data["model"] = cached.get("model", "-")
                        plane_data["last_api_error"] = cached.get("last_api_error", 0)
                        plane_data["api_retry_count"] = cached.get("api_retry_count", 0)
                        plane_data["api_retries_exhausted"] = cached.get("api_retries_exhausted", False)
                        if "last_lat" in cached:
                            plane_data["prev_lat"] = cached["last_lat"]
                            plane_data["prev_lon"] = cached["last_lon"]
                            plane_data["prev_update_time"] = cached.get("last_update_time")
                            plane_data["prev_altitude"] = cached.get("altitude")


                        plane_data["location_history"] = cached.get("location_history", {})
                        plane_data["altitude_history"] = cached.get("altitude_history", deque())
                        plane_data["hit_history"] = cached.get("hit_history", deque())
                        plane_data["last_hit_bucket"] = cached.get("last_hit_bucket")
                        plane_data["last_hit_count"] = cached.get("last_hit_count", 0)
                        plane_data["total_hit_count"] = cached.get("total_hit_count", 0)
                        plane_data["last_message_count"] = cached.get("last_message_count", cached.get("messages"))
                    else:
                        is_new_plane = True
                        plane_data["manufacturer"] = "-"
                        plane_data["registration"] = "-"
                        plane_data["owner"] = "-"
                        plane_data["model"] = "-"
                        plane_data["last_api_error"] = 0
                        plane_data["api_retry_count"] = 0
                        plane_data["api_retries_exhausted"] = False
                        plane_data["location_history"] = {}
                        plane_data["altitude_history"] = deque()
                        plane_data["hit_history"] = deque()
                        plane_data["last_hit_bucket"] = None
                        plane_data["last_hit_count"] = 0
                        plane_data["total_hit_count"] = 0
                        plane_data["last_message_count"] = None

                    previous_messages = plane_data.get("last_message_count")
                    if isinstance(current_messages, int):
                        has_new_hit = previous_messages != current_messages
                    elif current_seen != "-":
                        try:
                            has_new_hit = float(current_seen) <= 1.5
                        except (TypeError, ValueError):
                            has_new_hit = is_new_plane
                    else:
                        has_new_hit = is_new_plane

                    if is_new_plane and not has_new_hit:
                        continue

                    if not has_new_hit:
                        plane_data["last_lat"] = cached.get("last_lat", plane_data["lat"])
                        plane_data["last_lon"] = cached.get("last_lon", plane_data["lon"])
                        plane_data["last_update_time"] = cached.get("last_update_time", current_epoch)
                        active_planes[icao] = plane_data
                        continue

                    plane_data["last_lat"] = float(plane_data["lat"])
                    plane_data["last_lon"] = float(plane_data["lon"])
                    plane_data["last_update_time"] = current_epoch
                    plane_data["last_message_count"] = current_messages if isinstance(current_messages, int) else previous_messages
                    current_timestamp = plane_data.get("spotted_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    history_timestamp = f"{current_epoch:.6f}"
                    plane_data["history_timestamp"] = history_timestamp
                    bearing = functions.calculate_bearing(_config['myLat'], _config['myLon'], plane_data["last_lat"], plane_data["last_lon"])
                    append_directional_hit(directional_hit_history, bearing, PLANE_HIT_SAMPLE_INTERVAL, DIRECTIONAL_SECTOR_COUNT, current_epoch)
                    prune_history(directional_hit_history, DIRECTIONAL_HISTORY_SECONDS, current_epoch)

                    if plane_data["lat"] != "-" and plane_data["lon"] != "-":
                        plane_data["location_history"][history_timestamp] = [float(plane_data["lat"]), float(plane_data["lon"])]

                    altitude_value = plane_data.get("altitude")
                    if altitude_value not in (None, "-"):
                        try:
                            altitude_value = float(altitude_value)
                            append_sample(plane_data["altitude_history"], altitude_value, PLANE_ALTITUDE_SAMPLE_INTERVAL, current_epoch)
                            prune_history(plane_data["altitude_history"], PLANE_GRAPH_HISTORY_SECONDS, current_epoch)
                        except (TypeError, ValueError):
                            pass

                    hit_bucket = int(current_epoch // PLANE_HIT_SAMPLE_INTERVAL) * PLANE_HIT_SAMPLE_INTERVAL
                    if plane_data.get("last_hit_bucket") == hit_bucket:
                        plane_data["last_hit_count"] += 1
                        if plane_data["hit_history"] and plane_data["hit_history"][-1][0] == hit_bucket:
                            plane_data["hit_history"][-1] = (hit_bucket, plane_data["last_hit_count"])
                        else:
                            plane_data["hit_history"].append((hit_bucket, plane_data["last_hit_count"]))
                    else:
                        plane_data["last_hit_bucket"] = hit_bucket
                        plane_data["last_hit_count"] = 1
                    plane_data["total_hit_count"] = plane_data.get("total_hit_count", 0) + 1
                    prune_history(plane_data["hit_history"], PLANE_GRAPH_HISTORY_SECONDS, current_epoch)

                    active_planes[icao] = plane_data
                    displayed_planes[icao] = {
                        "plane_data": plane_data,
                        "display_until": time.time() + display_duration
                    }

                if is_new_plane:
                    cache_entry = icao_cache.get(icao)
                    if cache_entry and (time.time() - cache_entry.get('cached_at', 0)) < ICAO_CACHE_MAX_AGE_DAYS * 86400:
                        for field in ('manufacturer', 'model', 'owner', 'registration'):
                            if field in cache_entry:
                                plane_data[field] = cache_entry[field]
                        active_planes[icao] = plane_data
                        displayed_planes[icao]["plane_data"] = plane_data
                        if plane_data.get('manufacturer', '-') != '-' and plane_data.get('owner', '-') != '-':
                            save_plane_to_csv(icao, plane_data)
                    add_message(f"NEW plane {icao}")

                if not effective_offline and plane_data["manufacturer"] == "-" and not plane_data.get("api_retries_exhausted") and icao not in api_pending and can_retry_plane_api(plane_data, PLANE_API_RETRY_DELAY) and current_api_count < API_RATE_LIMIT_MAX:
                    api_pending.add(icao)
                    current_api_count += 1
                    threading.Thread(target=api_worker_thread, args=(icao, plane_data), daemon=True).start()

        except FileNotFoundError:
            if readsb_connected:
                add_message(f"readsb unavailable: {READSB_JSON_PATH} not found")
                readsb_connected = False
            time.sleep(3)
            is_receiving = False
            continue
        except Exception as e:
            log.error(f"ADSB loop error: {e}")
            add_message(f"ADSB loop error: {str(e)[:40]}")
            readsb_connected = False
            time.sleep(1)
            is_receiving = False
            continue


        current_time = time.time()
        with data_lock:
            old_planes = [icao for icao, d in displayed_planes.items() if d["display_until"] < current_time]
            for icao in old_planes:
                del displayed_planes[icao]

            stale_active_planes = [
                icao for icao, plane in active_planes.items()
                if current_time - plane.get("last_update_time", current_time) > ACTIVE_PLANE_RETENTION_SECONDS
            ]
            for icao in stale_active_planes:
                del active_planes[icao]
                tracker_plane_photo_cache.pop(icao, None)
                tracker_plane_photo_meta_cache.pop(icao, None)
                planecam_auto_capture_last_time.pop(icao, None)

        if flight_history_future is not None and flight_history_future.done():
            _fh_error = flight_history_future.exception()
            if _fh_error is not None:
                add_message(f"Flight history save error: {str(_fh_error)[:60]}")
            flight_history_future = None

        if current_time - last_flight_history_save >= 60 and flight_history_future is None:
            with data_lock:
                planes_snapshot = {icao: dict(plane) for icao, plane in active_planes.items()}
            for _plane in planes_snapshot.values():
                _plane['rating'] = get_rarity_rating(_plane.get('model', '-'), model_ratings)
            flight_history_future = bg_pool.submit(save_flight_history, planes_snapshot, FLIGHT_HISTORY_DIR)
            last_flight_history_save = current_time

        if stats_future is not None and stats_future.done():
            try:
                new_stats = stats_future.result()
            except Exception as e:
                new_stats = None
                log.error(f"Stats upload error: {e}")
                add_message(f"Stats upload error: {str(e)[:30]}")
            stats_future = None

            try:
                total = new_stats.get('total', 0) if new_stats else 0
                if total > 0:
                    _update_flight_stats_cache(new_stats)
                    if _stats_uploader is not None:
                        _stats_uploader(new_stats)
                        add_message(f"Firebase updated: {total} aircraft")
            except Exception as e:
                log.error(f"Stats upload error: {e}")
                add_message(f"Stats upload error: {str(e)[:30]}")

        if current_time - last_stats_upload > 60 and not offline and network_available and stats_future is None:
            stats_future = bg_pool.submit(functions.get_stats, _config['myLat'], _config['myLon'], FLIGHT_HISTORY_DIR)
            last_stats_upload = current_time

        is_receiving = False
        time.sleep(1)
