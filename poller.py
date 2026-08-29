import re
import threading
import time
from collections import deque
from datetime import datetime

from parsers import parse_sip_ua_register_status
from ssh_client import CiscoSSHError, CiscoSSHSession

DEFAULT_COMMAND = "show sip-ua register status"
HISTORY_LIMIT = 50
LOG_COMMAND = "show logging"
LOG_ENTRY_LIMIT = 300
SEVERITY_RE = re.compile(r"%\S+-(\d)-\S+:")
DEBUG_COMMAND = "debug ccsip messages"


class Monitor:
    """Owns the SSH session + background poll loop + shared state.

    One global instance is used by the Flask app; all access to shared
    state goes through the lock since the poll thread and Flask request
    threads touch it concurrently.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._session = None
        self._thread = None
        self._stop_event = threading.Event()
        self.history = deque(maxlen=HISTORY_LIMIT)
        self.log_entries = deque(maxlen=LOG_ENTRY_LIMIT)  # new router log lines, most recent first
        self._last_log_raw = ""
        self.status = "idle"  # idle | connecting | running | error | stopped
        self.error = None
        self.config = None
        self.secrets = {}  # password / key_passphrase / enable_password - never in snapshot()
        self.labels = {}  # sip-ua "line" identifier -> user-chosen display title

        # dedicated second session for 'debug ...' capture, see start_debug()
        self._debug_lock = threading.Lock()
        self._debug_session = None
        self._debug_thread = None
        self._debug_stop_event = None
        self._debug_buffer = []
        self._debug_started_at = None

    def start(self, host, username, password=None, port=22,
              key_filename=None, key_passphrase=None,
              enable_password=None, poll_interval=30,
              command=DEFAULT_COMMAND):
        self.stop()
        self.config = {
            "host": host,
            "port": port,
            "username": username,
            "key_filename": key_filename,
            "poll_interval": poll_interval,
            "command": command,
        }
        self.secrets = {
            "password": password,
            "key_passphrase": key_passphrase,
            "enable_password": enable_password,
        }
        self._stop_event.clear()
        self.status = "connecting"
        self.error = None
        self._last_log_raw = ""  # fresh baseline; avoids re-showing old log history as "new"
        self._thread = threading.Thread(
            target=self._run,
            args=(host, username, password, port, key_filename,
                  key_passphrase, enable_password, poll_interval, command),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        with self._lock:
            if self._session:
                self._session.close()
                self._session = None
        self.status = "stopped"
        self._thread = None

    def _run(self, host, username, password, port, key_filename,
              key_passphrase, enable_password, poll_interval, command):
        session = CiscoSSHSession(
            host=host, username=username, password=password, port=port,
            key_filename=key_filename, key_passphrase=key_passphrase,
            enable_password=enable_password,
        )
        try:
            session.connect()
        except CiscoSSHError as exc:
            self.status = "error"
            self.error = str(exc)
            return

        with self._lock:
            self._session = session
        self.status = "running"

        while not self._stop_event.is_set():
            self._poll_once(command)
            self._poll_log()
            self._stop_event.wait(poll_interval)

    def _poll_once(self, command):
        with self._lock:
            session = self._session
        if session is None:
            return
        entry = {"timestamp": datetime.now().isoformat(timespec="seconds")}
        try:
            with self._lock:
                output = session.run_command(command)
            entry["command"] = command
            entry["output"] = output
            entry["ok"] = True
            entry["parsed"] = parse_sip_ua_register_status(output)
            self.error = None
        except CiscoSSHError as exc:
            entry["command"] = command
            entry["output"] = ""
            entry["ok"] = False
            entry["error"] = str(exc)
            self.error = str(exc)
            self.status = "error"
        self.history.appendleft(entry)

    def _poll_log(self):
        """Fetch 'show logging' and record only lines that are new since
        the last fetch (tail-diff on the raw buffer text), so the router's
        own error/warning messages accumulate here over time instead of
        being re-shown every poll."""
        with self._lock:
            session = self._session
        if session is None:
            return
        try:
            with self._lock:
                raw = session.run_command(LOG_COMMAND)
        except CiscoSSHError:
            return  # don't let a log-fetch hiccup break the main status poll

        new_lines = self._extract_new_log_lines(raw)
        now = datetime.now().isoformat(timespec="seconds")
        for line in new_lines:
            sm = SEVERITY_RE.search(line)
            severity = int(sm.group(1)) if sm else None
            self.log_entries.appendleft({
                "timestamp": now,
                "line": line,
                "severity": severity,  # Cisco syslog 0-7 (0=emergency ... 7=debug); None if unparsed
            })
        self._last_log_raw = raw

    def _extract_new_log_lines(self, raw):
        lines = [l for l in raw.splitlines() if l.strip()]
        if not self._last_log_raw:
            # first fetch after (re)connect: establish a baseline instead
            # of dumping the router's entire historical log buffer
            return []
        old_lines = [l for l in self._last_log_raw.splitlines() if l.strip()]
        if not old_lines:
            return lines
        last_old = old_lines[-1]
        if last_old in lines:
            idx = len(lines) - 1 - lines[::-1].index(last_old)
            return lines[idx + 1:]
        # marker line not found - buffer likely wrapped/cleared; cap so a
        # full wrap doesn't flood log_entries in one go
        return lines[-50:]

    def start_debug(self, debug_command=DEBUG_COMMAND):
        """Open a second, independent SSH session dedicated to 'debug ...'
        capture. Kept separate from the main polling session so debug
        output (which streams in asynchronously, not as a normal
        command/response) never gets interleaved with the periodic show
        commands on that session."""
        with self._debug_lock:
            if self._debug_session is not None:
                raise CiscoSSHError("Debugging läuft bereits.")
            cfg = dict(self.config or {})
            secrets = dict(self.secrets or {})

        if not cfg.get("host") or not cfg.get("username"):
            raise CiscoSSHError("Keine Verbindungsdaten vorhanden - erst im Einstellungen-Tab verbinden.")

        session = CiscoSSHSession(
            host=cfg["host"], username=cfg["username"], password=secrets.get("password"),
            port=cfg.get("port", 22), key_filename=cfg.get("key_filename"),
            key_passphrase=secrets.get("key_passphrase"), enable_password=secrets.get("enable_password"),
        )
        session.connect()
        # debug output only reaches a vty/SSH session if monitoring is on;
        # by default it only goes to the console
        session.run_command("terminal monitor")
        stop_event = threading.Event()
        with self._debug_lock:
            self._debug_session = session
            self._debug_buffer = []
            self._debug_started_at = datetime.now().isoformat(timespec="seconds")
            self._debug_stop_event = stop_event
            self._debug_thread = threading.Thread(
                target=self._debug_reader_loop, args=(session, stop_event), daemon=True)
            self._debug_thread.start()
        # Send the debug command only after the reader thread is already
        # running, so nothing gets discarded/lost if real debug output
        # starts arriving immediately (it did in testing: a manual
        # "discard the echo" drain() here raced with genuine output and
        # ate some of it). The command's own echo just becomes the first
        # captured line, which is harmless.
        session.send_nowait(debug_command)

    def _debug_reader_loop(self, session, stop_event):
        while not stop_event.is_set():
            try:
                chunk = session.drain()
            except CiscoSSHError:
                break
            if chunk:
                with self._debug_lock:
                    self._debug_buffer.append(chunk)
            time.sleep(0.5)

    def stop_debug(self):
        with self._debug_lock:
            session = self._debug_session
            thread = self._debug_thread
            stop_event = self._debug_stop_event
            started_at = self._debug_started_at
        if session is None:
            raise CiscoSSHError("Kein aktives Debugging.")

        session.send_nowait("undebug all")
        time.sleep(1.0)  # let trailing debug output + the undebug confirmation land
        with self._debug_lock:
            self._debug_buffer.append(session.drain())
            full_log = "".join(self._debug_buffer)
        stop_event.set()
        thread.join(timeout=3)
        session.close()
        with self._debug_lock:
            self._debug_session = None
            self._debug_buffer = []
            self._debug_started_at = None
            self._debug_thread = None
        return {"log": full_log, "started_at": started_at}

    def debug_status(self):
        with self._debug_lock:
            return {
                "active": self._debug_session is not None,
                "started_at": self._debug_started_at,
                "bytes_captured": sum(len(c) for c in self._debug_buffer),
            }

    def health(self):
        """Boiled-down up/down verdict for external monitoring (e.g.
        Uptime Kuma via a plain HTTP status check): same anomaly rule as
        the GUI's "Verlauf" trigger - a line reporting reg != yes, or a
        line that was present in the previous poll but has disappeared."""
        if self.status != "running":
            return {"healthy": False, "reason": f"Monitor-Status: {self.status}", "tenants": []}
        if not self.history:
            return {"healthy": False, "reason": "Noch keine Daten", "tenants": []}

        latest = self.history[0]
        if not latest.get("ok"):
            return {"healthy": False, "reason": latest.get("error") or "Abfrage fehlgeschlagen", "tenants": []}

        parsed = latest.get("parsed")
        if not isinstance(parsed, list):
            return {"healthy": False, "reason": "Ausgabe konnte nicht geparst werden", "tenants": []}

        problems = []
        for row in parsed:
            if (row.get("reg") or "").lower() != "yes":
                problems.append(f"{self._label_for(row.get('line'))}: reg={row.get('reg')}")

        if len(self.history) > 1 and isinstance(self.history[1].get("parsed"), list):
            current_lines = {row.get("line") for row in parsed}
            for row in self.history[1]["parsed"]:
                if row.get("line") not in current_lines:
                    problems.append(f"{self._label_for(row.get('line'))}: nicht mehr in der Ausgabe")

        tenants = [
            {
                "line": row.get("line"),
                "label": self._label_for(row.get("line")),
                "tenant": row.get("tenant"),
                "reg": row.get("reg"),
            }
            for row in parsed
        ]
        return {
            "healthy": not problems,
            "reason": "OK" if not problems else "; ".join(problems),
            "tenants": tenants,
        }

    def _label_for(self, line):
        return self.labels.get(line, line)

    def set_label(self, line, title):
        with self._lock:
            if title:
                self.labels[line] = title
            else:
                self.labels.pop(line, None)

    def snapshot(self):
        return {
            "status": self.status,
            "error": self.error,
            "config": self.config,
            "history": list(self.history),
            "labels": dict(self.labels),
            "log_entries": list(self.log_entries)[:100],
            "debug": self.debug_status(),
        }

    def persistable_state(self):
        """Full state including secrets, for writing to disk. Never
        exposed via the HTTP API - only app.py's config_store uses this."""
        state = dict(self.config or {})
        state.update(self.secrets)
        state["labels"] = dict(self.labels)
        return state


monitor = Monitor()
