def handle_events():
        global aircraft_stat_selected, altitude_filter_above, altitude_filter_dragging
        global altitude_filter_threshold
        global distance_filter_dragging, distance_filter_outside
        global distance_filter_threshold_km, distance_unit, follow_selected_plane
        global hide_planes_mode, log_scroll_drag_start_offset, log_scroll_drag_start_y
        global log_scroll_dragging, log_scroll_offset, offline, range_km
        global selected_plane_icao, show_all_trajectories, tracker_running
        global view_center_lat, view_center_lon, window


        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                tracker_running = False
                pygame.quit()
                exit()


            elif event.type == pygame.MOUSEWHEEL:
                mouse_x, mouse_y = pygame.mouse.get_pos()

                if log_box_rect.collidepoint(mouse_x, mouse_y):
                    with data_lock:
                        total_msgs = len(message_queue)
                    lines_per_page = max(1, (log_h_early - 4) // 11)
                    max_scroll = max(0, total_msgs - lines_per_page)
                    if event.y > 0:
                        log_scroll_offset = min(log_scroll_offset + 3, max_scroll)
                    elif event.y < 0:
                        log_scroll_offset = max(log_scroll_offset - 3, 0)


                elif RADAR_RECT.collidepoint(mouse_x, mouse_y):

                    if event.y > 0:
                        range_km = _zoom_in_range(range_km)
                    elif event.y < 0:
                        range_km = _zoom_out_range(range_km)

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    altitude_filter_dragging = False
                    distance_filter_dragging = False
                    log_scroll_dragging = False

            elif event.type == pygame.MOUSEMOTION:
                if altitude_filter_dragging:
                    clamped_y = max(slider_track_rect.top, min(slider_track_rect.bottom, event.pos[1]))
                    altitude_filter_threshold = clamp_altitude_threshold((1.0 - ((clamped_y - slider_track_rect.top) / max(1, slider_track_rect.height))) * 50000)
                if distance_filter_dragging:
                    clamped_y = max(distance_slider_track_rect.top, min(distance_slider_track_rect.bottom, event.pos[1]))
                    distance_filter_threshold_km = clamp_distance_threshold((1.0 - ((clamped_y - distance_slider_track_rect.top) / max(1, distance_slider_track_rect.height))) * 1000.0)
                if log_scroll_dragging:
                    with data_lock:
                        total_msgs_drag = len(message_queue)
                    lines_per_page_drag = max(1, (log_h_early - 4) // 11)
                    max_scroll_drag = max(0, total_msgs_drag - lines_per_page_drag)
                    track_usable = log_h_early - 2 - max(20, int(log_h_early * lines_per_page_drag / max(1, total_msgs_drag)))
                    if track_usable > 0 and max_scroll_drag > 0:
                        dy = event.pos[1] - log_scroll_drag_start_y
                        delta = int(dy / track_usable * max_scroll_drag)

                        log_scroll_offset = max(0, min(max_scroll_drag, log_scroll_drag_start_offset - delta))

            elif event.type == pygame.MOUSEBUTTONDOWN:

                if event.button != 1:
                    continue

                last_tap_time = time.time()
                mouse_x, mouse_y = pygame.mouse.get_pos()

                if log_scrollbar_thumb_rect.collidepoint(mouse_x, mouse_y):
                    log_scroll_dragging = True
                    log_scroll_drag_start_y = mouse_y
                    log_scroll_drag_start_offset = log_scroll_offset
                    continue

                if trajectory_toggle_rect.collidepoint(mouse_x, mouse_y):
                    show_all_trajectories = not show_all_trajectories
                    add_message(
                        "Showing all aircraft trajectories"
                        if show_all_trajectories
                        else "Showing selected aircraft trajectory"
                    )
                    continue

                if hide_planes_button_rect.collidepoint(mouse_x, mouse_y):
                    hide_planes_mode = (hide_planes_mode + 1) % 3
                    if hide_planes_mode == 1:
                        add_message('Plane details hidden')
                    elif hide_planes_mode == 2:
                        add_message('Plane icons and details hidden')
                    else:
                        add_message('Plane display shown')
                    continue

                if reset_filters_button_rect.collidepoint(mouse_x, mouse_y):
                    altitude_filter_threshold = 0
                    altitude_filter_above = True
                    altitude_filter_dragging = False
                    distance_filter_threshold_km = 0.0
                    distance_filter_outside = True
                    distance_filter_dragging = False
                    hide_planes_mode = 0
                    distance_unit = "NM"
                    rarity_filter_selected.clear()
                    aircraft_stat_selected = set(DEFAULT_AIRCRAFT_STATS)
                    add_message("Filters reset to default")
                    continue

                _rarity_clicked = False
                for _tier, _rrect in rarity_checkbox_rects.items():
                    if _rrect.collidepoint(mouse_x, mouse_y):
                        if _tier in rarity_filter_selected:
                            rarity_filter_selected.discard(_tier)
                        else:
                            rarity_filter_selected.add(_tier)
                        _rarity_clicked = True
                        break
                if _rarity_clicked:
                    continue

                _aircraft_stat_clicked = False
                for _option, _stat_rect in aircraft_stat_checkbox_rects.items():
                    if _stat_rect.collidepoint(mouse_x, mouse_y):
                        if _option in aircraft_stat_selected:
                            aircraft_stat_selected.remove(_option)
                        else:
                            aircraft_stat_selected.add(_option)
                        _aircraft_stat_clicked = True
                        break
                if _aircraft_stat_clicked:
                    continue

                for unit_key, rect in distance_unit_rects.items():
                    if rect.collidepoint(mouse_x, mouse_y):
                        distance_unit = unit_key
                        add_message(f"Distance unit set to {unit_key}")
                        break
                else:
                    pass
                if any(rect.collidepoint(mouse_x, mouse_y) for rect in distance_unit_rects.values()):
                    continue

                if filter_checkbox_rect.collidepoint(mouse_x, mouse_y):
                    altitude_filter_above = not altitude_filter_above
                    continue

                if distance_filter_checkbox_rect.collidepoint(mouse_x, mouse_y):
                    distance_filter_outside = not distance_filter_outside
                    continue

                if altitude_slider_up_rect.collidepoint(mouse_x, mouse_y):
                    altitude_filter_threshold = clamp_altitude_threshold(altitude_filter_threshold + 100)
                    continue

                if altitude_slider_down_rect.collidepoint(mouse_x, mouse_y):
                    altitude_filter_threshold = clamp_altitude_threshold(altitude_filter_threshold - 100)
                    continue

                distance_step_km = convert_distance_to_km(10, distance_unit)
                if distance_slider_up_rect.collidepoint(mouse_x, mouse_y):
                    distance_filter_threshold_km = clamp_distance_threshold(distance_filter_threshold_km + distance_step_km)
                    continue

                if distance_slider_down_rect.collidepoint(mouse_x, mouse_y):
                    distance_filter_threshold_km = clamp_distance_threshold(distance_filter_threshold_km - distance_step_km)
                    continue

                if slider_track_rect.collidepoint(mouse_x, mouse_y) or filter_slider_handle_rect.collidepoint(mouse_x, mouse_y):
                    altitude_filter_dragging = True
                    clamped_y = max(slider_track_rect.top, min(slider_track_rect.bottom, mouse_y))
                    altitude_filter_threshold = clamp_altitude_threshold((1.0 - ((clamped_y - slider_track_rect.top) / max(1, slider_track_rect.height))) * 50000)
                    continue

                if distance_slider_track_rect.collidepoint(mouse_x, mouse_y) or distance_filter_slider_handle_rect.collidepoint(mouse_x, mouse_y):
                    distance_filter_dragging = True
                    clamped_y = max(distance_slider_track_rect.top, min(distance_slider_track_rect.bottom, mouse_y))
                    distance_filter_threshold_km = clamp_distance_threshold((1.0 - ((clamped_y - distance_slider_track_rect.top) / max(1, distance_slider_track_rect.height))) * 1000.0)
                    continue

                if zoom_in_ctrl_rect.collidepoint(mouse_x, mouse_y):
                    range_km = _zoom_in_range(range_km)

                elif zoom_out_ctrl_rect.collidepoint(mouse_x, mouse_y):
                    range_km = _zoom_out_range(range_km)

                elif mode_toggle_rect.collidepoint(mouse_x, mouse_y):
                    offline = not offline
                    _config['offlineMode'] = offline
                    if runtime_mode == "production":
                        functions.save_config(_config)
                    add_message(f"Switched to {'offline' if offline else 'online'} mode")

                elif screenshot_button_rect.collidepoint(mouse_x, mouse_y):
                    screenshots_dir = PROJECT_ROOT / "screenshots"
                    screenshot_path = screenshots_dir / f"plane_tracker_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
                    try:
                        screenshots_dir.mkdir(parents=True, exist_ok=True)
                        pygame.image.save(window, str(screenshot_path))
                        add_message(f"Screenshot saved: {screenshot_path.name}")
                    except (OSError, pygame.error) as exc:
                        add_message(f"Screenshot failed: {exc}")
                    continue

                elif clear_graph_rect.collidepoint(mouse_x, mouse_y):
                    follow_selected_plane = not follow_selected_plane
                    if follow_selected_plane:
                        followed_position = _active_plane_position(
                            displayed_planes_snapshot.get(selected_plane_icao),
                            current_time,
                        )
                        if followed_position is None:
                            selected_plane_icao, followed_position = _closest_active_plane(
                                displayed_planes_snapshot, current_time
                            )
                        if followed_position is not None:
                            view_center_lat, view_center_lon = followed_position
                    else:
                        view_center_lat = float(_config['myLat'])
                        view_center_lon = float(_config['myLon'])
                    add_message(
                        "Selected-plane follow enabled"
                        if follow_selected_plane
                        else "Selected-plane follow disabled; radar centred on home"
                    )
                    continue

                elif restart_button_rect.collidepoint(mouse_x, mouse_y) or off_button_rect.collidepoint(mouse_x, mouse_y):
                    if runtime_mode == "preview":
                        if restart_button_rect.collidepoint(mouse_x, mouse_y):
                            pygame.display.quit()
                            pygame.display.init()
                            window = _create_window()
                            initialise_preview_state()
                            add_message("Preview restarted")
                            continue
                        tracker_running = False
                        pygame.quit()
                        return
                    if restart_button_rect.collidepoint(mouse_x, mouse_y):
                        add_message("Restarting script")
                        tracker_running = False
                        release_instance_lock()
                        pygame.quit()
                        functions.restart_script()
                        return
                    tracker_running = False
                    release_instance_lock()
                    pygame.quit()
                    exit()
                clicked_plane = None
                with data_lock:
                    for icao, rect in plane_rects.items():
                        if rect.collidepoint(mouse_x, mouse_y):
                            clicked_plane = icao
                            break

                if clicked_plane:
                    selected_plane_icao = clicked_plane
                else:
                    if RADAR_RECT.collidepoint(mouse_x, mouse_y):
                        selected_plane_icao = None

