def prepare_frame():
        global aircraft_stat_availability, aircraft_stat_checkbox_rects
        global altitude_slider_down_rect, altitude_slider_up_rect
        global cpu_percentage, cpu_temp, current_graph_date, current_time, disk_free
        global displayed_planes_snapshot, distance_filter_checkbox_rect
        global distance_filter_slider_handle_rect, distance_slider_down_rect
        global distance_slider_track_rect, distance_slider_up_rect, distance_unit_rects
        global filter_checkbox_rect, filter_panel_rect, filter_slider_handle_rect
        global hide_planes_button_rect, last_health_log, last_system_stats_refresh
        global log_bottom_row_y, log_box_rect, log_h_early, logs_h, logs_y
        global rarity_checkbox_rects, ram_percentage, reset_filters_button_rect
        global slider_track_rect, top_graph_last_bucket
        global trajectory_toggle_rect

        current_time = time.time()

        _today = datetime.today().strftime('%Y-%m-%d')
        if runtime_mode == "production" and _today != current_graph_date:
            current_graph_date = _today
            with data_lock:
                active_count_history.clear()
                total_seen_history.clear()
            clear_top_graph_history(TOP_GRAPH_HISTORY_DIR)
            top_graph_last_bucket = None

        logs_y = 590
        logs_h = (height - 50) - logs_y - 10
        filter_panel_rect = pygame.Rect(SIDEBAR_X + (SIDEBAR_WIDTH // 2) + 5, (315 // 2) + 68 + 150, int(SIDEBAR_WIDTH / 2) - 5, int(logs_h // 2))
        log_bottom_row_y = filter_panel_rect.bottom + 10
        log_h_early = (height - 10) - log_bottom_row_y
        log_box_rect = pygame.Rect(filter_panel_rect.left, log_bottom_row_y, filter_panel_rect.width, log_h_early)
        trajectory_toggle_rect = pygame.Rect(filter_panel_rect.right - 48, filter_panel_rect.top + 8, 40, 40)
        hide_planes_button_rect = pygame.Rect(filter_panel_rect.right - 48, filter_panel_rect.top + 56, 40, 40)
        reset_filters_button_rect = pygame.Rect(filter_panel_rect.right - 48, filter_panel_rect.top + 104, 40, 40)
        distance_unit_rects = {
            "NM": pygame.Rect(filter_panel_rect.right - 44, filter_panel_rect.top + 152, 14, 14),
            "KM": pygame.Rect(filter_panel_rect.right - 44, filter_panel_rect.top + 174, 14, 14),
            "MI": pygame.Rect(filter_panel_rect.right - 44, filter_panel_rect.top + 196, 14, 14),
        }
        filter_checkbox_rect = pygame.Rect(filter_panel_rect.left + 8, filter_panel_rect.top + 10, 14, 14)
        slider_track_rect = pygame.Rect(filter_panel_rect.left + 28, filter_panel_rect.top + 48, 12, max(80, filter_panel_rect.height - 66))
        distance_filter_checkbox_rect = pygame.Rect(filter_panel_rect.left + 83, filter_panel_rect.top + 10, 14, 14)
        distance_slider_track_rect = pygame.Rect(filter_panel_rect.left + 103, filter_panel_rect.top + 48, 12, max(80, filter_panel_rect.height - 66))
        slider_ratio = 1.0 - (altitude_filter_threshold / 50000.0)
        slider_handle_y = slider_track_rect.top + int(slider_ratio * slider_track_rect.height) - 5
        slider_handle_y = max(slider_track_rect.top - 5, min(slider_track_rect.bottom - 5, slider_handle_y))
        filter_slider_handle_rect = pygame.Rect(slider_track_rect.left - 2, slider_handle_y, slider_track_rect.width + 4, 10)
        distance_slider_ratio = 1.0 - (distance_filter_threshold_km / 1000.0)
        distance_slider_handle_y = distance_slider_track_rect.top + int(distance_slider_ratio * distance_slider_track_rect.height) - 5
        distance_slider_handle_y = max(distance_slider_track_rect.top - 5, min(distance_slider_track_rect.bottom - 5, distance_slider_handle_y))
        distance_filter_slider_handle_rect = pygame.Rect(distance_slider_track_rect.left - 2, distance_slider_handle_y, distance_slider_track_rect.width + 4, 10)
        altitude_slider_up_rect = pygame.Rect(slider_track_rect.right + 30, slider_track_rect.top + 6, 18, 14)
        altitude_slider_down_rect = pygame.Rect(slider_track_rect.right + 30, slider_track_rect.top + 24, 18, 14)
        distance_slider_up_rect = pygame.Rect(distance_slider_track_rect.right + 30, distance_slider_track_rect.top + 6, 18, 14)
        distance_slider_down_rect = pygame.Rect(distance_slider_track_rect.right + 30, distance_slider_track_rect.top + 24, 18, 14)
        _rarity_col_x = filter_panel_rect.centerx - 20
        _rarity_row_h = 22
        _rarity_start_y = filter_panel_rect.top + 10
        rarity_checkbox_rects = {
            tier: pygame.Rect(_rarity_col_x, _rarity_start_y + i * _rarity_row_h, 14, 14)
            for i, (tier, _col, _label) in enumerate(RARITY_TIERS)
        }
        _aircraft_stat_x = filter_panel_rect.right - 140
        _aircraft_stat_start_y = filter_panel_rect.top + 8
        _aircraft_stat_row_h = 24
        aircraft_stat_checkbox_rects = {
            option: pygame.Rect(_aircraft_stat_x, _aircraft_stat_start_y + i * _aircraft_stat_row_h, 14, 14)
            for i, option in enumerate(AIRCRAFT_STAT_OPTIONS)
        }



        if current_time - last_health_log >= 1800:
            log.info(f"Health check: CPU temp={cpu_temp:.1f}C, RAM={ram_percentage:.1f}%")
            last_health_log = current_time


        #Refresh expensive system statistics once per second
        if runtime_mode == "production" and current_time - last_system_stats_refresh >= 1:
            cpu_temp = _read_cpu_temp()
            ram_percentage = psutil.virtual_memory()[2]
            cpu_percentage = psutil.cpu_percent()
            disk_free = functions.get_disk_free()
            last_system_stats_refresh = current_time

        displayed_planes_snapshot = snapshot_displayed_planes()
        aircraft_stat_availability = {
            option: any(
                _aircraft_stat_available(display_data.get("plane_data", {}), option)
                for display_data in displayed_planes_snapshot.values()
            )
            for option in AIRCRAFT_STAT_OPTIONS
        }
