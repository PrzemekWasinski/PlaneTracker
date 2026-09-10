def draw_radar():
        global camera_scroll_offset, closest_plane, displayed_count
        global displayed_planes_snapshot, target_icao
        global plane_rects, selected_plane_icao, view_center_lat, view_center_lon
        global _prev_target_icao_for_scroll

        displayed_planes_snapshot = snapshot_displayed_planes()

        refresh_tracker_photo_surface()

        if follow_selected_plane:
            followed_position = _active_plane_position(
                displayed_planes_snapshot.get(selected_plane_icao), current_time
            )
            if followed_position is None:
                selected_plane_icao, followed_position = _closest_active_plane(
                    displayed_planes_snapshot, current_time
                )
            if followed_position is not None:
                view_center_lat, view_center_lon = followed_position


        pygame.draw.rect(window, (0, 0, 0), (0, 0, width, height))


        window.set_clip(RADAR_RECT)

        home_x, home_y = functions.coords_to_xy(
            _config['myLat'], _config['myLon'], range_km,
            view_center_lat, view_center_lon, width, height,
            RADAR_CENTER_X, RADAR_CENTER_Y, _config['myLat']
        )
        radar_map_source, radar_map_range = _radar_map_for_view(
            range_km, view_center_lat, view_center_lon
        )
        radar_map_image = None
        radar_map_position = RADAR_RECT.topleft
        if radar_map_source is not None:
            radar_map_image = _render_radar_map_view(
                radar_map_source, radar_map_range, range_km,
                view_center_lat, view_center_lon,
            )
        if radar_map_image is not None:
            window.blit(radar_map_image, radar_map_position)
        else:
            pygame.draw.rect(window, (0, 0, 0), RADAR_RECT)


        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 100, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 200, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 300, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 400, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 500, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 600, 1)


        range_steps = [100, 200, 300, 400, 500, 600]
        cos_45 = math.cos(math.radians(45))

        for radius in range_steps:
            label_x = RADAR_CENTER_X - (radius * cos_45)
            label_y = RADAR_CENTER_Y - (radius * cos_45)
            circle_distance_km = range_km * (radius / 600.0)
            label_value = convert_distance_from_km(circle_distance_km, distance_unit)
            label_text = str(round(label_value)) if label_value is not None else '-'
            draw_text.normal(window, label_text, text_font3, (225, 225, 225), int(label_x), int(label_y))

        auto_track_rect = build_auto_track_rect(range_km, view_center_lat, view_center_lon, _config['myLat'])
        if auto_track_rect is not None:
            rect_colour = (0, 255, 0) if tracking_mode_auto else (100, 100, 100)
            pygame.draw.rect(window, rect_colour, auto_track_rect, 1)


        pygame.draw.polygon(window, (0, 255, 255), [
            (home_x, home_y - 3),
            (home_x + 3, home_y),
            (home_x, home_y + 3),
            (home_x - 3, home_y)
        ])


        for key in airport_db.airports_uk:
            airport = airport_db.airports_uk[key]
            x, y = functions.coords_to_xy(airport["lat"], airport["lon"], range_km, view_center_lat, view_center_lon, width, height, RADAR_CENTER_X, RADAR_CENTER_Y, _config['myLat'])
            pygame.draw.polygon(window, (0, 0, 255), [(x, y - 2), (x + 2, y), (x, y + 2), (x - 2, y)])
            draw_text.center(window, airport["airport_name"], text_font3, (255, 255, 255), x, y - 10)

        displayed_count = 0
        closest_plane = None
        min_dist = float('inf')




        for icao, display_data in displayed_planes_snapshot.items():
            plane = display_data.get("plane_data", {})
            if not plane_matches_altitude_filter(plane, altitude_filter_threshold, altitude_filter_above):
                continue
            if rarity_filter_selected:
                _r = get_rarity_rating(plane.get('model', '-'), model_ratings)
                _t = 10 if _r >= 10 else (8 if _r >= 8 else (6 if _r >= 6 else (4 if _r >= 4 else 1)))
                if _t not in rarity_filter_selected:
                    continue
            lat = plane.get("last_lat")
            lon = plane.get("last_lon")
            if lat is not None and lon is not None:
                dist = functions.calculate_distance(
                    float(_config["myLat"]), float(_config["myLon"]),
                    float(lat), float(lon),
                )
                plane["distance"] = dist
                if distance_filter_threshold_km > 0:
                    if distance_filter_outside and dist < distance_filter_threshold_km:
                        continue
                    if not distance_filter_outside and dist > distance_filter_threshold_km:
                        continue
                if dist < min_dist:
                    min_dist = dist
                    closest_plane = icao
                displayed_count += 1


        window.set_clip(RADAR_RECT)


        current_plane_rects = {}
        current_auto_track_icaos = set()
        target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes_snapshot) else closest_plane

        for icao, display_data in displayed_planes_snapshot.items():
            plane = display_data["plane_data"]
            if not plane_matches_altitude_filter(plane, altitude_filter_threshold, altitude_filter_above):
                continue
            if not plane_matches_distance_filter(plane, distance_filter_threshold_km, distance_filter_outside):
                continue
            if rarity_filter_selected:
                _r = get_rarity_rating(plane.get('model', '-'), model_ratings)
                _t = 10 if _r >= 10 else (8 if _r >= 8 else (6 if _r >= 6 else (4 if _r >= 4 else 1)))
                if _t not in rarity_filter_selected:
                    continue
            lat = plane.get("last_lat")
            lon = plane.get("last_lon")
            if lat is None or lon is None:
                continue


            time_remaining = display_data["display_until"] - current_time
            if time_remaining <= 0:
                continue
            fade_value = max(10, int(255 * (time_remaining / fade_duration))) if time_remaining < fade_duration else 255

            try:
                if hide_planes_mode == 2:
                    continue


                x, y = functions.coords_to_xy(float(lat), float(lon), range_km, view_center_lat, view_center_lon, width, height, RADAR_CENTER_X, RADAR_CENTER_Y, _config['myLat'])


                track = plane.get("track")
                if track != "-" and track is not None:
                    try:
                        heading = -float(track)
                        plane_headings[icao] = heading
                    except ValueError:
                        heading = plane_headings.get(icao, 0.0)
                else:
                    prev_lat = plane.get("prev_lat")
                    prev_lon = plane.get("prev_lon")
                    if prev_lat is not None and prev_lon is not None and (abs(float(prev_lat) - float(lat)) > 1e-6 or abs(float(prev_lon) - float(lon)) > 1e-6):
                        heading = functions.calculate_heading(prev_lat, prev_lon, lat, lon)
                        plane_headings[icao] = heading
                    else:
                        heading = plane_headings.get(icao, 0.0)

                if tracking_mode_auto and auto_track_rect is not None and auto_track_rect.collidepoint(int(x), int(y)):
                    current_auto_track_icaos.add(icao)

                rating = get_rarity_rating(plane.get('model', '-'), model_ratings)
                rarity_col = get_rarity_colour(rating)

                if show_all_trajectories or icao == target_icao:
                    location_history = plane.get("location_history", {})
                    if location_history and isinstance(location_history, dict) and len(location_history) > 1:

                        sorted_coords = sorted(location_history.items())


                        current_lat = plane.get("last_lat")
                        current_lon = plane.get("last_lon")


                        trajectory_points = []
                        last_valid_lat = None
                        last_valid_lon = None

                        for timestamp, coords in sorted_coords:
                            try:
                                hist_lat, hist_lon = coords


                                if current_lat is not None and current_lon is not None:
                                    if abs(float(hist_lat) - float(current_lat)) < 0.0001 and abs(float(hist_lon) - float(current_lon)) < 0.0001:
                                        continue


                                if last_valid_lat is not None and last_valid_lon is not None:
                                    distance = functions.calculate_distance(last_valid_lat, last_valid_lon, float(hist_lat), float(hist_lon))
                                    #Ignore impossible jumps in trajectory data
                                    if distance > 100:
                                        add_message(f"Skipped invalid trajectory point: {distance:.1f}km jump")
                                        continue

                                hist_x, hist_y = functions.coords_to_xy(
                                    float(hist_lat), float(hist_lon), range_km,
                                    view_center_lat, view_center_lon,
                                    width, height, RADAR_CENTER_X, RADAR_CENTER_Y,
                                    _config['myLat']
                                )


                                if -500 <= hist_x <= width + 500 and -500 <= hist_y <= height + 500:
                                    trajectory_points.append((hist_x, hist_y))
                                    last_valid_lat = float(hist_lat)
                                    last_valid_lon = float(hist_lon)

                            except Exception as e:
                                add_message(f"Trajectory point error: {str(e)[:30]}")
                                continue


                        trajectory_points.append((int(x), int(y)))


                        if len(trajectory_points) > 1:
                            trajectory_col = tuple(max(0, c - 50) for c in rarity_col)
                            pygame.draw.lines(window, trajectory_col, False, trajectory_points)

                            for i in trajectory_points[:-1]:
                                pygame.draw.circle(window, (0, 255, 255), i, 1)

                coloured = plane_icon_white.copy()
                coloured.fill((*rarity_col, fade_value), special_flags=pygame.BLEND_RGBA_MULT)
                rotated_image = pygame.transform.rotate(coloured, heading)
                new_rect = rotated_image.get_rect(center=(x, y))
                window.blit(rotated_image, new_rect)
                current_plane_rects[icao] = new_rect


                if hide_planes_mode == 0:
                    selected_stats = [
                        option for option in AIRCRAFT_STAT_OPTIONS
                        if option in aircraft_stat_selected
                    ]
                    above_count = len(selected_stats) // 2
                    above_stats = selected_stats[:above_count]
                    below_stats = selected_stats[above_count:]
                    for stat_index, option in enumerate(above_stats):
                        stat_text, stat_available = _aircraft_stat_display(plane, option)
                        stat_colour = rarity_col if stat_available else (100, 100, 100)
                        stat_y = y - (13 * (len(above_stats) - stat_index))
                        draw_text.fading(window, stat_text, text_font3, stat_colour, x, stat_y, fade_value)
                    for stat_index, option in enumerate(below_stats):
                        stat_text, stat_available = _aircraft_stat_display(plane, option)
                        stat_colour = rarity_col if stat_available else (100, 100, 100)
                        stat_y = y + (13 * (stat_index + 1))
                        draw_text.fading(window, stat_text, text_font3, stat_colour, x, stat_y, fade_value)

            except Exception as e:
                log.error(f"Draw error for {icao} at x={x} y={y}: {e}")

        with data_lock:
            plane_rects = current_plane_rects

        if tracking_mode_auto:
            new_auto_track_icaos = current_auto_track_icaos - auto_track_inside_icaos
            for icao in sorted(new_auto_track_icaos):
                if icao not in auto_track_queue:
                    auto_track_queue.append(icao)
            auto_track_inside_icaos.clear()
            auto_track_inside_icaos.update(current_auto_track_icaos)

            with data_lock:
                camera_busy_for_auto = tracker_capture_in_progress
            if not camera_busy_for_auto:
                while auto_track_queue:
                    queued_icao = auto_track_queue.popleft()
                    if begin_camera_tracking(queued_icao, logger=add_message, auto_select=True):
                        planecam_auto_capture_last_time[queued_icao] = current_time
                        break
        else:
            auto_track_queue.clear()
            auto_track_inside_icaos.clear()




        if tracking_mode_auto and current_auto_track_icaos:
            with data_lock:
                _ac_busy = tracker_capture_in_progress
            if not _ac_busy:
                _ac_candidates = [
                    icao for icao in current_auto_track_icaos
                    if current_time - planecam_auto_capture_last_time.get(icao, 0.0) >= PLANECAM_AUTO_CAPTURE_INTERVAL
                ]
                if _ac_candidates:
                    _ac_target = min(_ac_candidates, key=lambda icao: planecam_auto_capture_last_time.get(icao, 0.0))
                    if begin_camera_tracking(_ac_target, logger=add_message, auto_select=True):
                        planecam_auto_capture_last_time[_ac_target] = current_time


        _scroll_target_icao = selected_plane_icao if selected_plane_icao else closest_plane
        if _scroll_target_icao != _prev_target_icao_for_scroll:
            camera_scroll_offset = 0
            _prev_target_icao_for_scroll = _scroll_target_icao
