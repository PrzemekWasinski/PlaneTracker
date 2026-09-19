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
