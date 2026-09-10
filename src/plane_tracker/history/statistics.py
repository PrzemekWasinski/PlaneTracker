import ast
import os
from collections import Counter
from datetime import datetime, timedelta
from time import localtime, strftime

from ..core.geometry import calculate_distance


_STATS_NUMERIC_COLS = [
    "altitude", "alt_geom", "speed", "mach", "baro_rate", "geom_rate",
    "ias", "tas", "lat", "lon", "messages", "rssi", "roll", "oat", "tat",
]


def get_stats(home_lat=None, home_lon=None, flight_history_dir='./flight_history', now=None):
    import pandas as pd

    now = now or datetime.now()
    today = now.strftime('%Y-%m-%d')

    default_stats = {
        'total': 0,
        'top_model': {'name': None, 'count': 0},
        'top_manufacturer': {'name': None, 'count': 0},
        'top_aircraft': {'name': None, 'count': 0},
        'top_airline': {'name': None, 'count': 0},
        'manufacturer_breakdown': {},
        'furthest_detected': None,
        'furthest_plane': None,
        'highest_detected': None,
        'unique_airlines': 0,
        'unique_models': 0,
        'unique_manufacturers': 0,
        'emergencies_count': 0,
        'avg_altitude': None,
        'avg_speed': None,
        'max_speed': None,
        'max_hits': None,
        'avg_mach': None,
        'last_updated': strftime('%H:%M:%S', localtime()),
    }

    today_path = os.path.join(flight_history_dir, f'{today}.csv')
    stats_paths = [today_path] if os.path.exists(today_path) else []

    try:
        frames = [pd.read_csv(csv_path, low_memory=False) for csv_path in stats_paths]
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


        for col in _STATS_NUMERIC_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].replace("-", pd.NA), errors="coerce")


        for col in ("first_seen", "last_seen"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")




        stats_index_path = os.path.join(
            os.path.dirname(os.path.abspath(flight_history_dir)),
            'stats_history',
            'stats.csv',
        )
        index_df = None
        if os.path.exists(stats_index_path):
            try:
                index_df = pd.read_csv(stats_index_path, low_memory=False)
                index_df = index_df.rename(columns={
                    'airline': 'owner',
                    'timestamp': 'last_seen',
                })
            except (OSError, ValueError, pd.errors.ParserError, UnicodeDecodeError):
                index_df = None

        if index_df is not None and not index_df.empty and not df.empty:
            if 'icao' in df.columns and 'icao' in index_df.columns:
                lookup = index_df.drop_duplicates('icao', keep='last').set_index('icao')
                for col in ('manufacturer', 'model', 'owner', 'registration'):
                    if col not in lookup.columns:
                        continue
                    if col not in df.columns:
                        df[col] = pd.NA
                    else:
                        df[col] = df[col].astype(object)
                    missing = df[col].isna() | df[col].astype(str).str.strip().isin(('', '-', 'none', 'None'))
                    df.loc[missing, col] = df.loc[missing, 'icao'].map(lookup[col])


        for col in ("owner", "manufacturer", "model", "category", "emergency", "registration"):
            if col in df.columns:
                df[col] = df[col].replace(["-", "none", "None", ""], pd.NA)


        if "icao" in df.columns and "first_seen" in df.columns:
            df = df.drop_duplicates(subset=["icao", "first_seen"])

        total = len(df)




        max_hits = None
        #Count history entries without parsing large dictionaries
        if 'location_history' in df.columns:
            def _location_history_length(value):
                if isinstance(value, dict):
                    return len(value)
                if not isinstance(value, str) or not value.strip():
                    return 0





                return value.count('[')

            history_lengths = df['location_history'].map(_location_history_length)
            if not history_lengths.empty:
                max_hits = int(history_lengths.max())

        def _top(series):
            counts = series.dropna().value_counts()
            if counts.empty:
                return None, 0
            return counts.index[0], int(counts.iloc[0])

        top_model_name, top_model_count = _top(df['model']) if 'model' in df.columns else (None, 0)
        top_mfr_name, top_mfr_count = _top(df['manufacturer']) if 'manufacturer' in df.columns else (None, 0)
        top_airline_name, top_airline_count = _top(df['owner']) if 'owner' in df.columns else (None, 0)




        top_aircraft_name, top_aircraft_count = (None, 0)
        if top_model_name is not None and 'manufacturer' in df.columns:
            matching_rows = df.loc[df['model'] == top_model_name, 'manufacturer'].dropna()
            if not matching_rows.empty:
                top_aircraft_name = f"{matching_rows.iloc[0]} {top_model_name}"
                top_aircraft_count = top_model_count

        mfr_breakdown = {}
        if 'manufacturer' in df.columns:
            mfr_breakdown = {
                clean_string(str(k)): int(v)
                for k, v in df['manufacturer'].dropna().value_counts().items()
            }

        unique_airlines = int(df['owner'].nunique()) if 'owner' in df.columns else 0
        unique_models = int(df['model'].nunique()) if 'model' in df.columns else 0
        unique_manufacturers = int(df['manufacturer'].nunique()) if 'manufacturer' in df.columns else 0
        emergencies_count = int(df['emergency'].notna().sum()) if 'emergency' in df.columns else 0

        avg_altitude = None
        highest = None
        if 'altitude' in df.columns:
            val = df['altitude'].mean()
            if pd.notna(val):
                avg_altitude = int(round(float(val)))
            alt_max = df['altitude'].max()
            if pd.notna(alt_max):
                highest = int(alt_max)

        avg_speed = None
        max_speed = None
        if 'speed' in df.columns:
            val = df['speed'].mean()
            if pd.notna(val):
                avg_speed = int(round(float(val)))
            val = df['speed'].max()
            if pd.notna(val):
                max_speed = int(round(float(val)))

        avg_mach = None
        if 'mach' in df.columns:
            val = df['mach'].mean()
            if pd.notna(val):
                avg_mach = round(float(val), 3)

        furthest = None
        furthest_plane = None
        if home_lat is not None and home_lon is not None and 'lat' in df.columns and 'lon' in df.columns:
            valid = df[df['lat'].notna() & df['lon'].notna()]
            best = 0.0
            best_row = None
            for _, row in valid.iterrows():
                try:
                    d = calculate_distance(float(home_lat), float(home_lon), row['lat'], row['lon'])
                    if d > best:
                        best = d
                        best_row = row
                except (ValueError, TypeError):
                    pass
            if best > 0:
                furthest = best
                if best_row is not None:
                    furthest_plane = {
                        'icao': str(best_row.get('icao', '-')),
                        'flight': str(best_row.get('flight', '-')),
                        'model': str(best_row.get('model', '-')),
                        'airline': str(best_row.get('owner', '-')),
                        'distance_km': round(best, 2),
                    }

        return {
            'total': total,
            'top_model': {'name': top_model_name, 'count': top_model_count},
            'top_manufacturer': {'name': top_mfr_name, 'count': top_mfr_count},
            'top_aircraft': {'name': top_aircraft_name, 'count': top_aircraft_count},
            'top_airline': {'name': top_airline_name, 'count': top_airline_count},
            'manufacturer_breakdown': mfr_breakdown,
            'furthest_detected': furthest,
            'furthest_plane': furthest_plane,
            'highest_detected': highest,
            'unique_airlines': unique_airlines,
            'unique_models': unique_models,
            'unique_manufacturers': unique_manufacturers,
            'emergencies_count': emergencies_count,
            'avg_altitude': avg_altitude,
            'avg_speed': avg_speed,
            'max_speed': max_speed,
            'max_hits': max_hits,
            'avg_mach': avg_mach,
            'last_updated': strftime('%H:%M:%S', localtime()),
        }

    except Exception as e:
        print(f"Error reading stats: {e}")
        return default_stats
