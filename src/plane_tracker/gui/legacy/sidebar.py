def draw_sidebar():
        global log_scroll_offset, log_scrollbar_thumb_rect, top_graph_last_bucket


        window.set_clip(None)


        pygame.draw.rect(window, (225, 225, 225), RADAR_RECT, 2)


        pygame.draw.rect(window, (255, 0, 0), off_button_rect)


        current_time_str = strftime("%H:%M:%S", localtime())
        draw_text.center(window, current_time_str, text_font2, (255, 0, 0), SIDEBAR_X + SIDEBAR_WIDTH // 2, 40)


        sys_y = 85
        col1 = SIDEBAR_X + 10
        col2 = SIDEBAR_X + SIDEBAR_WIDTH // 2 - 250
        with data_lock:
            tracker_stats_snapshot = dict(tracker_device_stats)

        tracker_temp_text = f"TEMP:{round(tracker_stats_snapshot['temp'])}C" if tracker_stats_snapshot['temp'] is not None else "TEMP: N/A"
        tracker_ram_text = f"RAM:{round(tracker_stats_snapshot['ram'])}%" if tracker_stats_snapshot['ram'] is not None else "RAM: N/A"
        tracker_cpu_text = f"CPU:{round(tracker_stats_snapshot['cpu'])}%" if tracker_stats_snapshot['cpu'] is not None else "CPU: N/A"
        tracker_disk_text = f"DISK:{round(tracker_stats_snapshot['disk'], 1)}GB" if tracker_stats_snapshot['disk'] is not None else "DISK: N/A"

        api_status_connected = (not offline) and network_available and any(
            display_data.get("plane_data", {}).get('manufacturer', '-') != '-'
            for display_data in displayed_planes_snapshot.values()
        )
        internet_status_connected = network_available

        api_status_colour = (0, 255, 0) if api_status_connected else (255, 0, 0)
        internet_status_colour = (0, 255, 0) if internet_status_connected else (255, 0, 0)
        tracker_status_colour = (0, 255, 0) if tracker_status_connected else (255, 0, 0)




        pygame.draw.line(window, (100, 100, 100), (SIDEBAR_X + 5, sys_y - 10), (SIDEBAR_X + SIDEBAR_WIDTH - 10, sys_y - 10), 1)

        active_graph_rect = pygame.Rect(SIDEBAR_X + 300, sys_y, 240, 130)
        total_graph_rect = pygame.Rect(SIDEBAR_X + 580, sys_y, 240, 130)

        with _flight_stats_lock:
            stats = dict(_flight_stats_cache)
        total_seen = stats.get('total', 0)

        if displayed_count > 0 or (current_time - start_time) >= GRAPH_SAMPLE_INTERVAL:
            if runtime_mode == "production":
                top_graph_last_bucket = persist_top_graph_sample(active_count_history, total_seen_history, displayed_count, total_seen, TOP_GRAPH_HISTORY_DIR, top_graph_last_bucket, GRAPH_SAMPLE_INTERVAL, TOP_GRAPH_HISTORY_SECONDS, current_time)

        active_peak = max((sample[1] for sample in active_count_history), default=0)
        active_y_max = max(10, ((active_peak + 10 + 9) // 10) * 10)

        rarity_counts = {10: 0, 8: 0, 6: 0, 4: 0, 1: 0}
        for _icao, _display_data in displayed_planes_snapshot.items():
            _plane = _display_data.get("plane_data", {})
            if not plane_matches_altitude_filter(_plane, altitude_filter_threshold, altitude_filter_above):
                continue
            if not plane_matches_distance_filter(_plane, distance_filter_threshold_km, distance_filter_outside):
                continue
            _rating = get_rarity_rating(_plane.get('model', '-'), model_ratings)
            if _rating >= 10:
                rarity_counts[10] += 1
            elif _rating >= 8:
                rarity_counts[8] += 1
            elif _rating >= 6:
                rarity_counts[6] += 1
            elif _rating >= 4:
                rarity_counts[4] += 1
            else:
                rarity_counts[1] += 1

        draw_line_graph(window, active_graph_rect, list(active_count_history), active_y_max, draw_text, text_font3, pygame, active_peak, current_time, TOP_GRAPH_HISTORY_SECONDS, "ACTIVE")
        total_peak = max((sample[1] for sample in total_seen_history), default=0)
        total_y_max = max(100, ((total_peak + 100 + 99) // 100) * 100)
        draw_line_graph(window, total_graph_rect, list(total_seen_history), total_y_max, draw_text, text_font3, pygame, total_peak, current_time, TOP_GRAPH_HISTORY_SECONDS, "TOTAL")


        furthest_detected = stats.get('furthest_detected')
        highest_detected = stats.get('highest_detected')
        furthest_text = format_distance(furthest_detected, distance_unit, 1) if furthest_detected is not None else '-'
        highest_text = f"{highest_detected:,}ft" if highest_detected is not None else '-'
        avg_alt_text = f"{stats['avg_altitude']:,}ft" if stats.get('avg_altitude') is not None else '-'
        avg_spd_text = f"{stats['avg_speed']}kts" if stats.get('avg_speed') is not None else '-'
        max_spd_text = f"{stats['max_speed']}kts" if stats.get('max_speed') is not None else '-'
        max_hits_text = f"{stats['max_hits']:,}" if stats.get('max_hits') is not None else '-'
        top_airline_name = (stats['top_airline']['name'] or '-')[:16]
        top_mfr_name = (stats['top_manufacturer']['name'] or '-')[:14]
        top_aircraft_name = (stats['top_aircraft']['name'] or '-')[:16]

        _sp = 17
        col_r = col1 + 155
        draw_text.normal(window, f"Total Seen: {stats['total']:,}", text_font3, (255, 255, 255), col1, sys_y)
        draw_text.normal(window, f"Airlines: {stats['unique_airlines']}", text_font3, (255, 255, 255), col1, sys_y + _sp)
        draw_text.normal(window, f"Models: {stats['unique_models']}", text_font3, (255, 255, 255), col1, sys_y + _sp * 2)
        draw_text.normal(window, f"Active: {displayed_count}", text_font3, (0, 255, 0), col1, sys_y + _sp * 3)
        draw_text.normal(window, f"Top Manufacturer: {top_mfr_name}", text_font3, (255, 255, 255), col1, sys_y + _sp * 4 + 15)
        draw_text.normal(window, f"Top Airline: {top_airline_name}", text_font3, (255, 255, 255), col1, sys_y + _sp * 5 + 15)
        draw_text.normal(window, f"Top Aircraft: {top_aircraft_name}", text_font3, (255, 255, 255), col1, sys_y + _sp * 6 + 15)

        draw_text.normal(window, f"Max Spd: {max_spd_text}", text_font3, (255, 255, 255), col_r, sys_y)
        draw_text.normal(window, f"Max Hits: {max_hits_text}", text_font3, (255, 255, 255), col_r, sys_y + _sp)
        draw_text.normal(window, f"Furthest: {furthest_text}", text_font3, (255, 255, 255), col_r, sys_y + _sp * 2)
        draw_text.normal(window, f"Highest: {highest_text}", text_font3, (255, 255, 255), col_r, sys_y + _sp * 3)


        separator_y = (315 // 2) + 68
        pygame.draw.line(window, (100, 100, 100), (SIDEBAR_X + 5, separator_y), (SIDEBAR_X + SIDEBAR_WIDTH - 10, separator_y), 1)

        altitude_graph_rect = pygame.Rect(SIDEBAR_X + 300, separator_y + 10, 240, 130)
        hits_graph_rect = pygame.Rect(SIDEBAR_X + 580, separator_y + 10, 240, 130)


        track_button_colour = (120, 120, 120) if (tracking_mode_auto or tracker_capture_in_progress) else (255, 255, 255)
        pygame.draw.rect(window, track_button_colour, track_plane_button_rect, 0)
        pygame.draw.rect(window, (100, 100, 100), track_plane_button_rect, 1)
        scaled_track_target_icon = pygame.transform.smoothscale(track_target_icon, (32, 32))
        window.blit(scaled_track_target_icon, scaled_track_target_icon.get_rect(center=track_plane_button_rect.center))


        target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes_snapshot) else closest_plane
        p_data = displayed_planes_snapshot.get(target_icao, {}).get("plane_data") if target_icao else None
        graph_plane_icao = target_icao
        graph_plane_data = p_data


        altitude_samples = []
        hit_samples = []
        if graph_plane_data:
            altitude_history = graph_plane_data.get("altitude_history", deque())
            prune_history(altitude_history, PLANE_GRAPH_HISTORY_SECONDS, current_time)
            altitude_samples = list(altitude_history)

            hit_history = graph_plane_data.get("hit_history", deque())
            prune_history(hit_history, PLANE_GRAPH_HISTORY_SECONDS, current_time)
            hit_samples = list(hit_history)

        draw_line_graph(window, altitude_graph_rect, altitude_samples, 50000, draw_text, text_font3, pygame, 50000, current_time, PLANE_GRAPH_HISTORY_SECONDS, "ALTITUDE")
        hits_peak = max((sample[1] for sample in hit_samples), default=0)
        hits_y_max = max(10, ((hits_peak + 10 + 9) // 10) * 10)
        selected_total_hits = graph_plane_data.get("total_hit_count", 0) if graph_plane_data else 0
        draw_line_graph(window, hits_graph_rect, hit_samples, hits_y_max, draw_text, text_font3, pygame, selected_total_hits, current_time, PLANE_GRAPH_HISTORY_SECONDS, "HITS P/M")

        if p_data:
            mfg = p_data.get('manufacturer', '-')
            model = p_data.get('model', '-')
            owner = p_data.get('owner', '-')
            model_display = (f"{mfg} {model}")[:28] if mfg != '-' and model != '-' else "Unidentified Aircraft"
            owner_display = owner[:28] if owner != '-' else "Unidentified Airline"

            p_rating = get_rarity_rating(model, model_ratings)
            p_rarity_col = get_rarity_colour(p_rating)

            id_y = separator_y + 10
            draw_text.normal(window, model_display, plane_identity_font, p_rarity_col, col1, id_y)
            draw_text.normal(window, owner_display, plane_identity_font, p_rarity_col, col1, id_y + 16)

            spacing = 18
            stat_y = 290
            lx = col1
            rx = col2

            def rnd(val, dec=1):
                try: return round(float(val), dec)
                except: return "-"

            flight = p_data.get('flight', '-')
            alt = p_data.get('altitude', '-')
            baro_rate = p_data.get('baro_rate', '-')
            reg = p_data.get('registration', '-')
            spd = p_data.get('speed', '-')
            total_hits = p_data.get("total_hit_count", 0)

            draw_text.normal(window, f"FLNO: {flight if flight != '-' else 'N/A'}", stat_font, (255, 255, 255), lx, stat_y)
            draw_text.normal(window, f"HEX: {target_icao or 'N/A'}", stat_font, (255, 255, 255), rx, stat_y)

            draw_text.normal(window, f"ALT: {f'{alt}ft' if alt != '-' else 'N/A'}", stat_font, (255, 255, 255), lx, stat_y + spacing)
            draw_text.normal(window, f"REG: {reg if reg != '-' else 'N/A'}", stat_font, (255, 255, 255), rx, stat_y + spacing)

            baro_display = f"{baro_rate:+d}fpm" if baro_rate != '-' else 'N/A'
            draw_text.normal(window, f"V/SPD: {baro_display}", stat_font, (255, 255, 255), lx, stat_y + spacing * 2)
            draw_text.normal(window, f"SPD: {f'{rnd(spd)}kt' if spd != '-' else 'N/A'}", stat_font, (255, 255, 255), rx, stat_y + spacing * 2)

            draw_text.normal(window, f"HITS: {int(total_hits)}", stat_font, (255, 255, 255), lx, stat_y + spacing * 3)

            dist_km = p_data.get('distance', '-')
            if dist_km != '-' and dist_km is not None:
                try:
                    dist_converted = convert_distance_from_km(float(dist_km), distance_unit)
                    dist_text = f"{rnd(dist_converted, 1)}{distance_unit.lower()}"
                except (TypeError, ValueError):
                    dist_text = 'N/A'
            else:
                dist_text = 'N/A'
            draw_text.normal(window, f"DST: {dist_text}", stat_font, (255, 255, 255), rx, stat_y + spacing * 3)
        else:
            draw_text.center(window, "NO PLANE SELECTED", text_font1, (100, 100, 100), SIDEBAR_X + SIDEBAR_WIDTH // 2, separator_y + 80)


        logs_y = altitude_graph_rect.bottom + 10
        bottom_row_y = filter_panel_rect.bottom + 10
        log_h = (height - 10) - bottom_row_y
        pygame.draw.rect(window, (20, 20, 20), (filter_panel_rect.left, bottom_row_y, filter_panel_rect.width, log_h), 0)
        pygame.draw.rect(window, (100, 100, 100), (filter_panel_rect.left, bottom_row_y, filter_panel_rect.width, log_h), 1)

        with data_lock:
            prune_history(directional_hit_history, DIRECTIONAL_HISTORY_SECONDS, current_time)
            directional_plot_history = [(timestamp, counts.copy()) for timestamp, counts in directional_hit_history]

        draw_altitude_filter(
            window, filter_panel_rect, filter_checkbox_rect, slider_track_rect,
            filter_slider_handle_rect, altitude_slider_up_rect, altitude_slider_down_rect,
            altitude_filter_threshold, altitude_filter_above, distance_filter_checkbox_rect,
            distance_slider_track_rect, distance_filter_slider_handle_rect, distance_slider_up_rect,
            distance_slider_down_rect, distance_filter_threshold_km, distance_filter_outside,
            distance_unit, distance_unit_rects, draw_text, stat_font, graph_time_font, text_font3, pygame
        )
        filter_button_icons = {
            'show_trajectories': show_trajectories_icon,
            'hide_trajectories': hide_trajectories_icon,
            'plane_and_text': plane_and_text_mode_icon,
            'plane_only': plane_only_mode_icon,
            'hide_plane': hide_plane_mode_icon,
            'clear_filters': clear_filters_icon,
        }
        draw_filter_action_buttons(
            window, trajectory_toggle_rect, hide_planes_button_rect,
            reset_filters_button_rect, show_all_trajectories,
            hide_planes_mode, filter_button_icons, pygame
        )
        draw_rarity_filter(
            window, rarity_checkbox_rects, rarity_counts, rarity_filter_selected,
            RARITY_TIERS, draw_text, text_font3, pygame
        )
        for option in AIRCRAFT_STAT_OPTIONS:
            stat_rect = aircraft_stat_checkbox_rects[option]
            unavailable_online = not offline and not aircraft_stat_availability.get(option, False)
            checkbox_colour = (75, 75, 75) if unavailable_online else (160, 160, 160)
            label_colour = (255, 0, 0) if unavailable_online else (255, 255, 255)
            check_colour = (90, 90, 90) if unavailable_online else (0, 255, 0)
            pygame.draw.rect(window, (20, 20, 20), stat_rect, 0)
            pygame.draw.rect(window, checkbox_colour, stat_rect, 1)
            if option in aircraft_stat_selected:
                pygame.draw.line(window, check_colour, (stat_rect.left + 3, stat_rect.centery), (stat_rect.centerx, stat_rect.bottom - 4), 2)
                pygame.draw.line(window, check_colour, (stat_rect.centerx, stat_rect.bottom - 4), (stat_rect.right - 3, stat_rect.top + 3), 2)
            draw_text.normal(window, option, graph_time_font, label_colour, stat_rect.right + 5, stat_rect.top)


        info_box_rect = pygame.Rect(SIDEBAR_X + 5, logs_y, int((SIDEBAR_WIDTH / 2) - 10), filter_panel_rect.height)
        pygame.draw.rect(window, (20, 20, 20), info_box_rect, 0)
        pygame.draw.rect(window, (100, 100, 100), info_box_rect, 1)

        polar_size = info_box_rect.height
        polar_plot_rect = pygame.Rect(info_box_rect.right - polar_size, info_box_rect.top, polar_size, polar_size)
        draw_polar_coverage_plot(
            window, polar_plot_rect, directional_plot_history, draw_text, text_font3, graph_time_font,
            pygame, current_time, DIRECTIONAL_HISTORY_SECONDS, DIRECTIONAL_SECTOR_COUNT
        )

        sx = info_box_rect.left + 8
        sy = info_box_rect.top + 3
        sp = 15

        draw_text.normal(window, "Controller:", stat_font, (255, 255, 255), sx, sy)
        draw_text.normal(window, f"TEMP:{round(cpu_temp)}C", stat_font, (255, 255, 255), sx, sy + sp)
        draw_text.normal(window, f"RAM:{ram_percentage}%", stat_font, (255, 255, 255), sx, sy + sp * 2)
        draw_text.normal(window, f"CPU:{cpu_percentage}%", stat_font, (255, 255, 255), sx, sy + sp * 3)
        draw_text.normal(window, f"DISK:{disk_free}GB", stat_font, (255, 255, 255), sx, sy + sp * 4)
        draw_text.normal(window, "Camera:", stat_font, (255, 255, 255), sx, sy + sp * 5 + 5)
        draw_text.normal(window, tracker_temp_text, stat_font, (255, 255, 255), sx, sy + sp * 6 + 5)
        draw_text.normal(window, tracker_ram_text, stat_font, (255, 255, 255), sx, sy + sp * 7 + 5)
        draw_text.normal(window, tracker_cpu_text, stat_font, (255, 255, 255), sx, sy + sp * 8 + 5)
        draw_text.normal(window, tracker_disk_text, stat_font, (255, 255, 255), sx, sy + sp * 9 + 5)

        dot_y = sy + sp * 10 + 10
        pygame.draw.circle(window, api_status_colour, (sx + 5, dot_y + 9), 5)
        draw_text.normal(window, "API", stat_font, (255, 255, 255), sx + 14, dot_y)
        pygame.draw.circle(window, internet_status_colour, (sx + 5, dot_y + sp + 9), 5)
        draw_text.normal(window, "Internet", stat_font, (255, 255, 255), sx + 14, dot_y + sp)
        pygame.draw.circle(window, tracker_status_colour, (sx + 5, dot_y + sp * 2 + 9), 5)
        draw_text.normal(window, "Camera", stat_font, (255, 255, 255), sx + 14, dot_y + sp * 2)

        _LOG_SCROLLBAR_W = 6
        log_scrollbar_track_rect = pygame.Rect(filter_panel_rect.right - _LOG_SCROLLBAR_W - 1, bottom_row_y + 1, _LOG_SCROLLBAR_W, log_h - 2)
        log_max_w = filter_panel_rect.width - 10 - _LOG_SCROLLBAR_W - 2
        lines_per_page = max(1, (log_h - 4) // 11)
        with data_lock:
            all_msgs = list(message_queue)
        total_msgs = len(all_msgs)
        max_scroll = max(0, total_msgs - lines_per_page)
        log_scroll_offset = min(log_scroll_offset, max_scroll)
        start_idx = max(0, total_msgs - lines_per_page - log_scroll_offset)
        end_idx = max(0, total_msgs - log_scroll_offset)
        y_msg = bottom_row_y + 2
        for message in all_msgs[start_idx:end_idx]:
            colour = (200, 200, 200)
            if "WARNING" in message:
                colour = (255, 0, 0)
            elif "NEW" in message:
                colour = (0, 255, 0)
            draw_text.normal(window, truncate_log_text(str(message), text_font3, log_max_w), text_font3, colour, filter_panel_rect.left + 5, y_msg)
            y_msg += 11
            if y_msg > bottom_row_y + log_h - 10:
                break

        pygame.draw.rect(window, (40, 40, 40), log_scrollbar_track_rect)
        if total_msgs > lines_per_page:
            thumb_h = max(20, int(log_scrollbar_track_rect.height * lines_per_page / total_msgs))
            thumb_travel = log_scrollbar_track_rect.height - thumb_h

            thumb_y = log_scrollbar_track_rect.top + int(thumb_travel * (1.0 - log_scroll_offset / max_scroll)) if max_scroll > 0 else log_scrollbar_track_rect.top + thumb_travel
            log_scrollbar_thumb_rect = pygame.Rect(log_scrollbar_track_rect.left, thumb_y, _LOG_SCROLLBAR_W, thumb_h)
            pygame.draw.rect(window, (140, 140, 140), log_scrollbar_thumb_rect)
        else:
            log_scrollbar_thumb_rect = pygame.Rect(0, 0, 0, 0)


        cam_w = int((SIDEBAR_WIDTH / 2) - 10)
        cam_h = int(cam_w * 3 / 4)
        cam_rect = pygame.Rect(SIDEBAR_X + 5, bottom_row_y, cam_w, cam_h)
        pygame.draw.rect(window, (20, 20, 20), cam_rect, 0)
        pygame.draw.rect(window, (100, 100, 100), cam_rect, 1)

        with data_lock:
            camera_busy = tracker_capture_in_progress
            camera_connected = tracker_status_connected
            _latest_cam_surface = tracker_photo_surface
            _latest_cam_meta = dict(tracker_photo_meta)

        _scroll_display_icao = selected_plane_icao if selected_plane_icao else closest_plane
        _photo_history = tracker_plane_photo_history.get(_scroll_display_icao, []) if _scroll_display_icao else []
        if _photo_history:
            _display_idx = min(camera_scroll_offset, len(_photo_history) - 1)
            camera_photo_surface, cam_meta = _photo_history[_display_idx]
        else:
            camera_photo_surface = None if _scroll_display_icao else _latest_cam_surface
            cam_meta = _latest_cam_meta

        if camera_photo_surface is not None:
            img_w, img_h = camera_photo_surface.get_size()
            if img_w > 0 and img_h > 0:
                scale = min(cam_rect.width / img_w, cam_rect.height / img_h)
                scaled_size = (max(1, int(img_w * scale)), max(1, int(img_h * scale)))
                scaled_surface = pygame.transform.smoothscale(camera_photo_surface, scaled_size)
                window.blit(scaled_surface, scaled_surface.get_rect(center=cam_rect.center))
        else:
            placeholder = 'CAMERA BUSY' if camera_busy else 'NO IMAGE'
            draw_text.center(window, placeholder, text_font1, (100, 100, 100), cam_rect.centerx, cam_rect.centery)


        for _scroll_rect, _arrow_dir in [(cam_scroll_left_rect, 'L'), (cam_scroll_right_rect, 'R')]:
            pygame.draw.rect(window, (255, 255, 255), _scroll_rect, 0)
            pygame.draw.rect(window, (100, 100, 100), _scroll_rect, 1)
            _cx, _cy = _scroll_rect.centerx, _scroll_rect.centery
            if _arrow_dir == 'L':
                pygame.draw.polygon(window, (0, 0, 0), [(_cx + 8, _cy - 8), (_cx - 8, _cy), (_cx + 8, _cy + 8)])
            else:
                pygame.draw.polygon(window, (0, 0, 0), [(_cx - 8, _cy - 8), (_cx + 8, _cy), (_cx - 8, _cy + 8)])

        if _photo_history:
            _total_photos = len(_photo_history)
            _shown_idx = min(camera_scroll_offset, _total_photos - 1)
            draw_text.right(window, f"{_shown_idx + 1}/{_total_photos}", stat_font, (200, 200, 200), cam_scroll_right_rect.right, cam_scroll_right_rect.bottom + 5)

        cam_status = 'BUSY' if camera_busy else ('CONNECTED' if camera_connected else 'OFFLINE')
        cam_pan = cam_meta.get('pan', '-')
        cam_tilt = cam_meta.get('tilt', '-')
        cam_sx = cam_rect.left
        cam_sy = cam_rect.bottom + 10
        cam_sp = 15
        draw_text.normal(window, f"STATUS: {cam_status}", stat_font, (200, 200, 200), cam_sx, cam_sy)
        draw_text.normal(window, f"PAN: {cam_pan}", stat_font, (200, 200, 200), cam_sx, cam_sy + cam_sp)
        draw_text.normal(window, f"TILT: {cam_tilt}", stat_font, (200, 200, 200), cam_sx, cam_sy + cam_sp * 2)


        toolbar_buttons = [
            (zoom_in_ctrl_rect, zoom_in_icon),
            (zoom_out_ctrl_rect, zoom_out_icon),
            (mode_toggle_rect, offline_mode_icon if offline else online_mode_icon),
            (auto_track_mode_rect, manual_tracking_icon if tracking_mode_auto else auto_tracking_icon),
            (restart_button_rect, restart_icon),
            (
                clear_graph_rect,
                center_on_home_icon if follow_selected_plane else center_on_plane_icon,
            ),
            (off_button_rect, shutdown_icon),
            (screenshot_button_rect, screenshot_icon),
        ]
        for rect, icon in toolbar_buttons:
            button_background = (255, 255, 255)
            pygame.draw.rect(window, button_background, rect, 0)
            pygame.draw.rect(window, (100, 100, 100), rect, 1)
            scaled_icon = pygame.transform.smoothscale(icon, (rect.width - 8, rect.height - 8))
            icon_rect = scaled_icon.get_rect(center=rect.center)
            window.blit(scaled_icon, icon_rect)
