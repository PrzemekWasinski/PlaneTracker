import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yml"


def load_config():
    if not CONFIG_PATH.exists():
        print(f"{CONFIG_PATH} not found creating default config")
        CONFIG_PATH.write_text("{}\n", encoding="utf-8")
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            return yaml.safe_load(config_file) or {}
    except yaml.YAMLError as error:
        print(f"Error parsing config.yml: {error}")
        sys.exit(1)


def save_config(config):
    try:
        with CONFIG_PATH.open("w", encoding="utf-8") as config_file:
            yaml.safe_dump(config, config_file, default_flow_style=False)
        return True
    except Exception as error:
        print(f"Error saving config.yml: {error}")
        return False
