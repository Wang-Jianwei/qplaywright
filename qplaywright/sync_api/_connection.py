"""TCP connection to the QPlaywright agent."""

from __future__ import annotations

import json
import socket
import threading
from typing import Any

from qplaywright.protocol import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    Request,
    Response,
    decode_line,
)


class Connection:
    """Synchronous TCP connection to a QPlaywright agent."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 30.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._id_counter = 0
        self._buf = b""

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def send(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> Any:
        """Send a request and wait for the response. Returns the result or raises."""
        if self._sock is None:
            raise ConnectionError("Not connected to agent")

        with self._lock:
            self._id_counter += 1
            req_id = self._id_counter

            req = Request(method=method, params=params or {}, id=req_id)

            old_timeout = self._sock.gettimeout()
            if timeout is not None:
                self._sock.settimeout(timeout)

            try:
                self._sock.sendall(req.to_bytes())

                while True:
                    while b"\n" in self._buf:
                        line, self._buf = self._buf.split(b"\n", 1)
                        if not line.strip():
                            continue
                        d = decode_line(line)
                        resp = Response.from_dict(d)
                        if resp.id == req_id:
                            if resp.error:
                                raise RuntimeError(f"Agent error: {resp.error}")
                            return resp.result

                    data = self._sock.recv(65536)
                    if not data:
                        raise ConnectionError("Agent closed connection")
                    self._buf += data
            finally:
                if timeout is not None:
                    self._sock.settimeout(old_timeout)

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
