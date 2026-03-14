import math
import time

from .data_utils import aggregate_directional_hits


def plane_matches_altitude_filter(plane_data, altitude_filter_threshold, altitude_filter_above):
    altitude_value = plane_data.get('altitude')
    try:
        altitude_value = float(altitude_value)
    except (TypeError, ValueError):
        return False

    if altitude_filter_above:
        return altitude_value >= altitude_filter_threshold
    return altitude_value <= altitude_filter_threshold


def plane_matches_distance_filter(plane_data, distance_filter_threshold_km, distance_filter_outside):
    if distance_filter_threshold_km <= 0:
        return True

    distance_value = plane_data.get('distance')
    try:
        distance_value = float(distance_value)
    except (TypeError, ValueError):
        return False

    if distance_filter_outside:
        return distance_value >= distance_filter_threshold_km
    return distance_value <= distance_filter_threshold_km


def draw_step_button(surface, rect, direction, pygame_module):
    pygame_module.draw.rect(surface, (20, 20, 20), rect, 0)
    pygame_module.draw.rect(surface, (160, 160, 160), rect, 1)

    if direction == 'up':
        points = [
            (rect.centerx, rect.top + 4),
            (rect.left + 4, rect.bottom - 4),
            (rect.right - 4, rect.bottom - 4),
        ]
    else:
        points = [
            (rect.left + 4, rect.top + 4),
            (rect.right - 4, rect.top + 4),
            (rect.centerx, rect.bottom - 4),
        ]
    pygame_module.draw.polygon(surface, (255, 255, 255), points)



def draw_altitude_filter(surface, panel_rect, altitude_checkbox_rect, altitude_slider_track_rect, altitude_slider_handle_rect, altitude_up_button_rect, altitude_down_button_rect, altitude_filter_threshold, altitude_filter_above, distance_checkbox_rect, distance_slider_track_rect, distance_slider_handle_rect, distance_up_button_rect, distance_down_button_rect, distance_filter_threshold_km, distance_filter_outside, distance_unit, distance_unit_rects, draw_text_module, stat_font, graph_time_font, text_font, pygame_module):
    pygame_module.draw.rect(surface, (100, 100, 100), panel_rect, 1)

    pygame_module.draw.rect(surface, (20, 20, 20), altitude_checkbox_rect, 0)
    pygame_module.draw.rect(surface, (160, 160, 160), altitude_checkbox_rect, 1)
    if altitude_filter_above:
        pygame_module.draw.line(surface, (0, 255, 0), (altitude_checkbox_rect.left + 3, altitude_checkbox_rect.centery), (altitude_checkbox_rect.centerx, altitude_checkbox_rect.bottom - 4), 2)
        pygame_module.draw.line(surface, (0, 255, 0), (altitude_checkbox_rect.centerx, altitude_checkbox_rect.bottom - 4), (altitude_checkbox_rect.right - 3, altitude_checkbox_rect.top + 3), 2)

    draw_text_module.normal(surface, 'ABOVE', text_font, (255, 255, 255), altitude_checkbox_rect.right + 8, altitude_checkbox_rect.top - 1)
    draw_text_module.normal(surface, f"{int(altitude_filter_threshold)} FT", stat_font, (255, 255, 255), panel_rect.left + 8, altitude_checkbox_rect.bottom + 4)

    pygame_module.draw.rect(surface, (35, 35, 35), altitude_slider_track_rect, 0)
    pygame_module.draw.rect(surface, (100, 100, 100), altitude_slider_track_rect, 1)
    pygame_module.draw.line(surface, (0, 255, 255), (altitude_slider_track_rect.centerx, altitude_slider_track_rect.top + 4), (altitude_slider_track_rect.centerx, altitude_slider_track_rect.bottom - 4), 3)

    for alt_mark in [0, 10000, 20000, 30000, 40000, 50000]:
        tick_ratio = 1.0 - (alt_mark / 50000.0)
        tick_y = altitude_slider_track_rect.top + int(tick_ratio * altitude_slider_track_rect.height)
        pygame_module.draw.line(surface, (120, 120, 120), (altitude_slider_track_rect.left, tick_y), (altitude_slider_track_rect.left + 8, tick_y), 1)
        draw_text_module.normal(surface, f"{alt_mark // 1000}", graph_time_font, (180, 180, 180), altitude_slider_track_rect.right + 6, tick_y - 4)

    pygame_module.draw.rect(surface, (255, 255, 0), altitude_slider_handle_rect, 0)
    pygame_module.draw.rect(surface, (255, 255, 255), altitude_slider_handle_rect, 1)
    draw_step_button(surface, altitude_up_button_rect, 'up', pygame_module)
    draw_step_button(surface, altitude_down_button_rect, 'down', pygame_module)

    pygame_module.draw.rect(surface, (20, 20, 20), distance_checkbox_rect, 0)
    pygame_module.draw.rect(surface, (160, 160, 160), distance_checkbox_rect, 1)
    if distance_filter_outside:
        pygame_module.draw.line(surface, (0, 255, 0), (distance_checkbox_rect.left + 3, distance_checkbox_rect.centery), (distance_checkbox_rect.centerx, distance_checkbox_rect.bottom - 4), 2)
        pygame_module.draw.line(surface, (0, 255, 0), (distance_checkbox_rect.centerx, distance_checkbox_rect.bottom - 4), (distance_checkbox_rect.right - 3, distance_checkbox_rect.top + 3), 2)

    unit_suffix = distance_unit.lower()
    unit_divisor = 1.852 if distance_unit == 'NM' else (1.609344 if distance_unit == 'MI' else 1.0)
    displayed_distance = distance_filter_threshold_km / unit_divisor
    draw_text_module.normal(surface, 'OUTSIDE', text_font, (255, 255, 255), distance_checkbox_rect.right + 8, distance_checkbox_rect.top - 1)
    draw_text_module.normal(surface, f"{round(displayed_distance, 1)} {unit_suffix}", stat_font, (255, 255, 255), distance_slider_track_rect.left - 4, distance_checkbox_rect.bottom + 4)

    pygame_module.draw.rect(surface, (35, 35, 35), distance_slider_track_rect, 0)
    pygame_module.draw.rect(surface, (100, 100, 100), distance_slider_track_rect, 1)
    pygame_module.draw.line(surface, (0, 255, 255), (distance_slider_track_rect.centerx, distance_slider_track_rect.top + 4), (distance_slider_track_rect.centerx, distance_slider_track_rect.bottom - 4), 3)

    for mark_index in range(6):
        distance_mark_km = (1000.0 / 5.0) * mark_index
        tick_ratio = 1.0 - (distance_mark_km / 1000.0)
        tick_y = distance_slider_track_rect.top + int(tick_ratio * distance_slider_track_rect.height)
        display_mark = distance_mark_km / unit_divisor
        pygame_module.draw.line(surface, (120, 120, 120), (distance_slider_track_rect.left, tick_y), (distance_slider_track_rect.left + 8, tick_y), 1)
        draw_text_module.normal(surface, f"{int(round(display_mark))}", graph_time_font, (180, 180, 180), distance_slider_track_rect.right + 6, tick_y - 4)

    pygame_module.draw.rect(surface, (255, 255, 0), distance_slider_handle_rect, 0)
    pygame_module.draw.rect(surface, (255, 255, 255), distance_slider_handle_rect, 1)
    draw_step_button(surface, distance_up_button_rect, 'up', pygame_module)
    draw_step_button(surface, distance_down_button_rect, 'down', pygame_module)

    for unit_key, rect in distance_unit_rects.items():
        pygame_module.draw.rect(surface, (20, 20, 20), rect, 0)
        pygame_module.draw.rect(surface, (160, 160, 160), rect, 1)
        if distance_unit == unit_key:
            pygame_module.draw.line(surface, (0, 255, 0), (rect.left + 3, rect.centery), (rect.centerx, rect.bottom - 4), 2)
            pygame_module.draw.line(surface, (0, 255, 0), (rect.centerx, rect.bottom - 4), (rect.right - 3, rect.top + 3), 2)
        draw_text_module.normal(surface, unit_key, text_font, (255, 255, 255), rect.right + 6, rect.top - 1)


def draw_line_graph(surface, rect, samples, y_max, draw_text_module, text_font, pygame_module, display_y_max, now=None, time_window_seconds=30 * 60, title=None, border_color=(100, 100, 100)):
    pygame_module.draw.rect(surface, border_color, rect, 1)

    inner_rect = rect.inflate(-12, -12)
    if inner_rect.width <= 1 or inner_rect.height <= 1:
        return

    plot_rect = inner_rect
    pygame_module.draw.rect(surface, (15, 15, 15), inner_rect)

    y_min = 0
    y_max = max(1, int(y_max))
    now = now or time.time()

    if samples:
        first_visible_time = samples[0][0]
        min_time = max(first_visible_time, now - time_window_seconds)
    else:
        min_time = now - time_window_seconds
    max_time = max(now, min_time + 1)

    old_clip = surface.get_clip()
    surface.set_clip(plot_rect)
    pygame_module.draw.line(surface, (45, 45, 45), (plot_rect.left, plot_rect.bottom - 1), (plot_rect.right - 1, plot_rect.bottom - 1), 1)

    if samples:
        points = []
        for timestamp, value in samples:
            if timestamp < min_time or timestamp > max_time:
                continue
            x_ratio = (timestamp - min_time) / max(1, (max_time - min_time))
            clamped_value = max(y_min, min(y_max, value))
            y_ratio = (clamped_value - y_min) / max(1, (y_max - y_min))
            x = plot_rect.left + int(x_ratio * (plot_rect.width - 1))
            y = plot_rect.bottom - 1 - int(y_ratio * (plot_rect.height - 1))
            x = max(plot_rect.left, min(plot_rect.right - 1, x))
            y = max(plot_rect.top, min(plot_rect.bottom - 1, y))
            points.append((x, y))

        if len(points) >= 2:
            pygame_module.draw.lines(surface, (0, 255, 255), False, points, 2)
        for point in points:
            pygame_module.draw.circle(surface, (255, 255, 0), point, 2)

    surface.set_clip(old_clip)

    y_max_img = text_font.render(str(display_y_max), True, (255, 255, 255))
    y_max_rect = y_max_img.get_rect(topleft=(rect.left + 6, rect.top + 3))
    surface.blit(y_max_img, y_max_rect)

    if title:
        title_img = text_font.render(title, True, (255, 255, 255))
        title_rect = title_img.get_rect(topright=(rect.right - 6, rect.top + 3))
        surface.blit(title_img, title_rect)
    draw_text_module.normal(surface, '0', text_font, (255, 255, 255), rect.left + 4, rect.bottom - 14)


def draw_polar_coverage_plot(surface, rect, history, draw_text_module, text_font, graph_time_font, pygame_module, now=None, time_window_seconds=24 * 60 * 60, sector_count=8):
    pygame_module.draw.rect(surface, (100, 100, 100), rect, 1)
    pygame_module.draw.rect(surface, (15, 15, 15), rect.inflate(-2, -2), 0)

    inner_margin = 12
    plot_rect = rect.inflate(-(inner_margin * 2), -(inner_margin * 2))
    if plot_rect.width <= 10 or plot_rect.height <= 10:
        return

    center_x, center_y = plot_rect.center
    max_radius = max(8, min(plot_rect.width, plot_rect.height) // 2 - 2)

    for radius_ratio in (0.25, 0.5, 0.75, 1.0):
        pygame_module.draw.circle(surface, (40, 40, 40), (center_x, center_y), max(1, int(max_radius * radius_ratio)), 1)

    for angle_deg in (0, 45, 90, 135):
        angle_rad = math.radians(angle_deg)
        dx = math.sin(angle_rad) * max_radius
        dy = math.cos(angle_rad) * max_radius
        pygame_module.draw.line(surface, (50, 50, 50), (center_x - int(dx), center_y + int(dy)), (center_x + int(dx), center_y - int(dy)), 1)

    totals = aggregate_directional_hits(history, sector_count, now, time_window_seconds)
    peak = max(totals, default=0)

    if peak > 0:
        sector_width = 360.0 / max(1, sector_count)
        points = []
        for index, count in enumerate(totals):
            angle_deg = (index * sector_width) + (sector_width / 2)
            radius = (count / peak) * max_radius
            angle_rad = math.radians(angle_deg)
            x = center_x + math.sin(angle_rad) * radius
            y = center_y - math.cos(angle_rad) * radius
            points.append((int(round(x)), int(round(y))))

        if len(points) >= 3:
            pygame_module.draw.lines(surface, (0, 255, 255), True, points, 2)
        for point in points:
            pygame_module.draw.circle(surface, (255, 255, 0), point, 2)
    else:
        draw_text_module.center(surface, 'NO DATA', text_font, (120, 120, 120), center_x, center_y - 5)

    diagonal_offset = int(max_radius * 0.78)
    draw_text_module.center(surface, 'N', graph_time_font, (180, 180, 180), center_x, rect.top + 8)
    draw_text_module.center(surface, 'S', graph_time_font, (180, 180, 180), center_x, rect.bottom - 9)
    draw_text_module.center(surface, 'E', graph_time_font, (180, 180, 180), rect.right - 9, center_y)
    draw_text_module.center(surface, 'W', graph_time_font, (180, 180, 180), rect.left + 9, center_y)
    draw_text_module.center(surface, 'NE', graph_time_font, (180, 180, 180), center_x + diagonal_offset, center_y - diagonal_offset)
    draw_text_module.center(surface, 'SE', graph_time_font, (180, 180, 180), center_x + diagonal_offset, center_y + diagonal_offset)
    draw_text_module.center(surface, 'SW', graph_time_font, (180, 180, 180), center_x - diagonal_offset, center_y + diagonal_offset)
    draw_text_module.center(surface, 'NW', graph_time_font, (180, 180, 180), center_x - diagonal_offset, center_y - diagonal_offset)



def draw_filter_action_buttons(surface, heatmap_button_rect, hide_planes_button_rect, reset_filters_button_rect, radar_heatmap_enabled, hide_planes_mode, button_icons, *args):
    pygame_module = None
    for arg in reversed(args):
        if hasattr(arg, 'transform') and hasattr(arg, 'draw'):
            pygame_module = arg
            break
    if pygame_module is None:
        import pygame as pygame_module

    heatmap_icon = button_icons['heatmap_off'] if radar_heatmap_enabled else button_icons['heatmap_on']
    if hide_planes_mode == 0:
        plane_icon = button_icons['plane_and_text']
    elif hide_planes_mode == 1:
        plane_icon = button_icons['plane_only']
    else:
        plane_icon = button_icons['hide_plane']

    buttons = [
        (heatmap_button_rect, heatmap_icon, False),
        (hide_planes_button_rect, plane_icon, True),
        (reset_filters_button_rect, button_icons['clear_filters'], True),
    ]

    for rect, icon, use_white_background in buttons:
        if use_white_background:
            pygame_module.draw.rect(surface, (255, 255, 255), rect, 0)
        if icon is not None:
            scaled_icon = pygame_module.transform.smoothscale(icon, (rect.width, rect.height))
            surface.blit(scaled_icon, rect.topleft)


def draw_radar_heatmap(surface, radar_rect, hit_points, pygame_module):
    if not hit_points:
        return

    cell_size = 25
    cell_hits = {}
    for x, y in hit_points:
        local_x = int(x - radar_rect.left)
        local_y = int(y - radar_rect.top)
        if not (0 <= local_x < radar_rect.width and 0 <= local_y < radar_rect.height):
            continue

        cell_x = (local_x // cell_size) * cell_size
        cell_y = (local_y // cell_size) * cell_size
        key = (cell_x, cell_y)
        cell_hits[key] = cell_hits.get(key, 0) + 1

    if not cell_hits:
        return

    max_hit_count = max(cell_hits.values())
    capped_max_hit_count = min(max_hit_count, 10000)
    heatmap_surface = pygame_module.Surface((radar_rect.width, radar_rect.height), pygame_module.SRCALPHA)

    for (cell_x, cell_y), hit_count in cell_hits.items():
        capped_hit_count = min(hit_count, 10000)
        if capped_max_hit_count <= 1:
            red_value = 5
        else:
            intensity_ratio = (capped_hit_count - 1) / max(1, capped_max_hit_count - 1)
            red_value = 5 + int(intensity_ratio * 250)
        red_value = max(5, min(255, red_value))
        pygame_module.draw.rect(
            heatmap_surface,
            (red_value, 0, 0, 255),
            (cell_x, cell_y, cell_size, cell_size),
            0,
        )

    surface.blit(heatmap_surface, radar_rect.topleft)
