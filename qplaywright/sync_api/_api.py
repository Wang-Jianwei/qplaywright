"""Synchronous QPlaywright API — the main entry point for test scripts.

Usage::

    from qplaywright.sync_api import sync_qplaywright

    with sync_qplaywright() as qp:
        app = qp.connect()
        window = app.window()
        window.locator("role=button", has_text="OK").click()
"""

from __future__ import annotations

import base64
import contextlib
import subprocess
import time
from typing import Any, Generator

from qplaywright.errors import (
    QPlaywrightAgentError,
    QPlaywrightConnectionError,
    QPlaywrightLookupError,
    QPlaywrightProtocolError,
)
from qplaywright.protocol import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    METHOD_HANDSHAKE,
    METHOD_CLICK,
    METHOD_DBLCLICK,
    METHOD_HOVER,
    METHOD_PING,
    METHOD_SET_SESSION_INFO,
    METHOD_LIST_WINDOWS,
    METHOD_WIDGET_TREE,
    METHOD_SCREENSHOT,
    METHOD_WINDOW_TITLE,
    METHOD_WINDOW_SIZE,
    METHOD_WINDOW_RESIZE,
    METHOD_WINDOW_CLOSE,
    PROTOCOL_VERSION,
)
from qplaywright.sync_api._connection import Connection
from qplaywright.sync_api._locator import Locator


class _ConnectSetupError(RuntimeError):
    """Raised when the agent is reachable but connection setup cannot complete."""

    def __init__(self, error: QPlaywrightConnectionError):
        super().__init__(str(error))
        self.error = error


def _raise_connect_setup_error(error: QPlaywrightConnectionError) -> None:
    raise _ConnectSetupError(error)


def _wrap_connect_error(error: QPlaywrightConnectionError, *, host: str, port: int, timeout: float) -> QPlaywrightConnectionError:
    context = dict(getattr(error, "context", {}) or {})
    context.update({"host": host, "port": port, "timeout": timeout})
    return error.__class__(
        f"Could not connect to QPlaywright agent at {host}:{port} (timeout={timeout}s): {error}",
        code=getattr(error, "code", None),
        context=context,
    )


def _perform_handshake(conn: Connection) -> dict[str, Any]:
    try:
        result = conn.send(METHOD_HANDSHAKE)
    except QPlaywrightAgentError as exc:
        _raise_connect_setup_error(
            QPlaywrightProtocolError(
                f"handshake failed: {exc}",
                code="handshake_failed",
                context={"method": METHOD_HANDSHAKE},
            )
        )

    if not isinstance(result, dict):
        _raise_connect_setup_error(
            QPlaywrightProtocolError(
                "handshake failed: agent returned a non-object response",
                code="handshake_invalid_response",
                context={"method": METHOD_HANDSHAKE},
            )
        )

    protocol_version = result.get("protocol_version")
    if protocol_version != PROTOCOL_VERSION:
        _raise_connect_setup_error(
            QPlaywrightProtocolError(
                f"protocol mismatch: client requires protocol_version={PROTOCOL_VERSION}, "
                f"agent reported {protocol_version!r}",
                code="protocol_mismatch",
                context={
                    "method": METHOD_HANDSHAKE,
                    "protocol_version": protocol_version,
                    "expected_protocol_version": PROTOCOL_VERSION,
                },
            )
        )

    return result


def _advertise_agent_name(conn: Connection, agent_name: str) -> None:
    try:
        conn.send(METHOD_SET_SESSION_INFO, {"agentName": agent_name})
    except QPlaywrightAgentError as exc:
        _raise_connect_setup_error(
            QPlaywrightProtocolError(
                f"session setup failed: {exc}",
                code="session_setup_failed",
                context={"method": METHOD_SET_SESSION_INFO, "agent_name": agent_name},
            )
        )


def _launch_exit_error(
    *,
    executable: str,
    exit_code: int | None,
    host: str,
    port: int,
    timeout: float,
) -> QPlaywrightConnectionError:
    return QPlaywrightConnectionError(
        f"Launched executable {executable!r} exited before the QPlaywright agent became reachable at {host}:{port}.",
        code="launch_exited",
        context={
            "executable": executable,
            "exit_code": exit_code,
            "host": host,
            "port": port,
            "timeout": timeout,
        },
    )


def _raise_if_launched_process_exited(
    *,
    executable: str | None,
    process: subprocess.Popen[Any] | None,
    host: str,
    port: int,
    timeout: float,
) -> None:
    if executable is None or process is None:
        return
    exit_code = process.poll()
    if exit_code is None:
        return
    raise _launch_exit_error(
        executable=executable,
        exit_code=exit_code,
        host=host,
        port=port,
        timeout=timeout,
    )


# --------------------------------------------------------------------------- #
#  Window — equivalent to Playwright's Page                                    #
# --------------------------------------------------------------------------- #

class Window:
    """Represents a top-level Qt window. Equivalent to Playwright's ``Page``.

    Provides locator-based widget interaction, screenshots, and window
    management.
    """

    def __init__(self, conn: Connection, wid: int, title: str = "", timeout: float = 30.0):
        self._conn = conn
        self._wid = wid
        self._title_cache = title
        self._timeout = timeout

    @property
    def wid(self) -> int:
        return self._wid

    # -- Locator factory -----------------------------------------------------

    def locator(self, selector: str, *, has_text: str | None = None) -> Locator:
        """Create a locator scoped to this window.

        Args:
            selector: Playwright-style selector (see protocol.py for syntax).
            has_text: Filter by text content (case-insensitive contains).

        Returns:
            A Locator instance.

        Examples::

            window.locator("role=button", has_text="Submit")
            window.locator("#username")
            window.locator(".QLabel")
            window.locator("text=Hello World")
        """
        return Locator(
            self._conn,
            selector,
            has_text=has_text,
            parent_wid=self._wid,
            timeout=self._timeout,
        )

    def get_by_role(self, role: str, *, name: str | None = None) -> Locator:
        """Locate by accessibility role. Equivalent to Playwright's getByRole.

        Args:
            role: Widget role (button, checkbox, textbox, combobox, etc.)
            name: Filter by text/accessible name.

        Examples::

            window.get_by_role("button", name="Submit")
            window.get_by_role("textbox")
        """
        return self.locator(f"role={role}", has_text=name)

    def get_by_text(self, text: str, *, exact: bool = True) -> Locator:
        """Locate by visible text content.

        Args:
            text: The text to match.
            exact: If True, match exactly. If False, match as substring.
        """
        if exact:
            return self.locator(f"text={text}")
        return self.locator(f"has-text={text}")

    def get_by_label(self, text: str) -> Locator:
        """Locate an input by its associated label text."""
        return self.locator(f"has-text={text}")

    def get_by_placeholder(self, text: str) -> Locator:
        """Locate an input by placeholder text."""
        # Uses Qt property access
        return self.locator(f"text={text}")

    def get_by_test_id(self, test_id: str) -> Locator:
        """Locate by objectName (Qt equivalent of data-testid)."""
        return self.locator(f"#{test_id}")

    # -- Window properties ---------------------------------------------------

    def title(self) -> str:
        """Get the window title."""
        return self._conn.send(METHOD_WINDOW_TITLE, {"wid": self._wid})

    def size(self) -> dict[str, int]:
        """Get the window size as {width, height}."""
        return self._conn.send(METHOD_WINDOW_SIZE, {"wid": self._wid})

    def resize(self, width: int, height: int) -> None:
        """Resize the window."""
        self._conn.send(METHOD_WINDOW_RESIZE, {"wid": self._wid, "width": width, "height": height})

    def close(self) -> None:
        """Close the window."""
        self._conn.send(METHOD_WINDOW_CLOSE, {"wid": self._wid})

    def click_at(self, x: int, y: int, *, count: int = 1) -> None:
        """Click or double-click a window-relative coordinate."""
        if count not in (1, 2):
            raise ValueError("count must be 1 or 2")

        method = METHOD_DBLCLICK if count == 2 else METHOD_CLICK
        self._conn.send(method, {"window_wid": self._wid, "x": int(x), "y": int(y)})

    def hover_at(self, x: int, y: int) -> None:
        """Hover a window-relative coordinate."""
        self._conn.send(METHOD_HOVER, {"window_wid": self._wid, "x": int(x), "y": int(y)})

    # -- Screenshots ---------------------------------------------------------

    def screenshot(
        self,
        *,
        path: str | None = None,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | dict:
        """Take a screenshot of the entire window or a clipped region.

        Args:
            path: If provided, save the screenshot to this file path.
            x: Optional left coordinate relative to the window.
            y: Optional top coordinate relative to the window.
            width: Optional clip width.
            height: Optional clip height.

        Returns:
            If path is None, returns dict with base64 data.
            If path is provided, returns dict with path and dimensions.
        """
        params: dict[str, Any] = {"wid": self._wid}
        if path:
            params["path"] = path
        if x is not None:
            params["x"] = x
        if y is not None:
            params["y"] = y
        if width is not None:
            params["width"] = width
        if height is not None:
            params["height"] = height
        return self._conn.send(METHOD_SCREENSHOT, params)

    # -- Widget tree ---------------------------------------------------------

    def widget_tree(self, *, max_depth: int = 10, topmost_only: bool = False) -> list[dict]:
        """Get the widget tree, optionally filtering to frontmost visible widgets."""
        return self._conn.send(METHOD_WIDGET_TREE, {"max_depth": max_depth, "topmost_only": topmost_only})

    # -- Waiting -------------------------------------------------------------

    def wait_for_timeout(self, timeout: float) -> None:
        """Wait for the specified time in seconds."""
        time.sleep(timeout)

    def __repr__(self) -> str:
        return f"Window(wid={self._wid}, title={self._title_cache!r})"


# --------------------------------------------------------------------------- #
#  Application — equivalent to Playwright's Browser                            #
# --------------------------------------------------------------------------- #

class Application:
    """Represents a connected Qt application. Equivalent to Playwright's ``Browser``.

    Provides access to windows and global operations.
    """

    def __init__(self, conn: Connection, timeout: float = 30.0):
        self._conn = conn
        self._timeout = timeout

    def windows(self) -> list[Window]:
        """List all visible top-level windows."""
        result = self._conn.send(METHOD_LIST_WINDOWS)
        return [
            Window(self._conn, w["wid"], title=w.get("title", ""), timeout=self._timeout)
            for w in result
        ]

    def window(self, *, title: str | None = None, index: int = 0) -> Window:
        """Get a specific window by title or index.

        Args:
            title: Match window by title (substring match).
            index: If title is None, get the nth visible window (default: first).

        Returns:
            A Window instance.
        """
        wins = self.windows()
        if not wins:
            raise QPlaywrightLookupError(
                "No visible windows found in the application",
                code="window_not_found",
                context={"title": title, "index": index},
            )

        if title is not None:
            for w in wins:
                if title.lower() in w.title().lower():
                    return w
            raise QPlaywrightLookupError(
                f"No window found with title containing: {title!r}",
                code="window_not_found",
                context={"title": title, "index": index, "window_count": len(wins)},
            )

        if index >= len(wins):
            raise IndexError(f"Window index {index} out of range (found {len(wins)} windows)")

        return wins[index]

    def main_window(self) -> Window:
        """Get the main (first visible) window."""
        return self.window(index=0)

    def close(self) -> None:
        """Close the connection to the application."""
        self._conn.close()

    def __repr__(self) -> str:
        return f"Application(connected={self._conn.connected})"


# --------------------------------------------------------------------------- #
#  QPlaywright — top-level context manager                                     #
# --------------------------------------------------------------------------- #

class QPlaywright:
    """Top-level QPlaywright context. Equivalent to Playwright's ``Playwright``.

    Usage::

        with sync_qplaywright() as qp:
            app = qp.connect()
    """

    def connect(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        timeout: float = 30.0,
        agent_name: str | None = None,
    ) -> Application:
        """Connect to a running Qt application with QPlaywright agent embedded.

        Args:
            host: Agent host address.
            port: Agent port.
            timeout: Default timeout for operations (seconds).
            agent_name: Optional label advertised to the Qt-side overlay when
                visual feedback is enabled.

        Returns:
            An Application instance.
        """
        return self._connect_with_retry(host=host, port=port, timeout=timeout, agent_name=agent_name)

    def _connect_with_retry(
        self,
        *,
        host: str,
        port: int,
        timeout: float,
        agent_name: str | None,
        executable: str | None = None,
        process: subprocess.Popen[Any] | None = None,
    ) -> Application:
        conn = Connection(host=host, port=port, timeout=timeout)

        # Retry connection with exponential backoff
        deadline = time.monotonic() + timeout
        last_error = None
        backoff = 0.1
        connect_probe_timeout = 1.0
        max_backoff = 2.0
        while time.monotonic() < deadline:
            _raise_if_launched_process_exited(
                executable=executable,
                process=process,
                host=host,
                port=port,
                timeout=timeout,
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                if process is None:
                    conn.connect()
                else:
                    conn.connect(timeout=min(connect_probe_timeout, remaining))
                _perform_handshake(conn)
                if agent_name:
                    _advertise_agent_name(conn, agent_name)
                return Application(conn, timeout=timeout)
            except _ConnectSetupError as e:
                conn.close()
                raise _wrap_connect_error(e.error, host=host, port=port, timeout=timeout) from e.error
            except (ConnectionRefusedError, QPlaywrightConnectionError, OSError) as e:
                last_error = e
                conn.close()
                _raise_if_launched_process_exited(
                    executable=executable,
                    process=process,
                    host=host,
                    port=port,
                    timeout=timeout,
                )
                if process is None:
                    time.sleep(backoff)
                else:
                    sleep_for = min(backoff, max(0.0, deadline - time.monotonic()))
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                backoff = min(backoff * 2, max_backoff)

        raise QPlaywrightConnectionError(
            f"Could not connect to QPlaywright agent at {host}:{port} "
            f"(timeout={timeout}s): {last_error}",
            code="connect_timeout",
            context={
                "host": host,
                "port": port,
                "timeout": timeout,
                "last_error": None if last_error is None else repr(last_error),
            },
        )

    def launch(
        self,
        executable: str,
        *args: str,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = 30.0,
        agent_name: str | None = None,
    ) -> Application:
        """Launch a Qt application and connect to its agent.

        The application must have QPlaywright agent embedded via ``start_agent()``.

        Args:
            executable: Path to the Qt application executable.
            *args: Command-line arguments.
            host: Agent host address.
            port: Agent port.
            timeout: Connection timeout in seconds.
            agent_name: Optional label advertised to the Qt-side overlay when
                visual feedback is enabled.

        Returns:
            An Application instance.
        """
        self._process = subprocess.Popen([executable, *args])
        return self._connect_with_retry(
            host=host,
            port=port,
            timeout=timeout,
            agent_name=agent_name,
            executable=executable,
            process=self._process,
        )

    def close(self) -> None:
        """Clean up resources."""
        proc = getattr(self, "_process", None)
        if proc and proc.poll() is None:
            proc.terminate()


@contextlib.contextmanager
def sync_qplaywright() -> Generator[QPlaywright, None, None]:
    """Context manager that creates a QPlaywright instance.

    Usage::

        from qplaywright.sync_api import sync_qplaywright

        with sync_qplaywright() as qp:
            app = qp.connect(port=19876)
            window = app.window()
            window.locator("role=button").click()
    """
    qp = QPlaywright()
    try:
        yield qp
    finally:
        qp.close()
