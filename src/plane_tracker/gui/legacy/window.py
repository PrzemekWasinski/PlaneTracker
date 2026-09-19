from types import FunctionType

from ... import app
from ...core.compatibility import bind_module
from . import events, frame, loop, radar, sidebar

pygame = app.pygame
os = app.os
functions = app.functions
_config = app._config
deque = app.deque
IS_WINDOWS = app.IS_WINDOWS
DEFAULT_PREVIEW = app.DEFAULT_PREVIEW

pygame.init()


width = _config['screenWidth']
height = _config['screenHeight']
development_mode = DEFAULT_PREVIEW


def _create_window():
    pygame.display.set_caption("PlaneTracker")
    return pygame.display.set_mode((width, height), pygame.FULLSCREEN)


window = _create_window()


text_font1 = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 16)
text_font2 = pygame.font.Font(os.path.join("textures", "fonts", "DS-DIGI.TTF"), 40)
text_font3 = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 11)
stat_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 13)
graph_time_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 9)
plane_identity_font = pygame.font.Font(os.path.join("textures", "fonts", "NaturalMono-Bold.ttf"), 12)


zoom_in_icon = pygame.image.load(os.path.join("textures", "icons", "zoom_in.png")).convert_alpha()
zoom_out_icon = pygame.image.load(os.path.join("textures", "icons", "zoom_out.png")).convert_alpha()
online_mode_icon = pygame.image.load(os.path.join("textures", "icons", "online_mode.png")).convert_alpha()
offline_mode_icon = pygame.image.load(os.path.join("textures", "icons", "offline_mode.png")).convert_alpha()
shutdown_icon = pygame.image.load(os.path.join("textures", "icons", "shutdown.png")).convert_alpha()
restart_icon = pygame.image.load(os.path.join("textures", "icons", "restart.png")).convert_alpha()
center_on_home_icon = pygame.image.load(os.path.join("textures", "icons", "center_on_home.png")).convert_alpha()
center_on_plane_icon = pygame.image.load(os.path.join("textures", "icons", "center_on_plane.png")).convert_alpha()
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


RADAR_RECT = pygame.Rect(0, 0, 1080, 1080)
RADAR_CENTER_X = RADAR_RECT.centerx
RADAR_CENTER_Y = RADAR_RECT.centery
RADAR_RADIUS = 540
RADAR_RANGE_VALUES = list(range(25, 1001, 25))
MIN_RADAR_RANGE_KM = 25
MAX_RADAR_RANGE_KM = 300 * 1.852
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



    map_view = pygame.Surface(crop_rect.size)
    map_view.blit(map_image, (-crop_rect.left, -crop_rect.top))
    if map_view.get_size() != RADAR_RECT.size:
        map_view = pygame.transform.smoothscale(map_view, RADAR_RECT.size)
    map_view.set_colorkey((0, 0, 0))
    return map_view


SIDEBAR_X = 1090
SIDEBAR_WIDTH = width - SIDEBAR_X



btn_w = 40
btn_h = 40
toolbar_start_x = SIDEBAR_X + 5
toolbar_width = int((SIDEBAR_WIDTH / 2) - 10)
toolbar_button_count = 7


def toolbar_button_x(index):
    usable_width = toolbar_width - btn_w
    return toolbar_start_x + round(index * usable_width / (toolbar_button_count - 1))


zoom_in_ctrl_rect = pygame.Rect(toolbar_button_x(0), height - 50, btn_w, btn_h)
zoom_out_ctrl_rect = pygame.Rect(toolbar_button_x(1), height - 50, btn_w, btn_h)
mode_toggle_rect = pygame.Rect(toolbar_button_x(2), height - 50, btn_w, btn_h)
restart_button_rect = pygame.Rect(toolbar_button_x(3), height - 50, btn_w, btn_h)
off_button_rect = pygame.Rect(toolbar_button_x(4), height - 50, btn_w, btn_h)
clear_graph_rect = pygame.Rect(toolbar_button_x(5), height - 50, btn_w, btn_h)
screenshot_button_rect = pygame.Rect(toolbar_button_x(6), height - 50, btn_w, btn_h)


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
instance_lock_file = None




for _name, _value in tuple(globals().items()):
    if not _name.startswith("__") and _name not in {"app", "FunctionType"}:
        setattr(app, _name, _value)

def _main_impl(max_frames=None):
    global tracker_running, offline, selected_plane_icao, window
    global altitude_filter_threshold, altitude_filter_above, altitude_filter_dragging
    global distance_filter_threshold_km, distance_filter_outside, distance_filter_dragging
    global hide_planes_mode, show_all_trajectories, distance_unit, rarity_filter_selected
    global aircraft_stat_selected
    global start_time, top_graph_last_bucket, range_km
    global last_health_log, last_system_stats_refresh
    global cpu_temp, ram_percentage, cpu_percentage, disk_free
    global current_graph_date, view_center_lat, view_center_lon
    global follow_selected_plane, plane_headings, log_scroll_offset
    global log_scroll_dragging, log_scrollbar_thumb_rect
    global log_scroll_drag_start_y, log_scroll_drag_start_offset
    global closest_plane, frames_rendered
    global _compact_stat_number, _aircraft_stat_display
    global _aircraft_stat_available, _active_plane_position, _closest_active_plane

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

    for module in (frame, events, radar, sidebar, loop):
        bind_module(globals(), module)

    while True:
        prepare_frame()
        handle_events()
        draw_radar()
        draw_sidebar()
        if finish_frame(max_frames):
            return


bind_module(globals(), loop)
