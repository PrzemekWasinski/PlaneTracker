"""Optional Proxmox host temperature via a restricted SSH sensor account."""

import json
import math
import os
from pathlib import Path
import subprocess


def read_host_temperature():
    host = os.environ.get("PLANE_TRACKER_TEMPERATURE_HOST", "").strip()
    if not host:
        return None
    user = os.environ.get("PLANE_TRACKER_TEMPERATURE_USER", "planetracker-temp")
    key = Path(os.environ.get("PLANE_TRACKER_TEMPERATURE_KEY", "~/.ssh/planetracker_temp")).expanduser()
    try:
        result = subprocess.run(
            ["ssh", "-T", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
             "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=2",
             "-i", str(key), "-l", user, "--", host, "sensors -j"],
            capture_output=True, text=True, timeout=3, check=True,
        )
        sensors = json.loads(result.stdout)
        for chip, readings in sensors.items():
            if chip.startswith("k10temp"):
                for label in ("Tctl", "Tdie"):
                    for name, value in readings.get(label, {}).items():
                        if name.endswith("_input"):
                            temperature = float(value)
                            if math.isfinite(temperature) and -50 <= temperature <= 150:
                                return temperature
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        pass
    return None
