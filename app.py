from flask import Flask, jsonify, render_template, request

import config_store
from poller import DEFAULT_COMMAND, monitor
from ssh_client import CiscoSSHError

app = Flask(__name__)


def persist():
    config_store.save(monitor.persistable_state())


@app.get("/")
def index():
    saved = config_store.load() or {}
    return render_template("index.html", default_command=DEFAULT_COMMAND, saved=saved)


@app.get("/api/status")
def api_status():
    return jsonify(monitor.snapshot())


@app.get("/healthz")
def healthz():
    """Plain HTTP status-code health check for external monitoring (e.g.
    Uptime Kuma as an 'HTTP(s)' monitor): 200 when every tenant is
    registered, 503 as soon as one reports reg != yes or disappears."""
    health = monitor.health()
    return jsonify(health), 200 if health["healthy"] else 503


@app.post("/api/connect")
def api_connect():
    data = request.get_json(force=True) or {}
    host = (data.get("host") or "").strip()
    username = (data.get("username") or "").strip()
    if not host or not username:
        return jsonify(error="Host und Benutzername sind erforderlich."), 400

    try:
        port = int(data.get("port") or 22)
        poll_interval = max(5, int(data.get("poll_interval") or 30))
    except ValueError:
        return jsonify(error="Port und Intervall müssen Zahlen sein."), 400

    # Blank secret fields fall back to whatever is already saved, so the
    # form doesn't need to echo passwords/passphrases back to reconnect.
    existing = config_store.load() or {}
    password = data.get("password") or existing.get("password") or None
    key_filename = (data.get("key_filename") or "").strip() or existing.get("key_filename") or None
    key_passphrase = data.get("key_passphrase") or existing.get("key_passphrase") or None
    enable_password = data.get("enable_password") or existing.get("enable_password") or None
    command = (data.get("command") or DEFAULT_COMMAND).strip()

    monitor.start(
        host=host,
        username=username,
        password=password,
        port=port,
        key_filename=key_filename,
        key_passphrase=key_passphrase,
        enable_password=enable_password,
        poll_interval=poll_interval,
        command=command,
    )
    persist()
    return jsonify(monitor.snapshot())


@app.post("/api/disconnect")
def api_disconnect():
    monitor.stop()
    return jsonify(monitor.snapshot())


@app.post("/api/labels")
def api_labels():
    data = request.get_json(force=True) or {}
    line = (data.get("line") or "").strip()
    if not line:
        return jsonify(error="line ist erforderlich."), 400
    title = (data.get("title") or "").strip()
    monitor.set_label(line, title)
    persist()
    return jsonify(labels=monitor.labels)


@app.post("/api/debug/start")
def api_debug_start():
    try:
        monitor.start_debug()
    except CiscoSSHError as exc:
        return jsonify(error=str(exc)), 409
    return jsonify(monitor.debug_status())


@app.post("/api/debug/stop")
def api_debug_stop():
    try:
        result = monitor.stop_debug()
    except CiscoSSHError as exc:
        return jsonify(error=str(exc)), 409
    return jsonify(result)


def autostart():
    saved = config_store.load()
    if not saved or not saved.get("host") or not saved.get("username"):
        return
    monitor.start(
        host=saved.get("host"),
        username=saved.get("username"),
        password=saved.get("password"),
        port=saved.get("port", 22),
        key_filename=saved.get("key_filename"),
        key_passphrase=saved.get("key_passphrase"),
        enable_password=saved.get("enable_password"),
        poll_interval=saved.get("poll_interval", 30),
        command=saved.get("command", DEFAULT_COMMAND),
    )
    monitor.labels = dict(saved.get("labels") or {})


autostart()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)
