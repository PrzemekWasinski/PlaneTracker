import sys
from pathlib import Path
from types import FunctionType

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plane_tracker as app

pygame = app.pygame
os = app.os
functions = app.functions
_config = app._config
deque = app.deque
IS_WINDOWS = app.IS_WINDOWS
DEFAULT_PREVIEW = app.DEFAULT_PREVIEW
#PYGAME SETUP
pygame.init()
#pygame.mouse.set_visible(False)

width = _config['screenWidth']
height = _config['screenHeight']
development_mode = DEFAULT_PREVIEW


def _create_window():
    pygame.display.set_caption("PlaneTracker")
    return pygame.display.set_mode((width, height), pygame.FULLSCREEN)


window = _create_window()

#Fonts
text_font1 = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 16)
text_font2 = pygame.font.Font(os.path.join("textures", "fonts", "DS-DIGI.TTF"), 40)
text_font3 = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 11)
stat_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 13)
graph_time_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 9)
plane_identity_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 12)

#Load images
zoom_in_icon = pygame.image.load(os.path.join("textures", "icons", "zoom_in.png")).convert_alpha()
zoom_out_icon = pygame.image.load(os.path.join("textures", "icons", "zoom_out.png")).convert_alpha()
online_mode_icon = pygame.image.load(os.path.join("textures", "icons", "online_mode.png")).convert_alpha()
offline_mode_icon = pygame.image.load(os.path.join("textures", "icons", "offline_mode.png")).convert_alpha()
shutdown_icon = pygame.image.load(os.path.join("textures", "icons", "shutdown.png")).convert_alpha()
restart_icon = pygame.image.load(os.path.join("textures", "icons", "restart.png")).convert_alpha()
track_target_icon = pygame.image.load(os.path.join("textures", "icons", "track_target.png")).convert_alpha()
center_on_home_icon = pygame.image.load(os.path.join("textures", "icons", "center_on_home.png")).convert_alpha()
center_on_plane_icon = pygame.image.load(os.path.join("textures", "icons", "center_on_plane.png")).convert_alpha()
auto_tracking_icon = pygame.image.load(os.path.join("textures", "icons", "auto_tracking.png")).convert_alpha()
manual_tracking_icon = pygame.image.load(os.path.join("textures", "icons", "manual_tracking.png")).convert_alpha()
plane_only_mode_icon = pygame.image.load(os.path.join("textures", "icons", "plane.png")).convert_alpha()
plane_and_text_mode_icon = pygame.image.load(os.path.join("textures", "icons", "plane_and_text.png")).convert_alpha()
hide_plane_mode_icon = pygame.image.load(os.path.join("textures", "icons", "hide_plane.png")).convert_alpha()
hide_trajectories_icon = pygame.image.load(os.path.join("textures", "icons", "hide_trajectories.png")).convert_alpha()
show_trajectories_icon = pygame.image.load(os.path.join("textures", "icons", "show_trajectories.png")).convert_alpha()
screenshot_icon = pygame.image.load(os.path.join("textures", "icons", "screenshot.png")).convert_alpha()
clear_filters_icon = pygame.image.load(os.path.join("textures", "icons", "clear_filters.png")).convert_alpha()
plane_icon = pygame.image.load(os.path.join("textures", "icons", "plane_icon.png")).convert_alpha()
selected_plane_icon = pygame.image.load(os.path.join("textures", "icons", "selected_plane.png")).convert_alpha()
plane_icon_white = plane_icon.copy()
plane_icon_white.fill((255, 255, 255), special_flags=pygame.BLEND_RGB_MAX)

#Radar display settings
RADAR_RECT = pygame.Rect(0, 0, 1080, 1080)
RADAR_CENTER_X = RADAR_RECT.centerx
RADAR_CENTER_Y = RADAR_RECT.centery
RADAR_RADIUS = 540
RADAR_RANGE_VALUES = list(range(25, 1001, 25))
MIN_RADAR_RANGE_KM = 25
MAX_RADAR_RANGE_KM = 300 * 1.852  # 300 nautical miles
RADAR_MAP_DIR = os.path.join('textures', 'radar_map')

radar_map_images = {}
for radar_range_km in RADAR_RANGE_VALUES:
    radar_map_path = os.path.join(RADAR_MAP_DIR, f'{radar_range_km}.png')
    if os.path.exists(radar_map_path):
        try:
            radar_map_images[radar_range_km] = pygame.image.load(radar_map_path).convert()
            radar_map_images[radar_range_km].set_colorkey((0, 0, 0))
        except pygame.error:
            pass


def _zoom_in_range(range_km):
    if range_km >= MAX_RADAR_RANGE_KM:
        return min(550, MAX_RADAR_RANGE_KM)
    return max(MIN_RADAR_RANGE_KM, range_km - 25)


def _zoom_out_range(range_km):
    return min(MAX_RADAR_RANGE_KM, range_km + 25)


def _radar_map_for_view(range_km, view_center_lat, view_center_lon):
    """Return the smallest map containing the complete shifted viewport."""
    if not radar_map_images:
        return None, None
    offset_km = functions.calculate_distance(
        float(_config['myLat']), float(_config['myLon']),
        float(view_center_lat), float(view_center_lon),
    )
    required_range = offset_km + range_km
    containing_ranges = [
        value for value in radar_map_images
        if value >= required_range
    ]
    map_range = (
        min(containing_ranges)
        if containing_ranges
        else max(radar_map_images)
    )
    return radar_map_images[map_range], map_range


def _render_radar_map_view(map_image, map_range, range_km, view_center_lat, view_center_lon):
    """Extract the current viewport from a complete home-centred map."""
    source_width, source_height = map_image.get_size()
    source_center_x, source_center_y = functions.coords_to_xy(
        float(view_center_lat), float(view_center_lon), map_range,
        float(_config['myLat']), float(_config['myLon']),
        source_width, source_height, source_width // 2, source_height // 2,
        float(_config['myLat']),
    )
    crop_width = max(1, round(source_width * range_km / map_range))
    crop_height = max(1, round(source_height * range_km / map_range))
    crop_rect = pygame.Rect(
        round(source_center_x - crop_width / 2),
        round(source_center_y - crop_height / 2),
        crop_width,
        crop_height,
    )

    # Padding makes even a position beyond the largest available source map
    # safe; normally the wider map selected above fully covers this surface.
    map_view = pygame.Surface(crop_rect.size)
    map_view.blit(map_image, (-crop_rect.left, -crop_rect.top))
    if map_view.get_size() != RADAR_RECT.size:
        map_view = pygame.transform.smoothscale(map_view, RADAR_RECT.size)
    map_view.set_colorkey((0, 0, 0))
    return map_view

#Sidebar settings
SIDEBAR_X = 1090
SIDEBAR_WIDTH = width - SIDEBAR_X


# UI Buttons - spread across exactly the same width as the camera preview box.
btn_w = 40
btn_h = 40
btn_gap = 12  # Match the toolbar's nominal 12px spacing.
toolbar_start_x = SIDEBAR_X + 5
toolbar_width = int((SIDEBAR_WIDTH / 2) - 10)
toolbar_button_count = 8


def toolbar_button_x(index):
    usable_width = toolbar_width - btn_w
    return toolbar_start_x + round(index * usable_width / (toolbar_button_count - 1))


zoom_in_ctrl_rect = pygame.Rect(toolbar_button_x(0), height - 50, btn_w, btn_h)
zoom_out_ctrl_rect = pygame.Rect(toolbar_button_x(1), height - 50, btn_w, btn_h)
mode_toggle_rect = pygame.Rect(toolbar_button_x(2), height - 50, btn_w, btn_h)
auto_track_mode_rect = pygame.Rect(toolbar_button_x(3), height - 50, btn_w, btn_h)
restart_button_rect = pygame.Rect(toolbar_button_x(4), height - 50, btn_w, btn_h)
off_button_rect = pygame.Rect(toolbar_button_x(5), height - 50, btn_w, btn_h)
clear_graph_rect = pygame.Rect(toolbar_button_x(6), height - 50, btn_w, btn_h)
screenshot_button_rect = pygame.Rect(toolbar_button_x(7), height - 50, btn_w, btn_h)

#Global for plane selection
selected_plane_icao = None
plane_rects = {} 
altitude_filter_threshold = 0
altitude_filter_above = True
altitude_filter_dragging = False
distance_filter_threshold_km = 0.0
distance_filter_outside = True
distance_filter_dragging = False
rarity_filter_selected = set()
hide_planes_mode = 0
show_all_trajectories = False
AIRCRAFT_STAT_OPTIONS = (
    "Airline", "Aircraft", "FlightNumber", "Speed",
    "Altitude", "Squawk", "Hits", "Distance",
)
DEFAULT_AIRCRAFT_STATS = {"Airline", "Aircraft", "FlightNumber", "Altitude"}
aircraft_stat_selected = set(DEFAULT_AIRCRAFT_STATS)
distance_unit = "NM"
tracker_status_connected = False
tracker_device_stats = {"temp": None, "ram": None, "cpu": None, "disk": None}
tracker_capture_in_progress = False
tracker_photo_bytes = None
tracker_photo_surface = None
tracker_photo_dirty = False
tracker_photo_status = "No camera image"
tracker_photo_plane_icao = None
tracker_pending_photo_plane_icao = None
tracker_photo_meta = {}
tracker_plane_photo_cache = {}
tracker_plane_photo_meta_cache = {}
tracking_mode_auto = False
planecam_auto_capture_last_time = {}
PLANECAM_AUTO_CAPTURE_INTERVAL = 15.0
tracker_plane_photo_history = {}
TRACKER_PLANE_PHOTO_HISTORY_LIMIT = 10
camera_scroll_offset = 0
auto_track_queue = deque()
auto_track_inside_icaos = set()
AUTO_TRACK_POLYGON_KEYS = (("tlLat", "tlLon"), ("trLat", "trLon"), ("brLat", "brLon"), ("blLat", "blLon"))
AUTO_TRACK_CONFIGURED = all(_config.get(lat_key) is not None and _config.get(lon_key) is not None for lat_key, lon_key in AUTO_TRACK_POLYGON_KEYS)
instance_lock_file = None


# The render loop is rebound to the backend module's globals. Export the UI
# resources and interaction state it consumes into that shared state first.
for _name, _value in tuple(globals().items()):
    if not _name.startswith("__") and _name not in {"app", "FunctionType"}:
        setattr(app, _name, _value)
#THREAD 1: Main UI Thread
def _main_impl(max_frames=None):
    global tracker_running, offline, selected_plane_icao, window
    global altitude_filter_threshold, altitude_filter_above, altitude_filter_dragging
    global distance_filter_threshold_km, distance_filter_outside, distance_filter_dragging
    global hide_planes_mode, show_all_trajectories, distance_unit, rarity_filter_selected
    global aircraft_stat_selected
    global tracker_capture_in_progress, tracker_photo_status, tracker_photo_plane_icao, tracking_mode_auto
    global camera_scroll_offset, planecam_auto_capture_last_time

    start_time = time.time()
    if runtime_mode == "preview":
        top_graph_last_bucket = None
    else:
        top_graph_last_bucket = load_top_graph_history(active_count_history, total_seen_history, TOP_GRAPH_HISTORY_DIR, TOP_GRAPH_HISTORY_SECONDS, start_time)
    range_km = 50
    last_health_log = start_time
    last_system_stats_refresh = 0
    cpu_temp = 0
    ram_percentage = 0
    cpu_percentage = 0
    disk_free = functions.get_disk_free()
    
    current_graph_date = datetime.today().strftime('%Y-%m-%d')

    view_center_lat = _config['myLat']
    view_center_lon = _config['myLon']
    follow_selected_plane = False
    plane_headings = {}
    log_scroll_offset = 0
    log_scroll_dragging = False
    log_scrollbar_thumb_rect = pygame.Rect(0, 0, 0, 0)
    log_scroll_drag_start_y = 0
    log_scroll_drag_start_offset = 0
    _prev_target_icao_for_scroll = None
    closest_plane = None
    frames_rendered = 0

    def _compact_stat_number(value, decimals=0):
        try:
            number = float(value)
            if decimals:
                return str(round(number, decimals))
            return str(int(round(number)))
        except (TypeError, ValueError):
            return "-"

    def _aircraft_stat_display(plane, option):
        if option == "Airline":
            value = plane.get("owner")
            return (str(value), True) if value not in (None, "", "-") else ("Unknown Airline", False)
        if option == "Aircraft":
            parts = [str(plane.get(key)) for key in ("manufacturer", "model") if plane.get(key) not in (None, "", "-")]
            return (" ".join(parts), True) if parts else ("Unknown Aircraft", False)
        if option == "FlightNumber":
            value = plane.get("flight")
            return (str(value), True) if value not in (None, "", "-") else ("-", False)
        if option == "Speed":
            value = _compact_stat_number(plane.get("speed"))
            return (f"{value}kt", True) if value != "-" else ("-", False)
        if option == "Altitude":
            value = _compact_stat_number(plane.get("altitude"))
            return (f"{value}ft", True) if value != "-" else ("-", False)
        if option == "Squawk":
            value = plane.get("squawk")
            return (str(value), True) if value not in (None, "", "-") else ("-", False)
        if option == "Hits":
            value = plane.get("total_hit_count")
            return (str(int(value)), True) if value is not None else ("-", False)
        if option == "Distance":
            value = plane.get("distance")
            if value in (None, "", "-"):
                lat = plane.get("last_lat", plane.get("lat"))
                lon = plane.get("last_lon", plane.get("lon"))
                if lat not in (None, "", "-") and lon not in (None, "", "-"):
                    value = functions.calculate_distance(
                        float(_config["myLat"]), float(_config["myLon"]),
                        float(lat), float(lon),
                    )
                    plane["distance"] = value
            if value not in (None, "", "-"):
                return (format_distance(value, distance_unit, 1), True)
            return ("-", False)
        return ("-", False)

    def _aircraft_stat_available(plane, option):
        return _aircraft_stat_display(plane, option)[1]

    def _active_plane_position(display_data, now):
        if not display_data or display_data.get("display_until", 0) <= now:
            return None
        plane = display_data.get("plane_data", {})
        try:
            lat = float(plane.get("last_lat"))
            lon = float(plane.get("last_lon"))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(lat) or not math.isfinite(lon):
            return None
        return lat, lon

    def _closest_active_plane(snapshot, now):
        closest_icao = None
        closest_position = None
        closest_distance = float("inf")
        home_lat = float(_config["myLat"])
        home_lon = float(_config["myLon"])
        for icao, display_data in snapshot.items():
            position = _active_plane_position(display_data, now)
            if position is None:
                continue
            distance = functions.calculate_distance(
                home_lat, home_lon, position[0], position[1]
            )
            if distance < closest_distance:
                closest_icao = icao
                closest_position = position
                closest_distance = distance
        return closest_icao, closest_position

    while True:
        current_time = time.time()

        _today = datetime.today().strftime('%Y-%m-%d')
        if runtime_mode == "production" and _today != current_graph_date:
            current_graph_date = _today
            with data_lock:
                active_count_history.clear()
                total_seen_history.clear()
            clear_top_graph_history(TOP_GRAPH_HISTORY_DIR)
            top_graph_last_bucket = None

        pic_y = 377
        pic_h = 203
        logs_y = pic_y + pic_h + 10
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
        track_plane_button_rect = pygame.Rect(SIDEBAR_X + 250, ((315 // 2) + 68) + 10, 40, 40)
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

        _cam_box_w = int((SIDEBAR_WIDTH / 2) - 10)
        _cam_box_h = int(_cam_box_w * 3 / 4)
        cam_scroll_right_rect = pygame.Rect(SIDEBAR_X + 5 + _cam_box_w - btn_w, log_bottom_row_y + _cam_box_h + 10, btn_w, btn_h)
        cam_scroll_left_rect = pygame.Rect(cam_scroll_right_rect.left - btn_w - btn_gap, log_bottom_row_y + _cam_box_h + 10, btn_w, btn_h)

        #Log health stats every 30 minutes
        if current_time - last_health_log >= 1800:
            log.info(f"Health check: CPU temp={cpu_temp:.1f}C, RAM={ram_percentage:.1f}%")
            last_health_log = current_time

        #Refresh expensive local stats on a timer instead of every frame
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

        #Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                tracker_running = False
                pygame.quit()
                exit()
            
            #Mouse wheel zoom / log scroll
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

                #Only zoom if mouse is over the radar area
                elif RADAR_RECT.collidepoint(mouse_x, mouse_y):
                    #Scroll up = zoom in, scroll down = zoom out
                    if event.y > 0:  #Scroll up
                        range_km = _zoom_in_range(range_km)
                    elif event.y < 0:  #Scroll down
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
                        # drag down â†’ newer (lower offset); drag up â†’ older (higher offset)
                        log_scroll_offset = max(0, min(max_scroll_drag, log_scroll_drag_start_offset - delta))

            elif event.type == pygame.MOUSEBUTTONDOWN:
                #Only process left mouse button (button 1), ignore middle/right clicks and scroll buttons
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

                if cam_scroll_left_rect.collidepoint(mouse_x, mouse_y):
                    _scroll_icao = selected_plane_icao if selected_plane_icao else closest_plane
                    _hist_len = len(tracker_plane_photo_history.get(_scroll_icao, [])) if _scroll_icao else 0
                    if _hist_len > 0:
                        camera_scroll_offset = (camera_scroll_offset - 1) % _hist_len
                    continue

                if cam_scroll_right_rect.collidepoint(mouse_x, mouse_y):
                    _scroll_icao = selected_plane_icao if selected_plane_icao else closest_plane
                    _hist_len = len(tracker_plane_photo_history.get(_scroll_icao, [])) if _scroll_icao else 0
                    if _hist_len > 0:
                        camera_scroll_offset = (camera_scroll_offset + 1) % _hist_len
                    continue

                if track_plane_button_rect.collidepoint(mouse_x, mouse_y):
                    if tracking_mode_auto:
                        add_message('Manual tracking disabled in auto mode')
                        continue

                    with data_lock:
                        manual_track_busy = tracker_capture_in_progress
                    if manual_track_busy:
                        add_message('Camera module busy')
                        continue

                    target_icao = selected_plane_icao if (selected_plane_icao in displayed_planes_snapshot) else None
                    if not target_icao:
                        min_track_dist = float("inf")
                        for icao, display_data in displayed_planes_snapshot.items():
                            plane = display_data.get("plane_data", {})
                            if not plane_matches_altitude_filter(plane, altitude_filter_threshold, altitude_filter_above):
                                continue
                            lat = plane.get("last_lat")
                            lon = plane.get("last_lon")
                            if lat is None or lon is None:
                                continue
                            dist = functions.calculate_distance(view_center_lat, view_center_lon, float(lat), float(lon))
                            if distance_filter_threshold_km > 0:
                                if distance_filter_outside and dist < distance_filter_threshold_km:
                                    continue
                                if not distance_filter_outside and dist > distance_filter_threshold_km:
                                    continue
                            if dist < min_track_dist:
                                min_track_dist = dist
                                target_icao = icao
                    if target_icao:
                        begin_camera_tracking(target_icao, logger=add_message, auto_select=False)
                    else:
                        add_message("No target plane available for tracking")
                    continue
                
                elif zoom_in_ctrl_rect.collidepoint(mouse_x, mouse_y):
                    range_km = _zoom_in_range(range_km)

                elif zoom_out_ctrl_rect.collidepoint(mouse_x, mouse_y): #Zoom out
                    range_km = _zoom_out_range(range_km)

                elif mode_toggle_rect.collidepoint(mouse_x, mouse_y):
                    offline = not offline
                    _config['offlineMode'] = offline
                    if runtime_mode == "production":
                        functions.save_config(_config)
                    add_message(f"Switched to {'offline' if offline else 'online'} mode")

                elif auto_track_mode_rect.collidepoint(mouse_x, mouse_y):
                    tracking_mode_auto = not tracking_mode_auto
                    auto_track_queue.clear()
                    auto_track_inside_icaos.clear()
                    add_message(f"Switched to {'auto' if tracking_mode_auto else 'manual'} camera tracking")
                    continue

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

        #Clear screen
        pygame.draw.rect(window, (0, 0, 0), (0, 0, width, height))
        
        #Draw radar section with clipping
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
        
        #Draw radar circles
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 100, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 200, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 300, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 400, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 500, 1)
        pygame.draw.circle(window, (225, 225, 225), (RADAR_CENTER_X, RADAR_CENTER_Y), 600, 1)
        
        #Draw range labels
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

        #Draw home location marker
        pygame.draw.polygon(window, (0, 255, 255), [
            (home_x, home_y - 3), 
            (home_x + 3, home_y), 
            (home_x, home_y + 3), 
            (home_x - 3, home_y)
        ])
        
        #Draw airports - NOW using view_center instead of config location
        for key in airport_db.airports_uk:
            airport = airport_db.airports_uk[key]
            x, y = functions.coords_to_xy(airport["lat"], airport["lon"], range_km, view_center_lat, view_center_lon, width, height, RADAR_CENTER_X, RADAR_CENTER_Y, _config['myLat'])
            pygame.draw.polygon(window, (0, 0, 255), [(x, y - 2), (x + 2, y), (x, y + 2), (x - 2, y)])
            draw_text.center(window, airport["airport_name"], text_font3, (255, 255, 255), x, y - 10)
        
        displayed_count = 0
        closest_plane = None
        min_dist = float('inf')
        
        
        # Aircraft distance and filtering are always relative to the receiver,
        # even when selected-plane follow moves the radar's visual centre.
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

        #Draw radar elements with clipping
        window.set_clip(RADAR_RECT)
        
        #Draw planes with unique highlight
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

            #Calculate fade
            time_remaining = display_data["display_until"] - current_time
            if time_remaining <= 0:
                continue
            fade_value = max(10, int(255 * (time_remaining / fade_duration))) if time_remaining < fade_duration else 255

            try:
                if hide_planes_mode == 2:
                    continue

                #NOW using view_center instead of config location
                x, y = functions.coords_to_xy(float(lat), float(lon), range_km, view_center_lat, view_center_lon, width, height, RADAR_CENTER_X, RADAR_CENTER_Y, _config['myLat'])

                #Calculate Heading
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
                        #Sort coordinates by timestamp to get chronological order
                        sorted_coords = sorted(location_history.items())

                        #Get current position to exclude it from trajectory
                        current_lat = plane.get("last_lat")
                        current_lon = plane.get("last_lon")

                        #Convert all coordinates to x,y points - NOW using view_center
                        trajectory_points = []
                        last_valid_lat = None
                        last_valid_lon = None

                        for timestamp, coords in sorted_coords:
                            try:
                                hist_lat, hist_lon = coords

                                #Skip the current position (it's drawn as the plane icon)
                                if current_lat is not None and current_lon is not None:
                                    if abs(float(hist_lat) - float(current_lat)) < 0.0001 and abs(float(hist_lon) - float(current_lon)) < 0.0001:
                                        continue

                                #Detect and skip impossible jumps (more than 100km from last point)
                                if last_valid_lat is not None and last_valid_lon is not None:
                                    distance = functions.calculate_distance(last_valid_lat, last_valid_lon, float(hist_lat), float(hist_lon))
                                    if distance > 100:  #Skip jumps greater than 100km
                                        add_message(f"Skipped invalid trajectory point: {distance:.1f}km jump")
                                        continue

                                hist_x, hist_y = functions.coords_to_xy(
                                    float(hist_lat), float(hist_lon), range_km,
                                    view_center_lat, view_center_lon,
                                    width, height, RADAR_CENTER_X, RADAR_CENTER_Y,
                                    _config['myLat']
                                )

                                #Only add points that are on or near the screen
                                if -500 <= hist_x <= width + 500 and -500 <= hist_y <= height + 500:
                                    trajectory_points.append((hist_x, hist_y))
                                    last_valid_lat = float(hist_lat)
                                    last_valid_lon = float(hist_lon)

                            except Exception as e:
                                add_message(f"Trajectory point error: {str(e)[:30]}")
                                continue

                        #Append current plane position to close the gap to the icon
                        trajectory_points.append((int(x), int(y)))

                        #Draw lines connecting the trajectory points
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

                # User-selected aircraft statistics, split around the icon.
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

        # Periodic auto-capture (auto-track mode only): every plane currently inside the
        # auto-track zone gets its own independent 15s cooldown, not a shared global one -
        # one plane's cooldown doesn't block capturing a different plane in the meantime.
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

        # Reset scroll offset when the target plane changes
        _scroll_target_icao = selected_plane_icao if selected_plane_icao else closest_plane
        if _scroll_target_icao != _prev_target_icao_for_scroll:
            camera_scroll_offset = 0
            _prev_target_icao_for_scroll = _scroll_target_icao

        #Reset clip for UI elements outside radar
        window.set_clip(None)
        
        #Draw radar border
        pygame.draw.rect(window, (225, 225, 225), RADAR_RECT, 2)
        
        #Draw Off button
        pygame.draw.rect(window, (255, 0, 0), off_button_rect)

        #right sidebar
        current_time_str = strftime("%H:%M:%S", localtime())
        draw_text.center(window, current_time_str, text_font2, (255, 0, 0), SIDEBAR_X + SIDEBAR_WIDTH // 2, 40)
        
        #Sys stats
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



        #Separator
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

        #Flight stats
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

        #Sperator 2
        separator_y = (315 // 2) + 68
        pygame.draw.line(window, (100, 100, 100), (SIDEBAR_X + 5, separator_y), (SIDEBAR_X + SIDEBAR_WIDTH - 10, separator_y), 1)

        altitude_graph_rect = pygame.Rect(SIDEBAR_X + 300, separator_y + 10, 240, 130)
        hits_graph_rect = pygame.Rect(SIDEBAR_X + 580, separator_y + 10, 240, 130)

        #Track plane button
        track_button_colour = (120, 120, 120) if (tracking_mode_auto or tracker_capture_in_progress) else (255, 255, 255)
        pygame.draw.rect(window, track_button_colour, track_plane_button_rect, 0)
        pygame.draw.rect(window, (100, 100, 100), track_plane_button_rect, 1)
        scaled_track_target_icon = pygame.transform.smoothscale(track_target_icon, (32, 32))
        window.blit(scaled_track_target_icon, scaled_track_target_icon.get_rect(center=track_plane_button_rect.center))

        #Plane Info
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

        #LOGS BOX
        logs_y = altitude_graph_rect.bottom + 10
        bottom_row_y = filter_panel_rect.bottom + 10
        log_h = (height - 10) - bottom_row_y
        pygame.draw.rect(window, (20, 20, 20), (filter_panel_rect.left, bottom_row_y, filter_panel_rect.width, log_h), 0)
        pygame.draw.rect(window, (100, 100, 100), (filter_panel_rect.left, bottom_row_y, filter_panel_rect.width, log_h), 1)

        with data_lock:
            prune_history(directional_hit_history, DIRECTIONAL_HISTORY_SECONDS, current_time)
            directional_plot_history = [(timestamp, counts.copy()) for timestamp, counts in directional_hit_history]
        #FILTERS
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
            label_colour = (255, 0, 0) if unavailable_online else (255, 255, 255) #small test, revert to (90, 90, 90)
            check_colour = (90, 90, 90) if unavailable_online else (0, 255, 0)
            pygame.draw.rect(window, (20, 20, 20), stat_rect, 0)
            pygame.draw.rect(window, checkbox_colour, stat_rect, 1)
            if option in aircraft_stat_selected:
                pygame.draw.line(window, check_colour, (stat_rect.left + 3, stat_rect.centery), (stat_rect.centerx, stat_rect.bottom - 4), 2)
                pygame.draw.line(window, check_colour, (stat_rect.centerx, stat_rect.bottom - 4), (stat_rect.right - 3, stat_rect.top + 3), 2)
            draw_text.normal(window, option, graph_time_font, label_colour, stat_rect.right + 5, stat_rect.top)

        #INFO BOX â€” polar plot + system stats
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
        # Draw scrollbar
        pygame.draw.rect(window, (40, 40, 40), log_scrollbar_track_rect)
        if total_msgs > lines_per_page:
            thumb_h = max(20, int(log_scrollbar_track_rect.height * lines_per_page / total_msgs))
            thumb_travel = log_scrollbar_track_rect.height - thumb_h
            # offset=0 (newest) â†’ thumb at bottom; offset=max_scroll (oldest) â†’ thumb at top
            thumb_y = log_scrollbar_track_rect.top + int(thumb_travel * (1.0 - log_scroll_offset / max_scroll)) if max_scroll > 0 else log_scrollbar_track_rect.top + thumb_travel
            log_scrollbar_thumb_rect = pygame.Rect(log_scrollbar_track_rect.left, thumb_y, _LOG_SCROLLBAR_W, thumb_h)
            pygame.draw.rect(window, (140, 140, 140), log_scrollbar_thumb_rect)
        else:
            log_scrollbar_thumb_rect = pygame.Rect(0, 0, 0, 0)

        #CAMERA IMAGE
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

        # Scroll buttons below camera image
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

        #TOOLBAR
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


        pygame.display.update()
        frames_rendered += 1
        if max_frames is not None and frames_rendered >= max_frames:
            return
        time.sleep(0.05)

def run(mode="preview", stats_uploader=None, _max_frames=None):
    """Run the UI against the PlaneTracker backend in preview or production."""
    if mode not in {"preview", "production"}:
        raise ValueError("mode must be 'preview' or 'production'")
    if mode == "production" and not callable(stats_uploader):
        raise ValueError("production mode requires a stats_uploader callback")

    app.runtime_mode = mode
    app._stats_uploader = stats_uploader
    app.tracker_running = True
    if mode == "preview":
        app.offline = True
        app.window = _create_window()
        app.initialise_preview_state()
    else:
        app.load_icao_cache()
        app.acquire_instance_lock()
        app.start_background_services()

    render = FunctionType(_main_impl.__code__, vars(app), "main", _main_impl.__defaults__)
    render(max_frames=_max_frames)


if __name__ == "__main__":
    run(mode="preview")
