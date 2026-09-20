"""Serve the live web UI and a read-only, same-origin snapshot API."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit
import webbrowser

import yaml

from .state import LiveState, number
from .firebase import StatsUploader

ROOT = Path(__file__).resolve().parents[3]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, state, directory, **kwargs):
        self.state = state
        super().__init__(*args, directory=directory, **kwargs)

    def _json(self, value):
        payload = json.dumps(value, allow_nan=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/state":
            return self._json(self.state.snapshot())
        if path == "/api/config":
            return self._json({"mapStyle": self.state.map_style, "home": {
                "lat": self.state.home[0], "lon": self.state.home[1]}})
        if path.startswith("/api/"):
            return self.send_error(404)
        return super().do_GET()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def log_message(self, format, *args):
        if args and str(args[1] if len(args) > 1 else "") not in {"200", "304"}:
            super().log_message(format, *args)


def open_browser(url):
    # SSH sessions may choose a blocking text browser, which cannot render this UI.
    if sys.platform.startswith("linux") and not any(os.environ.get(key) for key in ("DISPLAY", "WAYLAND_DISPLAY")):
        print("No graphical desktop detected; open the URL in a browser on your computer.", flush=True)
        return None
    thread = threading.Thread(target=webbrowser.open, args=(url,), name="web-browser", daemon=True)
    thread.start()
    return thread


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/config.yml")
    parser.add_argument("--source", help="readsb aircraft.json local/shared path or HTTP(S) URL")
    parser.add_argument("--history-dir", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = yaml.safe_load(args.config.read_text(encoding="utf-8-sig")) or {}
    except FileNotFoundError:
        config = {}
    except (OSError, yaml.YAMLError) as exc:
        parser.error(f"Cannot read config: {exc}")
    if not isinstance(config, dict):
        parser.error("Config must be a YAML mapping")
    lat, lon = number(config.get("myLat")), number(config.get("myLon"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        parser.error("Set a valid myLat and myLon in config/config.yml")
    source = args.source or os.environ.get("PLANE_TRACKER_READSB_SOURCE") or config.get("readsbUrl") or config.get("readsbJsonPath") or "/run/readsb/aircraft.json"
    if not source.startswith(("http://", "https://")):
        source_path = Path(source)
        source = str(source_path if source_path.is_absolute() else ROOT / source_path)
    history = args.history_dir or Path(config.get("flightHistoryDir", "./flight_history"))
    if not history.is_absolute():
        history = ROOT / history
    dist = ROOT / "src/plane_tracker/gui/dist"
    if not (dist / "index.html").exists():
        parser.error("Build the frontend first: cd src/plane_tracker/gui && npm ci && npm run build")
    state = LiveState(source, (lat, lon), history, ROOT / "config/icao_cache.json",
                      config.get("mapStyleUrl", "https://tiles.openfreemap.org/styles/dark"),
                      metadata_enabled=not config.get("offlineMode", False))
    server = ThreadingHTTPServer((args.host, args.port), partial(Handler, state=state, directory=str(dist)))
    server.daemon_threads = True
    state.start()
    uploader = None
    if not config.get('offlineMode', False):
        uploader = StatsUploader(state, ROOT / 'config/firebase.json')
        uploader.start()
    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}/"
    print(f"Web UI: {url}", flush=True)
    print(f"Receiver source: {source}", flush=True)
    if args.host == "0.0.0.0":
        print(f"From another computer, use http://<this-machine-LAN-IP>:{args.port}/", flush=True)
    if args.open:
        open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if uploader is not None:
            uploader.stop()
        state.stop()


if __name__ == "__main__":
    main()
