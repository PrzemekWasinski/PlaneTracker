def start_background_services():

    global _background_services_started
    if _background_services_started:
        return
    _background_services_started = True
    for target in (
        adsb_processing_thread,
        flight_stats_refresh_thread,
    ):
        threading.Thread(target=target, daemon=True).start()


FIREBASE_DATABASE_URL = "https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app"


def initialise_firebase():

    import firebase_admin
    from firebase_admin import credentials

    if not firebase_admin._apps:
        certificate = credentials.Certificate(PROJECT_ROOT / "config" / "firebase.json")
        firebase_admin.initialize_app(certificate, {"databaseURL": FIREBASE_DATABASE_URL})


def upload_daily_stats(stats):

    from firebase_admin import db

    total = stats.get("total", 0)
    if total <= 0:
        return
    today = datetime.today().strftime("%Y-%m-%d")
    top_airline = stats.get("top_airline", {})
    top_aircraft = stats.get("top_aircraft", {})
    furthest = stats.get("furthest_detected")
    db.reference(today).set({
        "total_aircraft": total,
        "top_airline": {"name": top_airline.get("name") or "", "count": top_airline.get("count") or 0},
        "top_aircraft": {"name": top_aircraft.get("name") or "", "count": top_aircraft.get("count") or 0},
        "furthest_aircraft_km": round(furthest, 2) if furthest is not None else None,
        "furthest_plane": stats.get("furthest_plane"),
        "last_updated": datetime.now().strftime("%H-%M-%S"),
    })


def main():
    from .gui.legacy import window as gui

    if IS_WINDOWS:
        gui.run(mode="preview")
        return
    initialise_firebase()
    gui.run(mode="production", stats_uploader=upload_daily_stats)


if __name__ == "__main__":
    main()
