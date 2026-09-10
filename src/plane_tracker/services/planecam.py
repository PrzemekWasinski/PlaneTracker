def prune_tracker_photo_cache_locked(preserve_icao=None):
    if preserve_icao and preserve_icao in tracker_plane_photo_cache:
        tracker_plane_photo_cache[preserve_icao] = tracker_plane_photo_cache.pop(preserve_icao)
    if preserve_icao and preserve_icao in tracker_plane_photo_meta_cache:
        tracker_plane_photo_meta_cache[preserve_icao] = tracker_plane_photo_meta_cache.pop(preserve_icao)

    while len(tracker_plane_photo_cache) > TRACKER_PHOTO_CACHE_LIMIT:
        oldest_icao = next(iter(tracker_plane_photo_cache))
        if preserve_icao and oldest_icao == preserve_icao and len(tracker_plane_photo_cache) > 1:
            tracker_plane_photo_cache[oldest_icao] = tracker_plane_photo_cache.pop(oldest_icao)
            if oldest_icao in tracker_plane_photo_meta_cache:
                tracker_plane_photo_meta_cache[oldest_icao] = tracker_plane_photo_meta_cache.pop(oldest_icao)
            oldest_icao = next(iter(tracker_plane_photo_cache))
        del tracker_plane_photo_cache[oldest_icao]
        tracker_plane_photo_meta_cache.pop(oldest_icao, None)


def build_tracker_image_path(target_icao):
    hex_code = ''.join(ch for ch in str(target_icao or 'UNKNOWN').upper() if ch.isalnum()) or 'UNKNOWN'
    timestamp = datetime.now().strftime('%d-%m-%Y_%H-%M-%S')
    return TRACKER_IMAGE_DIR / f"{hex_code}_{timestamp}.jpg"


def save_tracker_image(image_bytes, target_icao):
    output_path = build_tracker_image_path(target_icao)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)
    return output_path


def api_worker_thread(icao, plane_data):
    try:
        api_request_timestamps.append(time.time())
        api_data = fetch_plane_info(icao)
        if api_data is None:

            with data_lock:
                if icao in active_planes:
                    active_planes[icao]['api_retries_exhausted'] = True
        elif api_data.get('last_api_error'):

            error_msg = api_data.get('api_error_msg', 'API error')
            add_message(f"{error_msg}")
            with data_lock:
                if icao in active_planes:
                    retry_count = active_planes[icao].get('api_retry_count', 0) + 1
                    active_planes[icao]['api_retry_count'] = retry_count
                    active_planes[icao]['last_api_error'] = api_data['last_api_error']
                    if retry_count >= 3:
                        active_planes[icao]['api_retries_exhausted'] = True
                if icao in displayed_planes:
                    displayed_planes[icao]['plane_data']['last_api_error'] = api_data['last_api_error']
        else:

            plane_snapshot = None
            with data_lock:
                if icao in active_planes:
                    active_planes[icao].update(api_data)
                    plane_snapshot = dict(active_planes[icao])
                if icao in displayed_planes:
                    displayed_planes[icao]["plane_data"].update(api_data)
            if plane_snapshot and api_data.get("manufacturer") and api_data.get("manufacturer") != "-":
                save_plane_to_csv(icao, plane_snapshot)
                save_icao_cache_entry(icao, api_data)
                _model = api_data.get('model', '-')
                if _model and _model != '-':
                    model_counts[_model] = model_counts.get(_model, 0) + 1
                    _new_ratings = compute_ratings(model_counts)
                    model_ratings.clear()
                    model_ratings.update(_new_ratings)
    finally:
        api_pending.discard(icao)


_tracker_stats_link_ok = False


def fetch_tracker_stats(log_result=False):
    global tracker_device_stats, _tracker_stats_link_ok
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(CAMERA_SERVER)
        sock.sendall(b'stats')
        response = sock.recv(1024).decode().strip()
        sock.close()

        temp_text, ram_text, cpu_text, disk_text = response.split(',', 3)
        parsed_stats = {
            'temp': float(temp_text),
            'ram': float(ram_text),
            'cpu': float(cpu_text),
            'disk': float(disk_text),
        }

        with data_lock:
            tracker_device_stats = parsed_stats

        was_connected = _tracker_stats_link_ok
        _tracker_stats_link_ok = True
        if log_result and not was_connected:
            add_message('Connected to camera module')
    except Exception as error:
        was_connected = _tracker_stats_link_ok
        _tracker_stats_link_ok = False
        with data_lock:
            tracker_device_stats = {'temp': None, 'ram': None, 'cpu': None, 'disk': None}
        if log_result or was_connected:
            add_message(format_service_connection_error('Camera module', CAMERA_SERVER, error))


def tracker_stats_thread():
    first_check = True
    while tracker_running:
        fetch_tracker_stats(log_result=first_check)
        first_check = False
        time.sleep(5)




TRACKER_PING_INTERVAL = 10.0


def ping_tracker_host(host, timeout=2):
    try:
        if sys.platform.startswith('win'):
            cmd = ['ping', '-n', '1', '-w', str(int(timeout * 1000)), host]
        else:
            cmd = ['ping', '-c', '1', '-W', str(int(timeout)), host]
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout + 1
        )
        return result.returncode == 0
    except Exception:
        return False


def tracker_ping_thread():
    global tracker_status_connected
    while tracker_running:
        reachable = ping_tracker_host(CAMERA_SERVER[0])
        with data_lock:
            tracker_status_connected = reachable
        time.sleep(TRACKER_PING_INTERVAL)


def receive_tracker_line(sock):
    header = bytearray()
    while True:
        chunk = sock.recv(1)
        if not chunk:
            break
        if chunk == b'\n':
            break
        header.extend(chunk)
    return header.decode(errors='ignore').strip()


def receive_tracker_bytes(sock, byte_count):
    payload = bytearray()
    while len(payload) < byte_count:
        chunk = sock.recv(min(4096, byte_count - len(payload)))
        if not chunk:
            raise ConnectionError('camera module closed connection during image transfer')
        payload.extend(chunk)
    return bytes(payload)


def refresh_tracker_photo_surface():
    global tracker_photo_surface, tracker_photo_dirty, tracker_photo_status
    global tracker_photo_bytes, tracker_pending_photo_plane_icao, tracker_plane_photo_meta_cache
    global tracker_plane_photo_history

    pending_bytes = None
    pending_plane_icao = None
    with data_lock:
        if tracker_photo_dirty and tracker_photo_bytes is not None:
            pending_bytes = tracker_photo_bytes
            pending_plane_icao = tracker_pending_photo_plane_icao
            tracker_photo_dirty = False
            tracker_photo_bytes = None
            tracker_pending_photo_plane_icao = None

    if pending_bytes is None:
        return

    try:
        loaded_surface = pygame.image.load(io.BytesIO(pending_bytes), 'camera.jpg').convert()
    except Exception as error:
        with data_lock:
            tracker_photo_status = 'Image decode failed'
        add_message(f'Camera image decode failed: {error}')
        return

    with data_lock:
        tracker_photo_surface = loaded_surface
        if pending_plane_icao:
            tracker_plane_photo_cache[pending_plane_icao] = loaded_surface
            tracker_plane_photo_meta_cache[pending_plane_icao] = dict(tracker_photo_meta)
            prune_tracker_photo_cache_locked(preserve_icao=pending_plane_icao)
            _pending_meta_snapshot = dict(tracker_photo_meta)

    if pending_plane_icao:
        if pending_plane_icao not in tracker_plane_photo_history:
            tracker_plane_photo_history[pending_plane_icao] = []
        _history = tracker_plane_photo_history[pending_plane_icao]
        _history.insert(0, (loaded_surface, _pending_meta_snapshot))
        if len(_history) > TRACKER_PLANE_PHOTO_HISTORY_LIMIT:
            _history.pop()


def predict_tracker_target(plane_data):
    try:
        lat = float(plane_data.get('last_lat'))
        lon = float(plane_data.get('last_lon'))
        alt_ft = float(plane_data.get('altitude'))
    except (TypeError, ValueError):
        return None

    last_update_time = plane_data.get('last_update_time')
    prev_update_time = plane_data.get('prev_update_time')
    prev_lat = plane_data.get('prev_lat')
    prev_lon = plane_data.get('prev_lon')
    prev_alt_ft = plane_data.get('prev_altitude')

    if not isinstance(last_update_time, (int, float)):
        return lat, lon, alt_ft, 0.0

    sample_age = max(0.0, time.time() - last_update_time)
    if sample_age > TRACKER_MAX_SAMPLE_AGE_SECONDS:
        return lat, lon, alt_ft, 0.0

    lead_seconds = min(TRACKER_MAX_EXTRAPOLATION_SECONDS, TRACKER_PREDICTION_SECONDS + sample_age)

    if not isinstance(prev_update_time, (int, float)):
        return lat, lon, alt_ft, lead_seconds

    try:
        prev_lat = float(prev_lat)
        prev_lon = float(prev_lon)
        prev_alt_ft = alt_ft if prev_alt_ft in (None, '-') else float(prev_alt_ft)
    except (TypeError, ValueError):
        return lat, lon, alt_ft, lead_seconds

    dt = last_update_time - prev_update_time
    if dt <= 0.0 or dt > TRACKER_MAX_SAMPLE_AGE_SECONDS:
        return lat, lon, alt_ft, lead_seconds

    scale = lead_seconds / dt
    predicted_lat = lat + (lat - prev_lat) * scale
    predicted_lon = lon + (lon - prev_lon) * scale
    predicted_alt_ft = alt_ft + (alt_ft - prev_alt_ft) * scale
    return predicted_lat, predicted_lon, predicted_alt_ft, lead_seconds


def send_to_tracker(lat, lon, alt_ft, target_icao=None, add_message_callback=None):
    global tracker_capture_in_progress
    global tracker_photo_bytes, tracker_photo_dirty, tracker_photo_status, tracker_photo_plane_icao, tracker_pending_photo_plane_icao, tracker_photo_meta, tracker_plane_photo_meta_cache

    logger = add_message_callback or add_message
    sock = None

    try:
        alt_m = alt_ft * 0.3048
        logger(f'Sending position data to camera module at {CAMERA_SERVER[0]}:{CAMERA_SERVER[1]}')
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(20)
        sock.connect(CAMERA_SERVER)
        hex_code = target_icao or 'UNKNOWN'
        message = f"{hex_code},{lat},{lon},{alt_m}"
        sock.sendall(message.encode())

        header = receive_tracker_line(sock)
        if not header:
            raise ConnectionError('camera module sent no response')

        if header.startswith('IMAGE '):
            header_parts = header.split()
            image_size = int(header_parts[1])
            image_meta = {}
            for token in header_parts[2:]:
                if '=' in token:
                    key, value = token.split('=', 1)
                    image_meta[key] = value
            image_bytes = receive_tracker_bytes(sock, image_size)
            saved_image_path = None
            save_error = None
            try:
                saved_image_path = save_tracker_image(image_bytes, target_icao)
            except Exception as error:
                save_error = error

            label = image_meta.get('label', 'UNKNOWN')
            aircraft = image_meta.get('aircraft', 'unknown')
            confidence = image_meta.get('confidence')
            raw_score = image_meta.get('raw_score')
            score_margin = image_meta.get('score_margin')
            detail = image_meta.get('detail')
            predictor = image_meta.get('predictor')
            classification_bits = [f"label={label}", f"aircraft={aircraft}"]
            if confidence is not None:
                classification_bits.append(f"confidence={confidence}")
            if raw_score is not None:
                classification_bits.append(f"raw_score={raw_score}")
            if score_margin is not None:
                classification_bits.append(f"score_margin={score_margin}")
            if predictor is not None:
                classification_bits.append(f"predictor={predictor}")
            if detail is not None:
                classification_bits.append(f"detail={detail}")
            classification_text = ', '.join(classification_bits)

            image_meta['target_icao'] = target_icao or 'UNKNOWN'
            image_meta['received_at'] = datetime.now().strftime('%H:%M:%S')
            if saved_image_path is not None:
                image_meta['saved_name'] = saved_image_path.name

            with data_lock:
                tracker_photo_bytes = image_bytes
                tracker_photo_dirty = True
                tracker_pending_photo_plane_icao = target_icao
                tracker_photo_plane_icao = target_icao
                tracker_photo_meta = dict(image_meta)
                tracker_photo_status = (f"Image received for {target_icao} ({classification_text})"
                                        if target_icao else f"Image received ({classification_text})")
                if target_icao:
                    tracker_plane_photo_meta_cache[target_icao] = dict(image_meta)
            if save_error is not None:
                logger(f"Image save failed: {save_error}")
            elif saved_image_path is not None:
                logger(f"Camera image saved: {saved_image_path.name}")
            logger(f"Camera image received: {classification_text}")
        elif header == 'BUSY':
            with data_lock:
                tracker_photo_status = 'Camera busy'
            logger('Camera module busy')
        elif header.startswith('ERROR'):
            detail = header.split(' ', 1)[1] if ' ' in header else 'unknown_error'
            with data_lock:
                tracker_photo_status = f"Camera error: {detail.replace('_', ' ')}"
            logger(f"Camera module error: {detail}")
        else:
            with data_lock:
                tracker_photo_status = f"Unexpected response: {header}"
            logger(f"Camera module response: {header}")
    except Exception as error:
        with data_lock:
            tracker_photo_status = 'Camera unavailable'
        logger(format_service_connection_error('Camera module', CAMERA_SERVER, error))
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        with data_lock:
            tracker_capture_in_progress = False
        if tracker_request_lock.locked():
            tracker_request_lock.release()


def begin_camera_tracking(target_icao, logger=None, auto_select=False):
    if runtime_mode == "preview":
        (logger or add_message)(f"Preview simulated camera tracking for {target_icao}")
        return True
    global selected_plane_icao, tracker_capture_in_progress, tracker_photo_status, tracker_photo_plane_icao

    logger = logger or add_message
    if not tracker_request_lock.acquire(blocking=False):
        logger('Camera module busy')
        return False

    try:
        with data_lock:
            if tracker_capture_in_progress:
                logger('Camera module busy')
                return False

            display_data = displayed_planes.get(target_icao)
            if not display_data:
                logger('No target plane available for tracking')
                return False

            plane_data = display_data.get('plane_data', {})
            predicted_target = predict_tracker_target(plane_data)
            if predicted_target is None:
                logger('Target plane altitude unknown, cannot track')
                return False

            lat, lon, alt_ft, lead_seconds = predicted_target

            tracker_capture_in_progress = True
            tracker_photo_status = f"Capturing {target_icao}"
            tracker_photo_plane_icao = target_icao

        if auto_select:
            with data_lock:
                _has_manual_selection = selected_plane_icao is not None and selected_plane_icao in displayed_planes
            if not _has_manual_selection:
                selected_plane_icao = target_icao

        threading.Thread(target=send_to_tracker, args=(lat, lon, float(alt_ft), target_icao, logger), daemon=True).start()
        logger(f"Aiming camera at {target_icao} using {lead_seconds:.1f}s lead")
        return True
    except Exception:
        with data_lock:
            tracker_capture_in_progress = False
        tracker_request_lock.release()
        raise


def build_auto_track_rect(range_km, centre_lat, centre_lon, projection_lat=None):
    if not AUTO_TRACK_CONFIGURED:
        return None

    projected_points = []
    for lat_key, lon_key in AUTO_TRACK_POLYGON_KEYS:
        projected_points.append(
            functions.coords_to_xy(
                float(_config[lat_key]),
                float(_config[lon_key]),
                range_km,
                centre_lat,
                centre_lon,
                width,
                height,
                RADAR_CENTER_X,
                RADAR_CENTER_Y,
                projection_lat,
            )
        )

    xs = [point_x for point_x, _ in projected_points]
    ys = [point_y for _, point_y in projected_points]
    left = int(min(xs))
    top = int(min(ys))
    rect_width = max(1, int(math.ceil(max(xs) - left)))
    rect_height = max(1, int(math.ceil(max(ys) - top)))
    return pygame.Rect(left, top, rect_width, rect_height)

