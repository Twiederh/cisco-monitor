"""Persists connection settings + labels to a local JSON file so the
monitor can auto-reconnect after a restart. May contain secrets (SSH
password / key passphrase / enable password) if the user supplied them,
so the file is created with 0600 permissions.
"""
import json
import os

CONFIG_DIR = os.environ.get("CONFIG_DIR") or os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def load():
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save(data):
    tmp_path = CONFIG_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, CONFIG_PATH)
