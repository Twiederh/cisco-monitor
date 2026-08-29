"""Persistent interactive SSH shell session to a Cisco IOS device.

Cisco IOS often needs an interactive shell (not one-shot exec_command)
because settings like "terminal length 0" only apply within a shell
session, and privileged commands may require an "enable" step.
"""
import re
import socket
import time

import paramiko

PROMPT_RE = re.compile(r"[\r\n]?\S+[>#]\s*$")


class CiscoSSHError(RuntimeError):
    pass


class CiscoSSHSession:
    def __init__(self, host, username, password=None, port=22,
                 key_filename=None, key_passphrase=None,
                 enable_password=None, timeout=10):
        self.host = host
        self.port = port
        self.username = username
        self.password = password or None
        self.key_filename = key_filename or None
        self.key_passphrase = key_passphrase or None
        self.enable_password = enable_password
        self.timeout = timeout
        self._client = None
        self._shell = None

    def connect(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # Explicit key file takes priority; otherwise fall back to a
        # password, or - if neither is given - the user's default keys /
        # a running ssh-agent (look_for_keys/allow_agent=True).
        use_defaults = not self.key_filename and not self.password
        try:
            client.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                key_filename=self.key_filename,
                passphrase=self.key_passphrase,
                timeout=self.timeout,
                look_for_keys=use_defaults,
                allow_agent=use_defaults,
            )
        except (paramiko.AuthenticationException,
                paramiko.SSHException,
                socket.error) as exc:
            raise CiscoSSHError(f"SSH-Verbindung fehlgeschlagen: {exc}") from exc

        shell = client.invoke_shell()
        shell.settimeout(self.timeout)
        self._client = client
        self._shell = shell

        self._read_until_prompt(initial=True)

        if self.enable_password:
            self._enable()

        self._send_raw("terminal length 0")
        self._send_raw("terminal width 511")

    def _enable(self):
        buf = self._send_raw("enable", wait_for="assword:")
        if "assword" in buf:
            self._shell.send(self.enable_password + "\n")
            self._read_until_prompt()

    def _read_until_prompt(self, initial=False, extra_wait=None):
        buf = ""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                if self._shell.recv_ready():
                    chunk = self._shell.recv(65535).decode(errors="replace")
                    buf += chunk
                    if extra_wait and extra_wait in buf:
                        return buf
                    if PROMPT_RE.search(buf.rstrip()):
                        # give the device a brief moment in case more is coming
                        time.sleep(0.05)
                        if not self._shell.recv_ready():
                            return buf
                else:
                    time.sleep(0.05)
            except socket.timeout:
                break
        return buf

    def _send_raw(self, cmd, wait_for=None):
        self._shell.send(cmd + "\n")
        return self._read_until_prompt(extra_wait=wait_for)

    def run_command(self, command):
        if not self.is_connected():
            raise CiscoSSHError("Keine aktive SSH-Sitzung.")
        raw = self._send_raw(command)
        lines = raw.replace("\r", "").split("\n")
        # drop the echoed command (first line) and the trailing prompt line
        if lines and command.strip() in lines[0]:
            lines = lines[1:]
        if lines and PROMPT_RE.match("\n" + lines[-1]):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    def send_nowait(self, cmd):
        """Send a command without waiting for the prompt to reappear.

        Used for 'debug ...' commands: IOS keeps streaming unsolicited
        output to the session as events happen, well after any immediate
        response, so there's no fixed point to wait for here - draining
        happens separately via drain()."""
        if not self.is_connected():
            raise CiscoSSHError("Keine aktive SSH-Sitzung.")
        self._shell.send(cmd + "\n")

    def drain(self):
        """Non-blocking read of whatever's currently buffered on the
        channel (used to collect asynchronous 'debug' output)."""
        chunks = []
        while self._shell.recv_ready():
            chunks.append(self._shell.recv(65535).decode(errors="replace"))
        return "".join(chunks)

    def is_connected(self):
        return (
            self._client is not None
            and self._shell is not None
            and not self._shell.closed
            and self._client.get_transport() is not None
            and self._client.get_transport().is_active()
        )

    def close(self):
        try:
            if self._shell:
                self._shell.close()
        finally:
            if self._client:
                self._client.close()
        self._shell = None
        self._client = None
