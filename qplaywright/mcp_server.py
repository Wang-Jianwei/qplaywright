"""MCP server adapter for qplaywright.

This module exposes the existing synchronous qplaywright client as an MCP
server. It does not replace the Qt-side agent protocol. Instead, it adds a
northbound MCP tool layer so MCP hosts can connect to a running Qt app,
inspect windows, and interact with widgets via the existing selector model.
"""

import builtins
import argparse
import atexit
import inspect as pyinspect
import contextlib
import json
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qplaywright.protocol import DEFAULT_HOST, DEFAULT_PORT, METHOD_FIND, METHOD_LIST_WINDOWS, METHOD_PING, METHOD_WIDGET_TREE
from qplaywright.sync_api import QPlaywright
from qplaywright.sync_api._locator import Locator

LOGGER = logging.getLogger(__name__)

_SNAPSHOT_REF_PATTERN = re.compile(r"^e\d+$")

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
    FastMCP = None  # type: ignore[assignment]
    _MCP_IMPORT_ERROR: ImportError | None = exc
else:
    _MCP_IMPORT_ERROR = None


@dataclass
class ManagedConnection:
    """A live qplaywright connection tracked by the MCP server."""

    name: str
    qplaywright: Any
    app: Any
    host: str
    port: int
    timeout: float
    launched_executable: str | None = None
    active_window_wid: int | None = None
    snapshot_refs: dict[str, int] = field(default_factory=dict)
    snapshot_wids: dict[int, str] = field(default_factory=dict)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.app.close()
        with contextlib.suppress(Exception):
            self.qplaywright.close()

    def clear_snapshot_refs(self) -> None:
        self.snapshot_refs.clear()
        self.snapshot_wids.clear()


@dataclass
class ServerState:
    """In-process state for live qplaywright MCP sessions."""

    connection: ManagedConnection | None = None

    def close_all(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None


_SERVER_STATE = ServerState()
atexit.register(_SERVER_STATE.close_all)


def _list_windows_raw(connection: ManagedConnection) -> list[dict[str, Any]]:
    client = getattr(connection.app, "_conn", None)
    if client is not None:
        return client.send(METHOD_LIST_WINDOWS)

    windows = []
    for index, window in enumerate(connection.app.windows()):
        windows.append(
            {
                "wid": window.wid,
                "title": window.title(),
                "class": "",
                "width": None,
                "height": None,
                "index": index,
            }
        )
    return windows


def _widget_tree_raw(
    connection: ManagedConnection,
    *,
    max_depth: int,
    window_wid: int | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"max_depth": max_depth}
    if window_wid is not None:
        params["wid"] = window_wid
    return connection.app._conn.send(METHOD_WIDGET_TREE, params)


def _window_summary(connection: ManagedConnection) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for index, window in enumerate(_list_windows_raw(connection)):
        if connection.active_window_wid is None:
            is_active = index == 0
        else:
            is_active = window["wid"] == connection.active_window_wid
        summaries.append(
            {
                "index": index,
                "wid": window["wid"],
                "title": window.get("title", ""),
                "class": window.get("class", ""),
                "width": window.get("width"),
                "height": window.get("height"),
                "is_active": is_active,
                "is_modal": False,
            }
        )
    return summaries


def _active_window_summary(
    connection: ManagedConnection,
    *,
    windows: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if windows is None:
        windows = _window_summary(connection)
    if not windows:
        return None

    active_window = None
    if connection.active_window_wid is not None:
        active_window = next(
            (window for window in windows if window["wid"] == connection.active_window_wid),
            None,
        )
    if active_window is None:
        active_window = windows[0]
    return {**active_window, "is_active": True, "is_modal": active_window.get("is_modal", False)}


def _session_summary(connection: ManagedConnection) -> dict[str, Any]:
    return {
        "connected": True,
        "host": connection.host,
        "port": connection.port,
        "launched_executable": connection.launched_executable,
    }


def _select_active_window(connection: ManagedConnection, window_wid: int | None) -> None:
    connection.active_window_wid = window_wid
    connection.clear_snapshot_refs()


def _initialize_active_window(connection: ManagedConnection) -> list[dict[str, Any]]:
    windows = _window_summary(connection)
    if windows:
        _select_active_window(connection, windows[0]["wid"])
    else:
        _select_active_window(connection, None)
    return windows


def _ping_connection(connection: ManagedConnection) -> None:
    client = getattr(connection.app, "_conn", None)
    if client is None:
        return
    client.send(METHOD_PING, timeout=min(connection.timeout, 5.0))


def _stale_connection_message(connection: ManagedConnection, exc: Exception) -> str:
    return (
        f"Session to {connection.host}:{connection.port} is no longer alive: {exc}. "
        "The remote qplaywright agent disconnected or restarted. Call session attach again to establish a fresh session."
    )


def _get_connection(state: ServerState) -> ManagedConnection:
    connection = state.connection
    if connection is None:
        raise ValueError("No active session. Call session with action='attach' or action='launch' first")

    try:
        _ping_connection(connection)
    except Exception as exc:
        connection.close()
        state.connection = None
        raise ConnectionError(_stale_connection_message(connection, exc)) from exc

    return connection


def connect_connection(
    state: ServerState,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 30.0,
) -> ManagedConnection:
    if state.connection is not None:
        state.connection.close()

    qplaywright = QPlaywright()
    app = qplaywright.connect(host=host, port=port, timeout=timeout)
    connection = ManagedConnection(
        name="default",
        qplaywright=qplaywright,
        app=app,
        host=host,
        port=port,
        timeout=timeout,
    )
    state.connection = connection
    _initialize_active_window(connection)
    return connection


def launch_connection(
    state: ServerState,
    *,
    executable: str,
    args: Sequence[str] | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 30.0,
) -> ManagedConnection:
    if state.connection is not None:
        state.connection.close()

    qplaywright = QPlaywright()
    app = qplaywright.launch(executable, *(args or ()), host=host, port=port, timeout=timeout)
    connection = ManagedConnection(
        name="default",
        qplaywright=qplaywright,
        app=app,
        host=host,
        port=port,
        timeout=timeout,
        launched_executable=executable,
    )
    state.connection = connection
    _initialize_active_window(connection)
    return connection


def disconnect_connection(state: ServerState) -> dict[str, Any]:
    connection = _get_connection(state)
    connection.close()
    state.connection = None
    return {
        "closed": True,
        "launched_executable": connection.launched_executable,
    }


def _resolve_window(
    connection: ManagedConnection,
    *,
    window_wid: int | None = None,
    window_title: str | None = None,
    window_index: int | None = None,
) -> Any:
    windows = connection.app.windows()
    if not windows:
        raise ValueError(f"No visible windows found for connection {connection.name!r}")

    if window_wid is not None:
        for window in windows:
            if window.wid == window_wid:
                return window
        raise ValueError(f"Window wid={window_wid} was not found for connection {connection.name!r}")

    if window_title:
        title_lower = window_title.lower()
        for window in windows:
            if title_lower in window.title().lower():
                return window
        raise ValueError(
            f"No window title containing {window_title!r} was found for connection {connection.name!r}"
        )

    if window_index is not None:
        if window_index < 0 or window_index >= len(windows):
            raise IndexError(
                f"Window index {window_index} is out of range for connection {connection.name!r}"
            )
        return windows[window_index]

    if connection.active_window_wid is not None:
        for window in windows:
            if window.wid == connection.active_window_wid:
                return window

    return windows[0]


def _resolve_locator(
    connection: ManagedConnection,
    *,
    target: str,
) -> Any:
    if not target.strip():
        raise ValueError("target must not be empty")

    if _SNAPSHOT_REF_PATTERN.match(target):
        ref_wid = connection.snapshot_refs.get(target)
        if ref_wid is None:
            raise ValueError(_target_not_found_message(connection, target))
        return Locator(connection.app._conn, "", widget_wid=ref_wid, timeout=connection.timeout)

    window = _resolve_window(connection)
    return window.locator(target)


def _inspect_locator(
    locator: Any,
    *,
    property_name: str | None = None,
    include_methods: bool = False,
) -> dict[str, Any]:
    count = locator.count()
    result: dict[str, Any] = {
        "exists": count > 0,
        "count": count,
    }
    if count == 0:
        return result

    first = locator.first()
    result.update(
        {
            "text": first.text_content(),
            "value": first.input_value(),
            "all_text_contents": locator.all_text_contents(),
            "is_visible": first.is_visible(),
            "is_enabled": first.is_enabled(),
            "is_checked": first.is_checked(),
            "bounding_box": first.bounding_box(),
        }
    )

    if property_name is not None:
        result["property_name"] = property_name
        result["property_value"] = first.get_attribute(property_name)

    if include_methods:
        result["methods"] = first.methods()

    return result


def _invoke_locator_method(
    locator: Any,
    *,
    method_name: str,
    args: dict[str, Any] | None = None,
) -> Any:
    count = locator.count()
    if count == 0:
        raise ValueError(
            "No widget found for invoke. Use snapshot or inspect first, then target with selectors like "
            "#objectName, role=button, text=Submit, has-text=partial, or .QLabel."
        )

    result = locator.first().invoke(method_name, args or {})
    if isinstance(result, dict) and "ok" in result and result.get("ok") is False:
        error_code = result.get("errorCode")
        error_message = str(result.get("errorMessage") or "Unknown invoke failure")
        raise ValueError(f"Invoke failed for method {method_name!r} (errorCode={error_code}): {error_message}")
    return result


def _target_not_found_message(connection: ManagedConnection, target: str | None, *, element: str | None = None) -> str:
    examples = "#objectName, role=button, text=Submit, has-text=partial, .QLabel"
    candidate = (target or element or "").strip()
    if candidate and _SNAPSHOT_REF_PATTERN.match(candidate) and candidate not in connection.snapshot_refs:
        return (
            f"No widget found for target {candidate!r}. Snapshot ref {candidate!r} is not available in the current session. "
            f"Run snapshot to refresh refs, or target a widget with selectors like {examples}."
        )
    if candidate:
        return (
            f"No widget found for target {candidate!r}. Run snapshot or inspect to discover the UI, "
            f"then target a widget with selectors like {examples}."
        )
    return (
        "No widget target was resolved. Run snapshot or inspect first, then target a widget with "
        f"selectors like {examples}."
    )


def _selector_help_text() -> str:
    return (
        "Selectors follow the qplaywright selector syntax.\n\n"
        "Common forms:\n"
        "- role=button\n"
        "- text=Submit\n"
        "- has-text=partial\n"
        "- #objectName\n"
        "- name=objectName\n"
        "- .QLabel\n\n"
        "Typical workflow:\n"
        "1. session attach or session launch\n"
        "2. window list and window select when multiple windows are visible\n"
        "3. snapshot or inspect\n"
        "4. click, input, set_checked, press_key, choose, screenshot, or invoke\n"
        "5. session close when finished"
    )


def _format_widget_snapshot(nodes: list[dict[str, Any]], *, depth: int = 10, level: int = 0) -> str:
    if level > depth:
        return ""

    lines: list[str] = []
    for node in nodes:
        selector = ""
        object_name = node.get("objectName") or ""
        if object_name:
            selector = f" target=#{object_name}"
        elif node.get("class"):
            selector = f" target=.{node['class']}"

        text = node.get("text") or ""
        text_part = f' "{text}"' if text else ""
        line = f"{'  ' * level}- {node.get('class', '?')}{text_part}{selector}"
        lines.append(line)

        children = node.get("children") or []
        child_text = _format_widget_snapshot(children, depth=depth, level=level + 1)
        if child_text:
            lines.append(child_text)

    return "\n".join(lines)


def _snapshot_ref_for_widget(connection: ManagedConnection, wid: int | None) -> str | None:
    if wid is None:
        return None
    ref = connection.snapshot_wids.get(wid)
    if ref is not None:
        return ref
    ref = f"e{len(connection.snapshot_refs) + 1}"
    connection.snapshot_refs[ref] = wid
    connection.snapshot_wids[wid] = ref
    return ref


def _snapshot_target_hint(node: dict[str, Any]) -> str:
    object_name = node.get("objectName") or ""
    if object_name:
        return f"#{object_name}"
    widget_class = node.get("class") or ""
    if widget_class:
        return f".{widget_class}"
    return ""


def _snapshot_entry(node: dict[str, Any], ref: str | None) -> dict[str, Any]:
    return {
        "ref": ref,
        "wid": node.get("wid"),
        "target": _snapshot_target_hint(node) or None,
        "class": node.get("class", ""),
        "text": node.get("text", ""),
    }


def _render_snapshot_tree(
    connection: ManagedConnection,
    nodes: list[dict[str, Any]],
    *,
    depth: int = 10,
    level: int = 0,
    seen_wids: set[int] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    if level > depth:
        return [], []

    if seen_wids is None:
        seen_wids = set()

    lines: list[str] = []
    refs: list[dict[str, Any]] = []

    for node in nodes:
        wid = node.get("wid")
        if wid is not None:
            if wid in seen_wids:
                continue
            seen_wids.add(wid)

        ref = _snapshot_ref_for_widget(connection, wid)
        ref_part = f" [ref={ref}]" if ref else ""
        target_hint = _snapshot_target_hint(node)
        target_part = f" target={target_hint}" if target_hint else ""
        text = node.get("text") or ""
        text_part = f' "{text}"' if text else ""
        active_part = " [active]" if wid == connection.active_window_wid else ""
        lines.append(f"{'  ' * level}- {node.get('class', '?')}{text_part}{active_part}{ref_part}{target_part}")
        refs.append(_snapshot_entry(node, ref))

        child_lines, child_refs = _render_snapshot_tree(
            connection,
            node.get("children") or [],
            depth=depth,
            level=level + 1,
            seen_wids=seen_wids,
        )
        lines.extend(child_lines)
        refs.extend(child_refs)

    return lines, refs


def _snapshot_payload(
    connection: ManagedConnection,
    nodes: list[dict[str, Any]],
    *,
    depth: int = 10,
) -> dict[str, Any]:
    lines, refs = _render_snapshot_tree(connection, nodes, depth=depth)
    return {
        "snapshot": "\n".join(lines),
        "refs": refs,
    }


def _write_text_file(path: str, content: str) -> str:
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return str(target_path)


def _target_params(connection: ManagedConnection, target: str) -> dict[str, Any]:
    if _SNAPSHOT_REF_PATTERN.match(target):
        ref_wid = connection.snapshot_refs.get(target)
        if ref_wid is None:
            raise ValueError(_target_not_found_message(connection, target))
        return {"wid": ref_wid}
    return {"selector": target}


def _snapshot_result(
    managed_connection: ManagedConnection,
    *,
    target: str | None = None,
    depth: int = 10,
) -> dict[str, Any]:
    if target is None:
        return _snapshot_payload(
            managed_connection,
            _widget_tree_raw(
                managed_connection,
                max_depth=depth,
                window_wid=managed_connection.active_window_wid,
            ),
            depth=depth,
        )

    node = managed_connection.app._conn.send(
        METHOD_FIND,
        _target_params(managed_connection, target),
        timeout=managed_connection.timeout,
    )
    if node is None:
        raise ValueError(_target_not_found_message(managed_connection, target))
    return _snapshot_payload(managed_connection, [node], depth=depth)


def _action_result_with_snapshot(
    managed_connection: ManagedConnection,
    *,
    target: str | None = None,
    depth: int = 10,
    **payload: Any,
) -> dict[str, Any]:
    result = dict(payload)
    result.update(_snapshot_result(managed_connection, target=target, depth=depth))
    return result


def _observe_action_window_state(managed_connection: ManagedConnection) -> dict[str, Any]:
    previous_active_window_wid = managed_connection.active_window_wid
    windows = _window_summary(managed_connection)

    active_window = _active_window_summary(managed_connection, windows=windows)

    next_active_window_wid = active_window["wid"] if active_window is not None else None
    if next_active_window_wid != managed_connection.active_window_wid:
        _select_active_window(managed_connection, next_active_window_wid)

    return {
        "window_changed": next_active_window_wid != previous_active_window_wid,
        "active_window": active_window,
    }


def _finalize_action_result(
    managed_connection: ManagedConnection,
    *,
    include_snapshot: bool = False,
    snapshot_target: str | None = None,
    **payload: Any,
) -> dict[str, Any]:
    result = dict(payload)
    result.update(_observe_action_window_state(managed_connection))
    if not include_snapshot:
        return result
    effective_target = None if result["window_changed"] else snapshot_target
    result.update(_action_result_with_snapshot(managed_connection, target=effective_target))
    return result


if FastMCP is not None:
    mcp = FastMCP(
        "qplaywright",
        instructions=(
            "Automate Qt QWidget applications through qplaywright. "
            "Use session, window, snapshot, and inspect to discover the UI before "
            "before performing destructive UI actions."
        ),
        json_response=True,
    )


    @mcp.resource("qplaywright://help/selectors")
    def selector_help() -> str:
        """Selector syntax and recommended qplaywright MCP workflow."""

        return _selector_help_text()


    @mcp.tool()
    def session(
        action: str,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = 30.0,
        executable: str | None = None,
        args: list[str] | None = None,
    ) -> dict[str, Any]:
        """Manage one MCP-side qplaywright session."""

        if action == "attach":
            connection_state = connect_connection(_SERVER_STATE, host=host, port=port, timeout=timeout)
            windows = _window_summary(connection_state)
            return {
                "ok": True,
                "action": action,
                "session": _session_summary(connection_state),
                "active_window": _active_window_summary(connection_state, windows=windows),
            }

        if action == "launch":
            if not executable:
                raise ValueError("executable is required when action='launch'")
            connection_state = launch_connection(
                _SERVER_STATE,
                executable=executable,
                args=args,
                host=host,
                port=port,
                timeout=timeout,
            )
            windows = _window_summary(connection_state)
            return {
                "ok": True,
                "action": action,
                "session": _session_summary(connection_state),
                "active_window": _active_window_summary(connection_state, windows=windows),
            }

        if action == "close":
            result = disconnect_connection(_SERVER_STATE)
            return {"ok": True, "action": action, "closed": result["closed"]}

        if action == "status":
            connection_state = _get_connection(_SERVER_STATE)
            windows = _window_summary(connection_state)
            return {
                "ok": True,
                "action": action,
                "session": _session_summary(connection_state),
                "active_window": _active_window_summary(connection_state, windows=windows),
            }

        raise ValueError(f"Unsupported session action: {action!r}")


    @mcp.tool()
    def window(
        action: str,
        index: int | None = None,
        wid: int | None = None,
        title: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        """Manage one top-level window within the current session."""

        connection_state = _get_connection(_SERVER_STATE)

        if action == "list":
            return {
                "ok": True,
                "action": action,
                "windows": _window_summary(connection_state),
            }

        if action == "select":
            selected_window = _resolve_window(
                connection_state,
                window_wid=wid,
                window_title=title,
                window_index=index,
            )
            refs_cleared = connection_state.active_window_wid != selected_window.wid
            _select_active_window(connection_state, selected_window.wid)
            return {
                "ok": True,
                "action": action,
                "active_window": _active_window_summary(connection_state),
                "refs_cleared": refs_cleared,
            }

        if action == "resize":
            if width is None or height is None:
                raise ValueError("width and height are required when action='resize'")
            target_window = _resolve_window(
                connection_state,
                window_wid=wid,
                window_title=title,
                window_index=index,
            )
            target_window.resize(width, height)
            return {
                "ok": True,
                "action": action,
                "active_window": _active_window_summary(connection_state),
            }

        if action == "close":
            target_window = _resolve_window(
                connection_state,
                window_wid=wid,
                window_title=title,
                window_index=index,
            )
            target_window.close()
            remaining_windows = _window_summary(connection_state)
            if not any(window["wid"] == connection_state.active_window_wid for window in remaining_windows):
                _select_active_window(connection_state, remaining_windows[0]["wid"] if remaining_windows else None)
            return {
                "ok": True,
                "action": action,
                "active_window": _active_window_summary(connection_state, windows=remaining_windows),
            }

        raise ValueError(f"Unsupported window action: {action!r}")


    @mcp.tool()
    def snapshot(
        target: str | None = None,
        depth: int = 10,
        save_to: str | None = None,
    ) -> dict[str, Any]:
        """Return a text snapshot of the current active window or one target."""

        connection_state = _get_connection(_SERVER_STATE)
        active_window = _active_window_summary(connection_state)
        payload = _snapshot_result(connection_state, target=target, depth=depth)
        result = {
            "ok": True,
            "session": _session_summary(connection_state),
            "window": active_window,
            "target": target,
            **payload,
        }
        if save_to is not None:
            result["save_to"] = _write_text_file(save_to, payload["snapshot"])
        return result


    @mcp.tool()
    def inspect(
        target: str | None = None,
        property: str | None = None,
        include_methods: bool = False,
        depth: int = 10,
    ) -> dict[str, Any]:
        """Inspect one target or return the current active window tree in debug mode."""

        connection_state = _get_connection(_SERVER_STATE)
        if target is None:
            return {
                "ok": True,
                "target": None,
                "depth": depth,
                "tree": _widget_tree_raw(
                    connection_state,
                    max_depth=depth,
                    window_wid=connection_state.active_window_wid,
                ),
            }

        locator = _resolve_locator(connection_state, target=target)
        result = _inspect_locator(locator, property_name=property, include_methods=include_methods)
        return {
            "ok": True,
            "target": target,
            **result,
        }


    @mcp.tool()
    def click(
        target: str,
        count: int = 1,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Click or double-click the first widget matched by a target."""

        if count not in (1, 2):
            raise ValueError("count must be 1 or 2")

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_locator(connection_state, target=target)
        if count == 2:
            locator.dblclick()
        else:
            locator.click()
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            ok=True,
            count=count,
            target=target,
        )


    @mcp.tool()
    def input(
        target: str,
        text: str,
        mode: str = "replace",
        delay: int = 0,
        submit: bool = False,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Input text into the first matched input-like widget."""

        if mode not in ("replace", "append"):
            raise ValueError("mode must be 'replace' or 'append'")
        if delay < 0:
            raise ValueError("delay must be >= 0")

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_locator(connection_state, target=target)
        if mode == "replace":
            if delay == 0:
                locator.fill(text)
            else:
                locator.clear()
                locator.type(text, delay=delay)
        else:
            locator.type(text, delay=delay)

        if submit:
            locator.press("Enter")

        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            ok=True,
            target=target,
            text=text,
            mode=mode,
            delay=delay,
            submitted=submit,
        )


    @mcp.tool()
    def invoke(
        target: str,
        method: str,
        args: dict[str, Any] | None = None,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Invoke one exposed custom widget method by exact name."""

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_locator(connection_state, target=target)
        result = _invoke_locator_method(locator, method_name=method, args=args)
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            ok=True,
            target=target,
            method=method,
            args=dict(args or {}),
            result=result,
        )
    @mcp.tool()
    def press_key(
        target: str,
        key: str,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Send a single key press to the first matched widget."""

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_locator(connection_state, target=target)
        locator.press(key)
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            ok=True,
            target=target,
            key=key,
        )


    @mcp.tool()
    def set_checked(
        target: str,
        checked: bool,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Check or uncheck the first matched checkable widget."""

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_locator(connection_state, target=target)
        if checked:
            locator.check()
        else:
            locator.uncheck()
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            ok=True,
            target=target,
            checked=checked,
        )


    @mcp.tool()
    def choose(
        target: str,
        value: str | None = None,
        index: int | None = None,
        label: str | None = None,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Select a combobox option by value, index, or label."""

        selector_count = sum(candidate is not None for candidate in (value, index, label))
        if selector_count != 1:
            raise ValueError("Exactly one of value, index, or label must be provided")

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_locator(connection_state, target=target)
        locator.select_option(value=value, index=index, label=label)
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            ok=True,
            target=target,
            value=value,
            index=index,
            label=label,
        )


    @mcp.tool()
    def wait(
        target: str,
        state: str = "visible",
        timeout: float | None = None,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Wait until a widget reaches a supported state."""

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_locator(connection_state, target=target)
        locator.wait_for(state=state, timeout=timeout)
        payload = {
            "ok": True,
            "target": target,
            "state": state,
            "timeout": timeout,
        }
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            **payload,
        )


    @mcp.tool()
    def screenshot(
        target: str | None = None,
        path: str | None = None,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        """Capture a screenshot of a window or a matched widget, optionally clipped to a rectangle."""

        live_connection = _get_connection(_SERVER_STATE)
        clip_kwargs = _screenshot_clip_kwargs(x=x, y=y, width=width, height=height)
        clip_x = clip_kwargs.get("x")
        clip_y = clip_kwargs.get("y")
        clip_width = clip_kwargs.get("width")
        clip_height = clip_kwargs.get("height")
        if target is None:
            window = _resolve_window(live_connection)
            if clip_kwargs:
                result = window.screenshot(
                    path=path,
                    x=clip_x,
                    y=clip_y,
                    width=clip_width,
                    height=clip_height,
                )
            elif path:
                result = window.screenshot(path=path)
            else:
                result = window.screenshot()
        else:
            locator = _resolve_locator(live_connection, target=target)
            if clip_kwargs:
                result = locator.screenshot(
                    path=path,
                    x=clip_x,
                    y=clip_y,
                    width=clip_width,
                    height=clip_height,
                )
            elif path:
                result = locator.screenshot(path=path)
            else:
                result = locator.screenshot()
        result["target"] = target
        return result


    @mcp.tool()
    def hover(
        target: str,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Hover over the first widget matched by a target."""

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_locator(connection_state, target=target)
        locator.hover()
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            ok=True,
            target=target,
        )


    @mcp.tool()
    def scroll(
        target: str,
        delta_x: int = 0,
        delta_y: int = 0,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Send a mouse wheel scroll event to the first matched widget."""

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_locator(connection_state, target=target)
        locator.scroll(delta_x=delta_x, delta_y=delta_y)
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            ok=True,
            target=target,
            delta_x=delta_x,
            delta_y=delta_y,
        )


else:  # pragma: no cover - exercised only without the extra installed
    mcp = None


_CLI_TOOL_NAMES = (
    "session",
    "window",
    "snapshot",
    "inspect",
    "click",
    "input",
    "invoke",
    "press_key",
    "set_checked",
    "choose",
    "wait",
    "screenshot",
    "hover",
    "scroll",
)


def _cli_tool_registry() -> dict[str, Any]:
    registry: dict[str, Any] = {}
    for name in _CLI_TOOL_NAMES:
        func = globals().get(name)
        if callable(func):
            registry[name] = func
    return registry


def _cli_usage_text() -> str:
    return (
        "Interactive qplaywright MCP CLI\n\n"
        "Examples:\n"
        "  qplaywright-mcp cli\n"
        "  qplaywright-mcp cli session '{\"action\": \"attach\", \"port\": 19877}'\n"
        "  qplaywright-mcp cli snapshot '{\"depth\": 4}'\n\n"
        "REPL commands:\n"
        "  .tools                List available tools\n"
        "  .help                 Show CLI help\n"
        "  .help TOOL            Show one tool signature and docstring\n"
        "  TOOL {JSON}           Invoke one tool with a JSON object argument\n"
        "  quit / exit           Leave the REPL"
    )


def _cli_tool_help(tool_name: str, func: Any) -> str:
    signature = pyinspect.signature(func)
    doc = (pyinspect.getdoc(func) or "No description available.").strip()
    return f"{tool_name}{signature}\n\n{doc}"


def _split_cli_invocation(command_line: str) -> tuple[str, str | None]:
    parts = command_line.strip().split(None, 1)
    if not parts:
        raise ValueError("A tool name is required")
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


def _parse_cli_arguments(raw_arguments: str | None) -> dict[str, Any]:
    if raw_arguments is None or not raw_arguments.strip():
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "CLI arguments must be a JSON object, for example: '{\"target\": \"#amount_editor\"}'"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError("CLI arguments must decode to a JSON object")
    return parsed


def _print_cli_result(value: Any) -> None:
    if isinstance(value, str):
        print(value)
        return
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def _invoke_cli_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    registry = _cli_tool_registry()
    try:
        func = registry[tool_name]
    except KeyError as exc:
        available = ", ".join(sorted(registry)) or "<none>"
        raise ValueError(f"Unknown CLI tool {tool_name!r}. Available tools: {available}") from exc
    return func(**arguments)


def _handle_cli_meta_command(command_line: str) -> bool:
    normalized = command_line.strip()
    if normalized in {".tools", "tools"}:
        print("Available tools:")
        for name in sorted(_cli_tool_registry()):
            print(f"- {name}")
        return True

    if normalized in {".help", "help"}:
        print(_cli_usage_text())
        return True

    if normalized.startswith(".help ") or normalized.startswith("help "):
        _, tool_name = normalized.split(None, 1)
        registry = _cli_tool_registry()
        try:
            func = registry[tool_name]
        except KeyError as exc:
            raise ValueError(f"Unknown CLI tool {tool_name!r}") from exc
        print(_cli_tool_help(tool_name, func))
        return True

    return False


def _run_cli_command(tool_name: str, raw_arguments: str | None) -> int:
    try:
        result = _invoke_cli_tool(tool_name, _parse_cli_arguments(raw_arguments))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _print_cli_result(result)
    return 0


def _run_cli_repl() -> int:
    print("qplaywright MCP CLI. Type .help for usage.")
    while True:
        try:
            command_line = builtins.input("qplaywright> ").strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 130

        if not command_line:
            continue
        if command_line in {"quit", "exit", ".quit", ".exit"}:
            return 0

        try:
            if _handle_cli_meta_command(command_line):
                continue
            tool_name, raw_arguments = _split_cli_invocation(command_line)
            _run_cli_command(tool_name, raw_arguments)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)


def _run_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run qplaywright MCP tools directly from the command line or in an interactive REPL."
    )
    parser.add_argument(
        "tool",
        nargs="?",
        help="Tool name to call once. Omit to start an interactive CLI session.",
    )
    parser.add_argument(
        "arguments",
        nargs="?",
        help="JSON object with tool arguments, for example '{\"action\": \"attach\", \"port\": 19877}'.",
    )
    args = parser.parse_args(argv)

    if args.tool is None:
        return _run_cli_repl()
    return _run_cli_command(args.tool, args.arguments)


def _configure_stdio_for_mcp(transport: str) -> None:
    """Force UTF-8 stdio for MCP line transport on Windows and other locale-based consoles."""

    if transport != "stdio":
        return

    for stream_name, errors in (("stdin", "strict"), ("stdout", "strict"), ("stderr", "backslashreplace")):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors=errors)


def _screenshot_clip_kwargs(
    x: int | None = None,
    y: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, int]:
    values = {"x": x, "y": y, "width": width, "height": height}
    present = {key: value for key, value in values.items() if value is not None}
    if not present:
        return {}
    if len(present) != 4:
        raise ValueError("Screenshot clipping requires x, y, width, and height together")
    if x is None or y is None or width is None or height is None:
        raise ValueError("Screenshot clipping requires x, y, width, and height together")
    clip_x = int(x)
    clip_y = int(y)
    clip_width = int(width)
    clip_height = int(height)
    if clip_x < 0 or clip_y < 0 or clip_width <= 0 or clip_height <= 0:
        raise ValueError("Screenshot clipping requires non-negative x/y and positive width/height")
    return {"x": clip_x, "y": clip_y, "width": clip_width, "height": clip_height}


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point for running the qplaywright MCP server."""

    if _MCP_IMPORT_ERROR is not None or mcp is None:
        raise SystemExit(
            "The qplaywright MCP server requires the optional 'mcp' dependency. "
            "Install it with: pip install -e .[mcp]"
        )

    argv_list = list(argv if argv is not None else sys.argv[1:])
    mode = "serve"
    if argv_list and argv_list[0] in {"serve", "cli"}:
        mode = argv_list.pop(0)

    if mode == "cli":
        raise SystemExit(_run_cli(argv_list))

    parser = argparse.ArgumentParser(description="Run the qplaywright MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport to expose. stdio is the default and works with most hosts.",
    )
    args = parser.parse_args(argv_list)
    LOGGER.debug("Starting qplaywright MCP server with transport=%s", args.transport)
    _configure_stdio_for_mcp(args.transport)
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()