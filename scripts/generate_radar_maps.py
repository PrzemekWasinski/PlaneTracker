import argparse
import math
from pathlib import Path

try:
    import shapefile  # pyshp
except ImportError as exc:
    raise SystemExit('Missing dependency: pyshp. Install with: pip install pyshp pillow pyyaml') from exc

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    raise SystemExit('Missing dependency: pillow. Install with: pip install pyshp pillow pyyaml') from exc

try:
    import yaml
except ImportError as exc:
    raise SystemExit('Missing dependency: pyyaml. Install with: pip install pyshp pillow pyyaml') from exc

IMAGE_SIZE = 1080
CENTER = IMAGE_SIZE // 2
RANGES_KM = list(range(25, 1001, 25))
CITY_SCALERANK_MAX = 6
COLORS = {
    'background': (0, 0, 0),
    'country': (175, 175, 175),
    'city_point': (220, 220, 220),
    'city_label': (180, 180, 180),
}



def load_config(config_path: Path) -> dict:
    with config_path.open('r', encoding='utf-8') as fh:
        return yaml.safe_load(fh) or {}



def km_per_pixel(range_km: float) -> float:
    return (range_km * 2.0) / 1024.0


def latlon_to_xy(lat: float, lon: float, center_lat: float, center_lon: float, range_km: float):
    scale = km_per_pixel(range_km)
    dy_km = (lat - center_lat) * 111.0
    dx_km = (lon - center_lon) * 111.0 * math.cos(math.radians(center_lat))
    x = CENTER + int(dx_km / scale)
    y = CENTER - int(dy_km / scale)
    return x, y


def bbox_for_range(center_lat: float, center_lon: float, range_km: float):
    lat_delta = range_km / 111.0
    lon_delta = range_km / max(1e-6, (111.0 * math.cos(math.radians(center_lat))))
    return (
        center_lon - lon_delta,
        center_lat - lat_delta,
        center_lon + lon_delta,
        center_lat + lat_delta,
    )


def bbox_intersects(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def shape_parts(points, parts):
    indices = list(parts) + [len(points)]
    for start, end in zip(indices, indices[1:]):
        yield points[start:end]


def split_visible_segments(points, margin=100):
    segments = []
    current_segment = []

    for x, y in points:
        is_visible = -margin <= x <= IMAGE_SIZE + margin and -margin <= y <= IMAGE_SIZE + margin
        if is_visible:
            current_segment.append((x, y))
        else:
            if len(current_segment) >= 2:
                segments.append(current_segment)
            current_segment = []

    if len(current_segment) >= 2:
        segments.append(current_segment)

    return segments


def draw_country_shapes(draw, reader, center_lat, center_lon, range_km, bounds, color, width):
    for shape_record in reader.iterShapeRecords():
        shape = shape_record.shape
        if hasattr(shape, 'bbox') and not bbox_intersects(shape.bbox, bounds):
            continue
        for part in shape_parts(shape.points, shape.parts):
            xy = [latlon_to_xy(lat, lon, center_lat, center_lon, range_km) for lon, lat in part]
            for segment in split_visible_segments(xy):
                draw.line(segment, fill=color, width=width)


def draw_cities(draw, reader, center_lat, center_lon, range_km, bounds, font):
    for record in reader.iterShapeRecords():
        shape = record.shape
        lon, lat = shape.points[0]
        if not (bounds[0] <= lon <= bounds[2] and bounds[1] <= lat <= bounds[3]):
            continue

        attrs = record.record.as_dict()
        scalerank = attrs.get('SCALERANK', 99)
        try:
            scalerank = int(scalerank)
        except (TypeError, ValueError):
            scalerank = 99
        if scalerank > CITY_SCALERANK_MAX:
            continue

        x, y = latlon_to_xy(lat, lon, center_lat, center_lon, range_km)
        if not (0 <= x < IMAGE_SIZE and 0 <= y < IMAGE_SIZE):
            continue

        draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=COLORS['city_point'])
        name = attrs.get('NAME', '')
        if name:
            draw.text((x + 4, y - 6), str(name), fill=COLORS['city_label'], font=font)


def build_map(country_reader, city_reader, center_lat, center_lon, range_km, font, output_path: Path):
    bounds = bbox_for_range(center_lat, center_lon, range_km)
    image = Image.new('RGB', (IMAGE_SIZE, IMAGE_SIZE), COLORS['background'])
    draw = ImageDraw.Draw(image)

    draw_country_shapes(draw, country_reader, center_lat, center_lon, range_km, bounds, COLORS['country'], 1)
    draw_cities(draw, city_reader, center_lat, center_lon, range_km, bounds, font)

    image.save(output_path)


def main():
    parser = argparse.ArgumentParser(description='Generate monochrome radar base maps from Natural Earth data.')
    parser.add_argument('--config', default='config/config.yml', help='Path to app config.yml')
    parser.add_argument('--data-root', default='textures/natural_earth', help='Root folder containing Natural Earth shapefiles')
    parser.add_argument('--output-dir', default='textures/radar_map', help='Output folder for generated PNG maps')
    parser.add_argument('--ranges', nargs='*', type=int, default=RANGES_KM, help='Radar ranges in km to generate')
    args = parser.parse_args()

    config = load_config(Path(args.config))
    center_lat = float(config['myLat'])
    center_lon = float(config['myLon'])

    data_root = Path(args.data_root)
    cultural_dir = data_root / 'cultural'

    countries_path = cultural_dir / 'ne_10m_admin_0_countries.shp'
    cities_path = cultural_dir / 'ne_10m_populated_places.shp'

    missing = [str(path) for path in [countries_path, cities_path] if not path.exists()]
    if missing:
        raise SystemExit('Missing Natural Earth shapefiles:\n' + '\n'.join(missing))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    country_reader = shapefile.Reader(str(countries_path), encoding='latin1')
    city_reader = shapefile.Reader(str(cities_path), encoding='latin1')
    font = ImageFont.load_default()

    for range_km in args.ranges:
        output_path = output_dir / f'{range_km}.png'
        build_map(country_reader, city_reader, center_lat, center_lon, float(range_km), font, output_path)
        print(f'Generated {output_path}')


if __name__ == '__main__':
    main()
