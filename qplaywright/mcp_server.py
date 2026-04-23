"""MCP server adapter for qplaywright.

This module exposes the existing synchronous qplaywright client as an MCP
server. It does not replace the Qt-side agent protocol. Instead, it adds a
northbound MCP tool layer so MCP hosts can connect to a running Qt app,
inspect windows, and interact with widgets via the existing selector model.
"""

import builtins
import argparse
import atexit
import contextlib
import inspect
import json
import logging
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qplaywright.protocol import DEFAULT_HOST, DEFAULT_PORT, METHOD_LIST_WINDOWS, METHOD_WIDGET_TREE
from qplaywright.protocol import (
    METHOD_CHECK,
    METHOD_CLICK,
    METHOD_DBLCLICK,
    METHOD_FILL,
    METHOD_FIND,
    METHOD_GET_METHODS,
    METHOD_GET_VALUE,
    METHOD_HOVER,
    METHOD_INVOKE,
    METHOD_IS_VISIBLE,
    METHOD_PING,
    METHOD_PRESS,
    METHOD_SCREENSHOT_WIDGET,
    METHOD_SELECT_OPTION,
    METHOD_TYPE,
    METHOD_UNCHECK,
)
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

    connections: dict[str, ManagedConnection] = field(default_factory=dict)

    def close_all(self) -> None:
        for connection in list(self.connections.values()):
            connection.close()
        self.connections.clear()


_SERVER_STATE = ServerState()
atexit.register(_SERVER_STATE.close_all)


def _normalize_connection_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("Connection name must not be empty")
    return normalized


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
        summaries.append(
            {
                "index": index,
                "wid": window["wid"],
                "title": window.get("title", ""),
                "class": window.get("class", ""),
                "width": window.get("width"),
                "height": window.get("height"),
            }
        )
    return summaries


def _resolve_window_scope_wid(
    connection: ManagedConnection,
    *,
    window_wid: int | None = None,
    window_title: str | None = None,
    window_index: int | None = None,
) -> int | None:
    if window_wid is None and window_title is None and window_index is None:
        return None
    window = _resolve_window(
        connection,
        window_wid=window_wid,
        window_title=window_title,
        window_index=window_index,
    )
    return window.wid


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
        f"Connection {connection.name!r} to {connection.host}:{connection.port} is no longer alive: {exc}. "
        "The remote qplaywright agent disconnected or restarted. Call connect again to establish a fresh session."
    )


def _get_connection(state: ServerState, name: str) -> ManagedConnection:
    normalized = _normalize_connection_name(name)
    try:
        connection = state.connections[normalized]
    except KeyError as exc:
        available = ", ".join(sorted(state.connections)) or "<none>"
        raise ValueError(
            f"Unknown connection {normalized!r}. Available connections: {available}"
        ) from exc

    try:
        _ping_connection(connection)
    except Exception as exc:
        connection.close()
        state.connections.pop(normalized, None)
        raise ConnectionError(_stale_connection_message(connection, exc)) from exc

    return connection


def connect_connection(
    state: ServerState,
    *,
    name: str,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 30.0,
) -> dict[str, Any]:
    normalized = _normalize_connection_name(name)
    replaced = normalized in state.connections
    if replaced:
        state.connections.pop(normalized).close()

    qplaywright = QPlaywright()
    app = qplaywright.connect(host=host, port=port, timeout=timeout)
    connection = ManagedConnection(
        name=normalized,
        qplaywright=qplaywright,
        app=app,
        host=host,
        port=port,
        timeout=timeout,
    )
    state.connections[normalized] = connection
    windows = _initialize_active_window(connection)
    return {
        "connection": normalized,
        "host": host,
        "port": port,
        "timeout": timeout,
        "replaced": replaced,
        "current_window_wid": connection.active_window_wid,
        "windows": windows,
    }


def launch_connection(
    state: ServerState,
    *,
    executable: str,
    args: Sequence[str] | None = None,
    name: str,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 30.0,
) -> dict[str, Any]:
    normalized = _normalize_connection_name(name)
    replaced = normalized in state.connections
    if replaced:
        state.connections.pop(normalized).close()

    qplaywright = QPlaywright()
    app = qplaywright.launch(executable, *(args or ()), host=host, port=port, timeout=timeout)
    connection = ManagedConnection(
        name=normalized,
        qplaywright=qplaywright,
        app=app,
        host=host,
        port=port,
        timeout=timeout,
        launched_executable=executable,
    )
    state.connections[normalized] = connection
    windows = _initialize_active_window(connection)
    return {
        "connection": normalized,
        "host": host,
        "port": port,
        "timeout": timeout,
        "replaced": replaced,
        "launched_executable": executable,
        "current_window_wid": connection.active_window_wid,
        "windows": windows,
    }


def disconnect_connection(state: ServerState, *, name: str) -> dict[str, Any]:
    connection = _get_connection(state, name)
    connection.close()
    state.connections.pop(connection.name, None)
    return {
        "connection": connection.name,
        "closed": True,
        "launched_executable": connection.launched_executable,
    }


def list_connections(state: ServerState) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name in sorted(state.connections):
        connection = state.connections[name]
        error: str | None = None
        alive = True
        try:
            _ping_connection(connection)
            window_count = len(_window_summary(connection))
        except Exception as exc:
            alive = False
            window_count = None
            error = _stale_connection_message(connection, exc)
        results.append(
            {
                "connection": connection.name,
                "host": connection.host,
                "port": connection.port,
                "timeout": connection.timeout,
                "launched_executable": connection.launched_executable,
                "window_count": window_count,
                "alive": alive,
                "error": error,
            }
        )
    return results


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
    has_text: str | None = None,
    nth: int | None = None,
    window_wid: int | None = None,
    window_title: str | None = None,
    window_index: int | None = None,
) -> Any:
    if not target.strip():
        raise ValueError("target must not be empty")

    if _SNAPSHOT_REF_PATTERN.match(target):
        ref_wid = connection.snapshot_refs.get(target)
        if ref_wid is None:
            raise ValueError(_target_not_found_message(connection, target))
        return Locator(connection.app._conn, "", widget_wid=ref_wid, timeout=connection.timeout)

    window = _resolve_window(
        connection,
        window_wid=window_wid,
        window_title=window_title,
        window_index=window_index,
    )
    locator = window.locator(target, has_text=has_text)
    if nth is not None:
        locator = locator.nth(nth)
    return locator


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


def _locator_methods(locator: Any) -> list[dict[str, Any]]:
    count = locator.count()
    if count == 0:
        raise ValueError("No widget found for method introspection")
    return locator.first().methods()


def _invoke_locator_method(
    locator: Any,
    *,
    method_name: str,
    args: dict[str, Any] | None = None,
) -> Any:
    count = locator.count()
    if count == 0:
        raise ValueError(
            "No widget found for invoke. Use inspect_widget or widget_tree first, then target with selectors like "
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
            f"Run browser_snapshot to refresh refs, or target a widget with selectors like {examples}."
        )
    if candidate:
        return (
            f"No widget found for target {candidate!r}. Run browser_snapshot, widget_tree, or inspect_widget to discover the UI, "
            f"then target a widget with selectors like {examples}."
        )
    return (
        "No widget target was resolved. Run browser_snapshot, widget_tree, or inspect_widget first, then target a widget with "
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
        "1. connect or launch a Qt app with an embedded qplaywright agent\n"
        "2. list_windows\n"
        "3. widget_tree or inspect_widget\n"
        "4. click, input, set_checked, press_key, choose, screenshot\n"
        "5. disconnect when finished"
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


def _window_snapshot_text(connection: ManagedConnection, *, depth: int = 10) -> str:
    return _format_widget_snapshot(_widget_tree_raw(connection, max_depth=depth), depth=depth)


def _write_text_file(path: str, content: str) -> str:
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return str(target_path)


def _browser_target_to_selector(target: str | None, element: str | None = None) -> str:
    if target and target.strip():
        return target.strip()
    if element and element.strip():
        return element.strip()
    raise ValueError("A target selector is required for this operation")


def _browser_target_params(connection: ManagedConnection, target: str | None, element: str | None = None) -> dict[str, Any]:
    if target and target in connection.snapshot_refs:
        return {"wid": connection.snapshot_refs[target]}
    return {"selector": _browser_target_to_selector(target, element)}


def _send_widget_command(
    connection: ManagedConnection,
    method: str,
    *,
    target: str | None = None,
    element: str | None = None,
    **extra: Any,
) -> Any:
    params = _browser_target_params(connection, target, element)
    params.update(extra)
    return connection.app._conn.send(method, params, timeout=connection.timeout)


def _compat_snapshot_result(
    managed_connection: ManagedConnection,
    *,
    snapshot_target: str | None = None,
    depth: int = 10,
    window_wid: int | None = None,
    window_title: str | None = None,
    window_index: int | None = None,
) -> dict[str, Any]:
    if snapshot_target is None:
        scoped_window_wid = _resolve_window_scope_wid(
            managed_connection,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
        return _snapshot_payload(
            managed_connection,
            _widget_tree_raw(managed_connection, max_depth=depth, window_wid=scoped_window_wid),
            depth=depth,
        )

    node = _send_widget_command(managed_connection, METHOD_FIND, target=snapshot_target)
    if node is None:
        raise ValueError(_target_not_found_message(managed_connection, snapshot_target))
    return _snapshot_payload(managed_connection, [node], depth=depth)


def _action_result_with_snapshot(
    managed_connection: ManagedConnection,
    *,
    snapshot_target: str | None = None,
    depth: int = 10,
    **payload: Any,
) -> dict[str, Any]:
    result = dict(payload)
    result.update(_compat_snapshot_result(managed_connection, snapshot_target=snapshot_target, depth=depth))
    return result


def _observe_action_window_state(managed_connection: ManagedConnection) -> dict[str, Any]:
    previous_active_window_wid = managed_connection.active_window_wid
    windows = _window_summary(managed_connection)

    active_window: dict[str, Any] | None = None
    if previous_active_window_wid is not None:
        active_window = next(
            (window for window in windows if window["wid"] == previous_active_window_wid),
            None,
        )
    if active_window is None and windows:
        active_window = windows[0]

    next_active_window_wid = active_window["wid"] if active_window is not None else None
    if next_active_window_wid != managed_connection.active_window_wid:
        _select_active_window(managed_connection, next_active_window_wid)

    return {
        "window_changed": next_active_window_wid != previous_active_window_wid,
        "active_window": ({**active_window, "is_active": True} if active_window is not None else None),
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
    effective_snapshot_target = None if result["window_changed"] else snapshot_target
    return _action_result_with_snapshot(
        managed_connection,
        snapshot_target=effective_snapshot_target,
        **result,
    )


def _stringify_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _browser_tabs_markdown(connection: ManagedConnection) -> str:
    lines: list[str] = []
    for index, window in enumerate(_window_summary(connection)):
        current = "(current) " if window["wid"] == connection.active_window_wid else ""
        title = window["title"] or window["class"] or f"Window {index}"
        lines.append(f"- {index}: {current}[{title}](qt://window/{window['wid']})")
    return "\n".join(lines)


def _wait_for_text_state(
    connection: ManagedConnection,
    *,
    text: str | None = None,
    text_gone: str | None = None,
    timeout: float = 5.0,
    poll_interval: float = 0.1,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = _compat_snapshot_result(connection, depth=10)["snapshot"]
        if text is not None and text in snapshot:
            return
        if text_gone is not None and text_gone not in snapshot:
            return
        time.sleep(poll_interval)

    if text is not None:
        raise TimeoutError(f"Timed out waiting for text {text!r}")
    raise TimeoutError(f"Timed out waiting for text to disappear: {text_gone!r}")


if FastMCP is not None:
    mcp = FastMCP(
        "qplaywright",
        instructions=(
            "Automate Qt QWidget applications through qplaywright. "
            "Use connect or launch first, then list_windows and inspect_widget "
            "before performing destructive UI actions."
        ),
        json_response=True,
    )


    @mcp.resource("qplaywright://help/selectors")
    def selector_help() -> str:
        """Selector syntax and recommended qplaywright MCP workflow."""

        return _selector_help_text()


    @mcp.tool()
    def connect(
        name: str = "default",
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Connect to a running Qt application with an embedded qplaywright agent."""

        return connect_connection(_SERVER_STATE, name=name, host=host, port=port, timeout=timeout)


    @mcp.tool()
    def launch(
        executable: str,
        args: list[str] | None = None,
        name: str = "default",
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Launch a Qt executable that embeds qplaywright agent support and connect to it."""

        return launch_connection(
            _SERVER_STATE,
            executable=executable,
            args=args,
            name=name,
            host=host,
            port=port,
            timeout=timeout,
        )


    @mcp.tool()
    def disconnect(name: str = "default") -> dict[str, Any]:
        """Close one MCP-managed qplaywright connection."""

        return disconnect_connection(_SERVER_STATE, name=name)


    @mcp.tool()
    def list_live_connections() -> list[dict[str, Any]]:
        """List the qplaywright connections currently tracked by the MCP server."""

        return list_connections(_SERVER_STATE)


    @mcp.tool()
    def list_windows(connection: str = "default") -> list[dict[str, Any]]:
        """List visible top-level windows for a connected Qt application."""

        return _window_summary(_get_connection(_SERVER_STATE, connection))


    @mcp.tool()
    def widget_tree(
        connection: str = "default",
        max_depth: int = 10,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return the current visible widget tree for the connected application."""

        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        connection_state = _get_connection(_SERVER_STATE, connection)
        scoped_window_wid = _resolve_window_scope_wid(
            connection_state,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
        return _widget_tree_raw(connection_state, max_depth=max_depth, window_wid=scoped_window_wid)


    @mcp.tool()
    def inspect_widget(
        target: str,
        connection: str = "default",
        has_text: str | None = None,
        nth: int | None = None,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
        property_name: str | None = None,
        include_methods: bool = False,
    ) -> dict[str, Any]:
        """Inspect widgets matched by a target and return common state for the first match."""

        locator = _resolve_locator(
            _get_connection(_SERVER_STATE, connection),
            target=target,
            has_text=has_text,
            nth=nth,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
        result = _inspect_locator(locator, property_name=property_name, include_methods=include_methods)
        result.update(
            {
                "connection": connection,
                "target": target,
                "has_text": has_text,
                "nth": nth,
                "window_wid": window_wid,
                "window_title": window_title,
                "window_index": window_index,
                "include_methods": include_methods,
            }
        )
        return result


    @mcp.tool()
    def get_widget_methods(
        target: str,
        connection: str = "default",
        has_text: str | None = None,
        nth: int | None = None,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
    ) -> dict[str, Any]:
        """Return exposed custom widget methods and any declared argument metadata."""

        locator = _resolve_locator(
            _get_connection(_SERVER_STATE, connection),
            target=target,
            has_text=has_text,
            nth=nth,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
        return {
            "connection": connection,
            "target": target,
            "has_text": has_text,
            "nth": nth,
            "window_wid": window_wid,
            "window_title": window_title,
            "window_index": window_index,
            "methods": _locator_methods(locator),
        }


    @mcp.tool()
    def click(
        target: str,
        connection: str = "default",
        has_text: str | None = None,
        nth: int | None = None,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
        count: int = 1,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Click or double-click the first widget matched by a target."""

        if count not in (1, 2):
            raise ValueError("count must be 1 or 2")

        connection_state = _get_connection(_SERVER_STATE, connection)
        locator = _resolve_locator(
            connection_state,
            target=target,
            has_text=has_text,
            nth=nth,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
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
            connection=connection,
        )


    @mcp.tool()
    def input(
        target: str,
        text: str,
        connection: str = "default",
        has_text: str | None = None,
        nth: int | None = None,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
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

        connection_state = _get_connection(_SERVER_STATE, connection)
        locator = _resolve_locator(
            connection_state,
            target=target,
            has_text=has_text,
            nth=nth,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
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
            connection=connection,
        )


    @mcp.tool()
    def invoke(
        target: str,
        method: str,
        connection: str = "default",
        has_text: str | None = None,
        nth: int | None = None,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
        args: dict[str, Any] | None = None,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Invoke one exposed custom widget method by exact name."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        locator = _resolve_locator(
            connection_state,
            target=target,
            has_text=has_text,
            nth=nth,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
        result = _invoke_locator_method(locator, method_name=method, args=args)
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            ok=True,
            connection=connection,
            target=target,
            method=method,
            args=dict(args or {}),
            result=result,
        )
    @mcp.tool()
    def press_key(
        target: str,
        key: str,
        connection: str = "default",
        has_text: str | None = None,
        nth: int | None = None,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Send a single key press to the first matched widget."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        locator = _resolve_locator(
            connection_state,
            target=target,
            has_text=has_text,
            nth=nth,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
        locator.press(key)
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            ok=True,
            target=target,
            key=key,
            connection=connection,
        )


    @mcp.tool()
    def set_checked(
        target: str,
        checked: bool,
        connection: str = "default",
        has_text: str | None = None,
        nth: int | None = None,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Check or uncheck the first matched checkable widget."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        locator = _resolve_locator(
            connection_state,
            target=target,
            has_text=has_text,
            nth=nth,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
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
            connection=connection,
        )


    @mcp.tool()
    def choose(
        target: str,
        connection: str = "default",
        has_text: str | None = None,
        nth: int | None = None,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
        value: str | None = None,
        index: int | None = None,
        label: str | None = None,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Select a combobox option by value, index, or label."""

        selector_count = sum(candidate is not None for candidate in (value, index, label))
        if selector_count != 1:
            raise ValueError("Exactly one of value, index, or label must be provided")

        connection_state = _get_connection(_SERVER_STATE, connection)
        locator = _resolve_locator(
            connection_state,
            target=target,
            has_text=has_text,
            nth=nth,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
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
            connection=connection,
        )


    @mcp.tool()
    def wait(
        target: str,
        connection: str = "default",
        has_text: str | None = None,
        nth: int | None = None,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
        state: str = "visible",
        timeout: float | None = None,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Wait until a widget reaches a supported state."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        locator = _resolve_locator(
            connection_state,
            target=target,
            has_text=has_text,
            nth=nth,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
        locator.wait_for(state=state, timeout=timeout)
        payload = {
            "ok": True,
            "target": target,
            "state": state,
            "timeout": timeout,
            "connection": connection,
        }
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            **payload,
        )


    @mcp.tool()
    def screenshot(
        connection: str = "default",
        target: str | None = None,
        has_text: str | None = None,
        nth: int | None = None,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
        path: str | None = None,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        """Capture a screenshot of a window or a matched widget, optionally clipped to a rectangle."""

        live_connection = _get_connection(_SERVER_STATE, connection)
        clip_kwargs = _screenshot_clip_kwargs(x=x, y=y, width=width, height=height)
        clip_x = clip_kwargs.get("x")
        clip_y = clip_kwargs.get("y")
        clip_width = clip_kwargs.get("width")
        clip_height = clip_kwargs.get("height")
        if target is None:
            window = _resolve_window(
                live_connection,
                window_wid=window_wid,
                window_title=window_title,
                window_index=window_index,
            )
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
            locator = _resolve_locator(
                live_connection,
                target=target,
                has_text=has_text,
                nth=nth,
                window_wid=window_wid,
                window_title=window_title,
                window_index=window_index,
            )
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
        result["connection"] = connection
        result["target"] = target
        return result


    @mcp.tool()
    def resize_window(
        width: int,
        height: int,
        connection: str = "default",
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
    ) -> dict[str, Any]:
        """Resize one top-level window."""

        window = _resolve_window(
            _get_connection(_SERVER_STATE, connection),
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
        window.resize(width, height)
        return {"ok": True, "width": width, "height": height, "connection": connection}


    @mcp.tool()
    def close_window(
        connection: str = "default",
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
    ) -> dict[str, Any]:
        """Close one top-level window."""

        window = _resolve_window(
            _get_connection(_SERVER_STATE, connection),
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
        window.close()
        return {"ok": True, "connection": connection, "window_wid": window.wid}


    @mcp.tool()
    def hover(
        target: str,
        connection: str = "default",
        has_text: str | None = None,
        nth: int | None = None,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Hover over the first widget matched by a target."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        locator = _resolve_locator(
            connection_state,
            target=target,
            has_text=has_text,
            nth=nth,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
        locator.hover()
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            ok=True,
            target=target,
            connection=connection,
        )


    @mcp.tool()
    def scroll(
        target: str,
        connection: str = "default",
        has_text: str | None = None,
        nth: int | None = None,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
        delta_x: int = 0,
        delta_y: int = 0,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Send a mouse wheel scroll event to the first matched widget."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        locator = _resolve_locator(
            connection_state,
            target=target,
            has_text=has_text,
            nth=nth,
            window_wid=window_wid,
            window_title=window_title,
            window_index=window_index,
        )
        locator.scroll(delta_x=delta_x, delta_y=delta_y)
        return _finalize_action_result(
            connection_state,
            include_snapshot=include_snapshot,
            snapshot_target=target,
            ok=True,
            target=target,
            delta_x=delta_x,
            delta_y=delta_y,
            connection=connection,
        )


    @mcp.tool(name="browser_click")
    def browser_click(
        target: str,
        connection: str = "default",
        element: str | None = None,
        doubleClick: bool = False,
        button: str = "left",
        modifiers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Perform click on a Qt widget using playwright-mcp style arguments."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        if button != "left":
            raise ValueError("Qt compatibility layer currently supports only left-click")
        if modifiers:
            raise ValueError("Qt compatibility layer does not support modifier-assisted clicks yet")
        _send_widget_command(
            connection_state,
            METHOD_DBLCLICK if doubleClick else METHOD_CLICK,
            target=target,
            element=element,
        )
        return _action_result_with_snapshot(
            connection_state,
            snapshot_target=target,
            ok=True,
            connection=connection,
            target=target,
            doubleClick=doubleClick,
        )


    @mcp.tool(name="browser_close")
    def browser_close(connection: str = "default") -> dict[str, Any]:
        """Close the current Qt window, similar to closing the current Playwright page."""

        result = close_window(connection=connection)
        connection_state = _get_connection(_SERVER_STATE, connection)
        remaining = _window_summary(connection_state)
        _select_active_window(connection_state, remaining[0]["wid"] if remaining else None)
        result["remaining_windows"] = remaining
        return result


    @mcp.tool(name="browser_fill_form")
    def browser_fill_form(fields: list[dict[str, Any]], connection: str = "default") -> dict[str, Any]:
        """Fill multiple form fields using playwright-mcp style field descriptors."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        results: list[dict[str, Any]] = []
        for field in fields:
            value = field.get("value")
            if value is None:
                raise ValueError("Each field must include a value")
            target = field.get("target")
            element = field.get("element")
            _send_widget_command(
                connection_state,
                METHOD_FILL,
                target=target,
                element=element,
                value=str(value),
            )
            results.append({"target": target, "element": element, "value": str(value)})
        return _action_result_with_snapshot(
            connection_state,
            snapshot_target=None,
            result=f"Filled {len(results)} fields",
            fields=results,
            connection=connection,
        )


    @mcp.tool(name="browser_hover")
    def browser_hover(target: str, connection: str = "default", element: str | None = None) -> dict[str, Any]:
        """Hover over a Qt widget using playwright-mcp style arguments."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        _send_widget_command(connection_state, METHOD_HOVER, target=target, element=element)
        return _action_result_with_snapshot(
            connection_state,
            snapshot_target=target,
            ok=True,
            connection=connection,
            target=target,
        )


    @mcp.tool(name="browser_press_key")
    def browser_press_key(
        key: str,
        connection: str = "default",
        target: str | None = None,
        element: str | None = None,
    ) -> dict[str, Any]:
        """Press a key on a targeted Qt widget."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        _send_widget_command(connection_state, METHOD_PRESS, target=target, element=element, key=key)
        return _action_result_with_snapshot(
            connection_state,
            snapshot_target=target,
            ok=True,
            connection=connection,
            target=target,
            key=key,
        )


    @mcp.tool(name="browser_resize")
    def browser_resize(width: int, height: int, connection: str = "default") -> dict[str, Any]:
        """Resize the current Qt top-level window."""

        return resize_window(width=width, height=height, connection=connection)


    @mcp.tool(name="browser_select_option")
    def browser_select_option(
        target: str,
        values: list[str],
        connection: str = "default",
        element: str | None = None,
    ) -> dict[str, Any]:
        """Select one option in a Qt combobox using playwright-mcp style arguments."""

        if not values:
            raise ValueError("values must contain exactly one option")
        if len(values) > 1:
            raise ValueError("Qt compatibility layer currently supports selecting one option at a time")
        connection_state = _get_connection(_SERVER_STATE, connection)
        _send_widget_command(
            connection_state,
            METHOD_SELECT_OPTION,
            target=target,
            element=element,
            value=values[0],
        )
        return _action_result_with_snapshot(
            connection_state,
            snapshot_target=target,
            ok=True,
            connection=connection,
            target=target,
            value=values[0],
        )


    @mcp.tool(name="browser_snapshot")
    def browser_snapshot(
        connection: str = "default",
        target: str | None = None,
        filename: str | None = None,
        depth: int = 10,
        window_wid: int | None = None,
        window_title: str | None = None,
        window_index: int | None = None,
    ) -> dict[str, Any]:
        """Return a text snapshot of the current Qt widget tree or one targeted widget."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        if target is None:
            payload = _snapshot_payload(
                connection_state,
                _widget_tree_raw(
                    connection_state,
                    max_depth=depth,
                    window_wid=_resolve_window_scope_wid(
                        connection_state,
                        window_wid=window_wid,
                        window_title=window_title,
                        window_index=window_index,
                    ),
                ),
                depth=depth,
            )
        else:
            node = _send_widget_command(
                connection_state,
                METHOD_FIND,
                target=target,
            )
            if node is None:
                raise ValueError(_target_not_found_message(connection_state, target))
            payload = _snapshot_payload(connection_state, [node], depth=depth)

        result = {
            "connection": connection,
            "target": target,
            "window_wid": window_wid,
            "window_title": window_title,
            "window_index": window_index,
            **payload,
        }
        if filename is not None:
            result["path"] = _write_text_file(filename, payload["snapshot"])
        return result


    @mcp.tool(name="browser_tabs")
    def browser_tabs(
        action: str,
        connection: str = "default",
        index: int | None = None,
        url: str | None = None,
    ) -> dict[str, Any]:
        """Manage Qt top-level windows using a playwright-mcp style tabs API."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        windows = _window_summary(connection_state)

        if action == "list":
            return {"result": _browser_tabs_markdown(connection_state), "windows": windows, "connection": connection}

        if action == "select":
            if index is None:
                raise ValueError("index is required when action='select'")
            if index < 0 or index >= len(windows):
                raise IndexError(f"Window index {index} is out of range")
            _select_active_window(connection_state, windows[index]["wid"])
            return {"result": _browser_tabs_markdown(connection_state), "selected": windows[index], "connection": connection}

        if action == "close":
            if index is None and connection_state.active_window_wid is None:
                raise ValueError("No current window is selected")
            target_index = index
            if target_index is None:
                target_index = next(
                    (i for i, window in enumerate(windows) if window["wid"] == connection_state.active_window_wid),
                    None,
                )
            if target_index is None or target_index < 0 or target_index >= len(windows):
                raise IndexError("Window index is out of range")
            closed_window = windows[target_index]
            close_window(connection=connection, window_wid=closed_window["wid"])
            remaining = _window_summary(connection_state)
            _select_active_window(connection_state, remaining[0]["wid"] if remaining else None)
            return {
                "result": _browser_tabs_markdown(connection_state),
                "closed": closed_window,
                "windows": remaining,
                "connection": connection,
            }

        if action == "new":
            raise ValueError(
                "Qt compatibility layer cannot create a new top-level window from a URL. "
                "Drive the application-specific action that opens the window instead."
            )

        raise ValueError(f"Unsupported browser_tabs action: {action!r}")


    @mcp.tool(name="browser_take_screenshot")
    def browser_take_screenshot(
        connection: str = "default",
        element: str | None = None,
        target: str | None = None,
        type: str = "png",
        filename: str | None = None,
        fullPage: bool = False,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        """Take a screenshot of the current Qt window or a specific widget, optionally clipped to a rectangle."""

        if type not in {"png", "jpeg", "jpg"}:
            raise ValueError("Supported screenshot types are png and jpeg")
        if fullPage:
            raise ValueError("Qt compatibility layer does not distinguish viewport and full-page screenshots")
        connection_state = _get_connection(_SERVER_STATE, connection)
        clip_kwargs = _screenshot_clip_kwargs(x=x, y=y, width=width, height=height)
        if target is None and element is None:
            if clip_kwargs:
                return screenshot(
                    connection=connection,
                    path=filename,
                    x=clip_kwargs["x"],
                    y=clip_kwargs["y"],
                    width=clip_kwargs["width"],
                    height=clip_kwargs["height"],
                )
            return screenshot(connection=connection, path=filename)

        result = _send_widget_command(
            connection_state,
            METHOD_SCREENSHOT_WIDGET,
            target=target,
            element=element,
            path=filename,
            **clip_kwargs,
        )
        result["connection"] = connection
        result["selector"] = target or element
        return result


    @mcp.tool(name="browser_type")
    def browser_type(
        target: str,
        text: str,
        connection: str = "default",
        element: str | None = None,
        submit: bool = False,
        slowly: bool = False,
    ) -> dict[str, Any]:
        """Type text into an editable Qt widget using playwright-mcp style arguments."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        if slowly:
            _send_widget_command(connection_state, METHOD_TYPE, target=target, element=element, text=text, delay=50)
            payload = {"ok": True, "connection": connection, "target": target, "text": text, "slowly": True}
        else:
            _send_widget_command(connection_state, METHOD_FILL, target=target, element=element, value=text)
            payload = {"ok": True, "connection": connection, "target": target, "text": text, "slowly": False}
        if submit:
            _send_widget_command(connection_state, METHOD_PRESS, target=target, element=element, key="Enter")
            payload["submitted"] = True
        return _action_result_with_snapshot(connection_state, snapshot_target=target, **payload)


    @mcp.tool(name="browser_wait_for")
    def browser_wait_for(
        connection: str = "default",
        time: float | None = None,
        text: str | None = None,
        textGone: str | None = None,
        timeout: float = 5.0,
        include_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Wait for a duration or for text to appear or disappear in the widget snapshot."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        if time is not None:
            time_seconds = max(time, 0)
            time_module = __import__("time")
            time_module.sleep(time_seconds)
            payload = {"ok": True, "waited": time_seconds, "connection": connection}
            return _finalize_action_result(connection_state, include_snapshot=include_snapshot, **payload)

        if text is None and textGone is None:
            raise ValueError("Provide time, text, or textGone")

        _wait_for_text_state(
            connection_state,
            text=text,
            text_gone=textGone,
            timeout=timeout,
        )
        payload = {
            "ok": True,
            "text": text,
            "textGone": textGone,
            "timeout": timeout,
            "connection": connection,
        }
        return _finalize_action_result(connection_state, include_snapshot=include_snapshot, **payload)


    @mcp.tool(name="browser_verify_element_visible")
    def browser_verify_element_visible(
        role: str,
        accessibleName: str,
        connection: str = "default",
    ) -> dict[str, Any]:
        """Verify a Qt widget is visible by role and accessible/displayed name."""

        target = f"role={role}"
        locator_info = inspect_widget(target=target, has_text=accessibleName, connection=connection)
        if not locator_info["exists"] or not locator_info["is_visible"]:
            raise AssertionError(f"Expected visible element role={role!r} accessibleName={accessibleName!r}")
        return {
            "ok": True,
            "connection": connection,
            "role": role,
            "accessibleName": accessibleName,
            "snapshot": _compat_snapshot_result(
                _get_connection(_SERVER_STATE, connection),
                depth=10,
            )["snapshot"],
        }


    @mcp.tool(name="browser_verify_text_visible")
    def browser_verify_text_visible(text: str, connection: str = "default") -> dict[str, Any]:
        """Verify a text fragment is visible in the current Qt widget snapshot."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        payload = _compat_snapshot_result(connection_state, depth=10)
        if text not in payload["snapshot"]:
            raise AssertionError(f"Expected text to be visible: {text!r}")
        return {"ok": True, "connection": connection, "text": text, **payload}


    @mcp.tool(name="browser_verify_value")
    def browser_verify_value(
        type: str,
        element: str,
        target: str,
        value: str,
        connection: str = "default",
    ) -> dict[str, Any]:
        """Verify the current value of a target widget."""

        connection_state = _get_connection(_SERVER_STATE, connection)
        actual_value = _send_widget_command(connection_state, METHOD_GET_VALUE, target=target, element=element)
        actual_text = _stringify_value(actual_value)
        if actual_text != value:
            raise AssertionError(
                f"Expected value {value!r} for {type} {element!r}, got {actual_text!r}"
            )
        return _action_result_with_snapshot(
            connection_state,
            snapshot_target=target,
            ok=True,
            connection=connection,
            type=type,
            element=element,
            target=target,
            expected=value,
            actual=actual_text,
        )

else:  # pragma: no cover - exercised only without the extra installed
    mcp = None


_CLI_TOOL_NAMES = (
    "connect",
    "launch",
    "disconnect",
    "list_live_connections",
    "list_windows",
    "widget_tree",
    "inspect_widget",
    "get_widget_methods",
    "click",
    "input",
    "invoke",
    "press_key",
    "set_checked",
    "choose",
    "wait",
    "screenshot",
    "resize_window",
    "close_window",
    "hover",
    "scroll",
    "browser_click",
    "browser_close",
    "browser_fill_form",
    "browser_hover",
    "browser_press_key",
    "browser_resize",
    "browser_select_option",
    "browser_snapshot",
    "browser_tabs",
    "browser_take_screenshot",
    "browser_type",
    "browser_wait_for",
    "browser_verify_element_visible",
    "browser_verify_text_visible",
    "browser_verify_value",
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
        "  qplaywright-mcp cli connect '{\"name\": \"probe\", \"port\": 19877}'\n"
        "  qplaywright-mcp cli browser_snapshot '{\"connection\": \"probe\", \"depth\": 4}'\n\n"
        "REPL commands:\n"
        "  .tools                List available tools\n"
        "  .help                 Show CLI help\n"
        "  .help TOOL            Show one tool signature and docstring\n"
        "  TOOL {JSON}           Invoke one tool with a JSON object argument\n"
        "  quit / exit           Leave the REPL"
    )


def _cli_tool_help(tool_name: str, func: Any) -> str:
    signature = inspect.signature(func)
    doc = (inspect.getdoc(func) or "No description available.").strip()
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
            "CLI arguments must be a JSON object, for example: '{\"connection\": \"default\"}'"
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
        help="JSON object with tool arguments, for example '{\"name\": \"probe\", \"port\": 19877}'.",
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