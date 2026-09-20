"""Background publishing of daily statistics using the legacy Firebase schema."""
from collections import Counter
from datetime import datetime
import threading

from ..orchestration import FIREBASE_DATABASE_URL
from ..core.geometry import calculate_distance
from .state import number, text


def daily_payload(state):
    with state.lock:
        state._roll_day(datetime.now().date())
        rows = state._rows()
        day = state.day.isoformat()
        if not rows:
            return day, None

        def leader(values):
            counts = Counter(value for value in values if value)
            name, count = counts.most_common(1)[0] if counts else ('', 0)
            return {'name': name, 'count': count}

        def model(row):
            name = text(row.get('model')) or ''
            maker = text(row.get('manufacturer')) or ''
            return f'{maker} {name}'.strip() if name and not name.lower().startswith(maker.lower()) else name

        furthest = None
        for icao, row in rows.items():
            distance = number(row.get('distance'))
            if distance is None:
                lat, lon = number(row.get('lat')), number(row.get('lon'))
                if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
                    distance = calculate_distance(*state.home, lat, lon)
            if distance is not None and (furthest is None or distance > furthest['distance_km']):
                furthest = {'icao': icao, 'flight': text(row.get('flight')) or '-',
                            'model': text(row.get('model')) or '-',
                            'airline': text(row.get('owner')) or '-', 'distance_km': round(distance, 2)}
        return day, {
            'total_aircraft': len(rows),
            'top_airline': leader(text(row.get('owner')) for row in rows.values()),
            'top_aircraft': leader(model(row) for row in rows.values()),
            'furthest_aircraft_km': furthest['distance_km'] if furthest else None,
            'furthest_plane': furthest,
            'last_updated': datetime.now().strftime('%H-%M-%S'),
        }


class StatsUploader:
    def __init__(self, state, credentials_path):
        self.state = state
        self.credentials_path = credentials_path
        self.stop_event = threading.Event()
        self.thread = None
        self.app = None

    def upload_once(self):
        day, payload = daily_payload(self.state)
        if payload is None:
            return
        import firebase_admin
        from firebase_admin import credentials, db
        if self.app is None:
            self.app = firebase_admin.initialize_app(
                credentials.Certificate(str(self.credentials_path)),
                {'databaseURL': FIREBASE_DATABASE_URL, 'httpTimeout': 10},
                name='plane-tracker-web-stats')
        # Retain unrelated fields already present at the existing daily node.
        db.reference(day, app=self.app).update(payload)
        with self.state.lock:
            self.state._event(f"Firebase updated: {payload['total_aircraft']} aircraft")

    def _run(self):
        try:
            while not self.stop_event.is_set():
                try:
                    self.upload_once()
                except Exception as error:
                    # Avoid logging credential paths, secrets or SDK response bodies.
                    with self.state.lock:
                        self.state._event(f'Firebase upload failed ({type(error).__name__}); retrying in 60s', 'warning')
                self.stop_event.wait(60)
        finally:
            if self.app is not None:
                import firebase_admin
                firebase_admin.delete_app(self.app)
                self.app = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name='firebase-stats', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=12)
