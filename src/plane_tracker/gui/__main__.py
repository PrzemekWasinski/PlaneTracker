import os

os.environ.setdefault("PLANE_TRACKER_DEV_GUI", "1")

from .legacy.window import run


if __name__ == "__main__":
    run(mode="preview")
