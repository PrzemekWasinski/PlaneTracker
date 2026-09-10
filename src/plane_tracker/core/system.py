import multiprocessing
import os
import shutil
import sys
import time


def get_disk_free():
    try:
        total, used, free = shutil.disk_usage("/")
        return round(free / (2**30), 1)
    except Exception:
        return 0.0


def restart_script():
    print("Restarting script")
    for child in multiprocessing.active_children():
        child.terminate()
        child.join(timeout=2)
    time.sleep(0.25)
    os.execv(sys.executable, [sys.executable, *sys.argv])
