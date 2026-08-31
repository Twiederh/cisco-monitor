"""Persists connection settings + labels to a local JSON file so the
monitor can auto-reconnect after a restart. May contain secrets (SSH
password / key passphrase / enable password) if the user supplied them,
so the file is created with 0600 permissions.
"""
import json
import os

CONFIG_DIR = os.environ.get("CONFIG_DIR") or os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# "Störungsfälle": a full 'show logging' captured automatically the moment
# the poller notices a SIP-UA registration go away, so it survives past the
# rolling in-memory log window (see poller.py's Monitor._capture_incident).
INCIDENTS_DIR = os.path.join(CONFIG_DIR, "incidents")


def list_incidents():
    """Filenames of captured incidents, newest first. Filenames are
    '<timestamp>.log' with a sortable timestamp, so a plain reverse
    alphabetical sort is also newest-first."""
    if not os.path.isdir(INCIDENTS_DIR):
        return []
    names = [n for n in os.listdir(INCIDENTS_DIR) if n.endswith(".log")]
    names.sort(reverse=True)
    return names


def list_incidents_meta():
    """list_incidents() plus each file's size and the one-line reason from
    its own header, for the /api/incidents listing."""
    out = []
    for name in list_incidents():
        path = os.path.join(INCIDENTS_DIR, name)
        reason = ""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("Grund: "):
                        reason = line[len("Grund: "):].strip()
                        break
        except OSError:
            pass
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        out.append({"filename": name, "reason": reason, "size": size})
    return out


def incident_path(filename):
    """Resolve a filename from the incidents dir to its full path, or None
    if it's not one of the files actually in there (guards against path
    traversal via a crafted filename in the download route)."""
    if filename not in list_incidents():
        return None
    return os.path.join(INCIDENTS_DIR, filename)


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
