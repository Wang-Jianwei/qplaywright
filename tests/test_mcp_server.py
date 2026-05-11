from __future__ import annotations

import base64
import anyio
import json
from pathlib import Path
from typing import Any, cast

import pytest

import qplaywright.mcp_server as mcp_server


class FakeQPlaywright:
    def __init__(self):
        self.closed = False
        self.connected = None
        self.launched = None

    def connect(self, *, host: str, port: int, timeout: float, agent_name: str | None = None):
        self.connected = (host, port, timeout)
        return FakeApp([])

    def launch(self, executable, *args, host: str, port: int, timeout: float, agent_name: str | None = None):
        self.launched = (executable, list(args), host, port, timeout)
        return FakeApp([])

    def close(self) -> None:
        self.closed = True


class FakeApp:
    def __init__(self, windows):
        self._windows = windows
        self.closed = False
        self._conn: FakeTransportConn | None = None

    def windows(self):
        return [window for window in self._windows if not window.closed]

    def close(self) -> None:
        self.closed = True


class FakeTransportConn:
    def __init__(self, *, error: Exception | None = None, responses: dict[str, object] | None = None):
        self.error = error
        self.responses = responses or {}
        self.calls = []

    def send(self, method: str, params=None, *, timeout=None):
        self.calls.append({"method": method, "params": params, "timeout": timeout})
        if self.error is not None:
            raise self.error
        response = self.responses.get(method, {"ok": True})
        if isinstance(response, list):
            if len(response) > 1:
                return response.pop(0)
            return response[0]
        return response


class FakeWindow:
    def __init__(self, wid: int, title: str, *, is_modal: bool = False):
        self.wid = wid
        self._title = title
        self._is_modal = is_modal
        self.closed = False
        self.resized_to = None
        self.screenshot_calls = []

    def title(self) -> str:
        return self._title

    def resize(self, width: int, height: int) -> None:
        self.resized_to = (width, height)

    def close(self) -> None:
        self.closed = True

    def isModal(self) -> bool:
        return self._is_modal

    def locator(self, target: str):
        return FakeLocator(count=1, target=target, widget_wid=101)

    def screenshot(self, **kwargs):
        self.screenshot_calls.append(kwargs)
        return {"path": kwargs.get("path"), "width": 320, "height": 240}


class FakeLocator:
    def __init__(self, *, count: int, invoke_result=None, target: str | None = None, widget_wid: int = 101):
        self._count = count
        self._invoke_result = invoke_result
        self._target = target
        self._widget_wid = widget_wid
        self.action_calls = []
        self.wait_calls = []
        self.screenshot_calls = []

    def count(self) -> int:
        return self._count

    def first(self):
        return self

    def text_content(self) -> str:
        return "Save"

    def input_value(self) -> str:
        return "ready"

    def all_text_contents(self) -> list[str]:
        return ["Save", "Cancel"]

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return False

    def is_checked(self) -> bool:
        return True

    def bounding_box(self) -> dict[str, int]:
        return {"x": 1, "y": 2, "width": 3, "height": 4}

    def get_attribute(self, name: str) -> str:
        return f"attr:{name}"

    def properties(self) -> dict[str, object]:
        return {
            "class": "FancyAmountEdit",
            "objectName": self._target or "amount_editor",
            "accessibleName": "Amount editor",
            "accessibleDescription": "输入金额",
            "geometry": {"x": 11, "y": 22, "width": 130, "height": 28},
            "myText": "pressme",
        }

    def methods(self) -> list[dict[str, object]]:
        return [
            {
                "name": "setAmount",
                "args": [
                    {
                        "name": "value",
                        "type": "QString",
                        "brief": "Formatted amount text",
                        "required": True,
                        "defaultValue": None,
                    }
                ],
                "returnType": "QVariant",
                "brief": "Update the current amount",
            }
        ]

    def invoke(self, method_name: str, args: dict[str, object] | None = None):
        self.action_calls.append(("invoke", {"method_name": method_name, "args": dict(args or {})}))
        if self._invoke_result is not None:
            return self._invoke_result
        return {
            "method_name": method_name,
            "args": dict(args or {}),
        }

    def click(self):
        self.action_calls.append(("click", {}))

    def dblclick(self):
        self.action_calls.append(("dblclick", {}))

    def fill(self, value: str):
        self.action_calls.append(("fill", {"value": value}))

    def clear(self):
        self.action_calls.append(("clear", {}))

    def type(self, text: str, *, delay: int = 0):
        self.action_calls.append(("type", {"text": text, "delay": delay}))

    def press(self, key: str):
        self.action_calls.append(("press", {"key": key}))

    def check(self):
        self.action_calls.append(("check", {}))

    def uncheck(self):
        self.action_calls.append(("uncheck", {}))

    def select_option(self, *, value=None, index=None, label=None):
        self.action_calls.append(("select_option", {"value": value, "index": index, "label": label}))

    def hover(self):
        self.action_calls.append(("hover", {}))

    def scroll(self, *, delta_x: int = 0, delta_y: int = 0):
        self.action_calls.append(("scroll", {"delta_x": delta_x, "delta_y": delta_y}))

    def wait_for(self, *, state: str, timeout: float | None = None):
        self.wait_calls.append({"state": state, "timeout": timeout})

    def screenshot(self, **kwargs):
        self.screenshot_calls.append(kwargs)
        return {"path": kwargs.get("path"), "width": 120, "height": 40}

    def _resolve_owner_wid(self) -> int:
        return self._widget_wid


def _item_target(owner: str = "#tree") -> dict[str, object]:
    return {
        "owner": owner,
        "item": {"kind": "tree_node", "path": [0, 1]},
    }


def _v2_snapshot_payload(label: str, *, handle: str = "w1", class_name: str = "DemoWindow") -> dict[str, object]:
    return {
        "snapshot": f"- {label} @{handle}",
        "root_handle": handle,
        "widgets": [{"handle": handle, "class": class_name}],
    }


def test_connect_connection_replaces_existing(monkeypatch):
    created: list[FakeQPlaywright] = []

    def fake_factory():
        instance = FakeQPlaywright()
        created.append(instance)
        return instance

    monkeypatch.setattr(mcp_server, "QPlaywright", fake_factory)

    existing_qplaywright = FakeQPlaywright()
    existing_app = FakeApp([])
    state = mcp_server.ServerState(
        connection=mcp_server.ManagedConnection(
            name="default",
            qplaywright=existing_qplaywright,
            app=existing_app,
            host="127.0.0.1",
            port=19876,
            timeout=30.0,
        )
    )

    result = mcp_server.connect_connection(state, host="127.0.0.1", port=19877, timeout=5.0)

    assert result.port == 19877
    assert state.connection is result
    assert existing_qplaywright.closed is True
    assert existing_app.closed is True
    assert created[0].connected == ("127.0.0.1", 19877, 5.0)


def test_connect_connection_clears_existing_when_new_connect_fails(monkeypatch):
    class FailingQPlaywright(FakeQPlaywright):
        def connect(self, *, host: str, port: int, timeout: float, agent_name: str | None = None):
            self.connected = (host, port, timeout)
            raise ConnectionError("protocol mismatch")

    monkeypatch.setattr(mcp_server, "QPlaywright", FailingQPlaywright)

    existing_qplaywright = FakeQPlaywright()
    existing_app = FakeApp([])
    existing_connection = mcp_server.ManagedConnection(
        name="default",
        qplaywright=existing_qplaywright,
        app=existing_app,
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )
    state = mcp_server.ServerState(connection=existing_connection)

    with pytest.raises(ConnectionError, match="protocol mismatch"):
        mcp_server.connect_connection(state, host="127.0.0.1", port=19877, timeout=5.0)

    assert existing_qplaywright.closed is True
    assert existing_app.closed is True
    assert state.connection is None


def test_launch_connection_tracks_executable(monkeypatch):
    created: list[FakeQPlaywright] = []

    def fake_factory():
        instance = FakeQPlaywright()
        created.append(instance)
        return instance

    monkeypatch.setattr(mcp_server, "QPlaywright", fake_factory)

    state = mcp_server.ServerState()
    result = mcp_server.launch_connection(
        state,
        executable="demo_app.exe",
        args=["--flag"],
        host="127.0.0.1",
        port=19878,
        timeout=6.0,
    )

    assert result.launched_executable == "demo_app.exe"
    assert created[0].launched == ("demo_app.exe", ["--flag"], "127.0.0.1", 19878, 6.0)


def test_get_connection_removes_stale_session_from_state():
    app = FakeApp([])
    app._conn = FakeTransportConn(error=ConnectionError("Agent closed connection"))
    qplaywright = FakeQPlaywright()
    state = mcp_server.ServerState(
        connection=mcp_server.ManagedConnection(
            name="default",
            qplaywright=qplaywright,
            app=app,
            host="127.0.0.1",
            port=19876,
            timeout=30.0,
        )
    )

    with pytest.raises(ConnectionError, match="Call session attach again"):
        mcp_server._get_connection(state)

    assert state.connection is None
    assert app.closed is True
    assert qplaywright.closed is True


def test_resolve_window_prefers_wid_then_title():
    first = FakeWindow(1, "Main Window")
    second = FakeWindow(2, "Preferences")
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([first, second]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    assert mcp_server._resolve_window(connection, window_wid=2) is second
    assert mcp_server._resolve_window(connection, window_title="pref") is second

    with pytest.raises(IndexError):
        mcp_server._resolve_window(connection, window_index=5)


def test_resolve_window_explicit_index_overrides_active_window():
    first = FakeWindow(1, "Main Window")
    second = FakeWindow(2, "Secondary Window")
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([first, second]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=1,
    )

    assert mcp_server._resolve_window(connection) is first
    assert mcp_server._resolve_window(connection, window_index=1) is second


def test_require_exactly_one_window_selector_rejects_missing_or_multiple_values():
    with pytest.raises(ValueError, match="exactly one of index, wid, or title"):
        mcp_server._require_exactly_one_window_selector(index=None, wid=None, title=None)

    with pytest.raises(ValueError, match="exactly one of index, wid, or title"):
        mcp_server._require_exactly_one_window_selector(index=0, wid=11, title=None)

    mcp_server._require_exactly_one_window_selector(index=0, wid=None, title=None)


def test_resolve_locator_accepts_stable_handle_as_widget_id():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        wid_to_handle={42: "w2"},
        handle_to_wid={"w2": 42},
    )
    connection.app._conn = FakeTransportConn()

    locator = mcp_server._resolve_locator(connection, target="w2")
    locator.click()

    assert connection.app._conn.calls == [
        {"method": "click", "params": {"wid": 42}, "timeout": 30.0}
    ]


def test_resolve_locator_rejects_unknown_stable_handle():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        wid_to_handle={41: "w1"},
        handle_to_wid={"w1": 41},
    )

    with pytest.raises(ValueError, match="Unknown stable handle 'w9'"):
        mcp_server._resolve_locator(connection, target="w9")


def test_resolve_item_locator_uses_owner_locator_wid():
    window = FakeWindow(11, "Main")
    app = FakeApp([window])
    app._conn = FakeTransportConn(responses={"item_click": True})
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=app,
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    locator = mcp_server._resolve_item_locator(connection, target=_item_target())
    locator.click()

    assert app._conn.calls == [
        {
            "method": "item_click",
            "params": {"wid": 101, "item": {"kind": "tree_node", "path": [0, 1]}},
            "timeout": 30.0,
        }
    ]


def test_inspect_accepts_item_target(monkeypatch):
    window = FakeWindow(11, "Main")
    app = FakeApp([window])
    app._conn = FakeTransportConn(
        responses={
            "item_properties": {
                "kind": "tree_node",
                "text": "Advanced",
                "edit_value": "Advanced Draft",
                "path": ["Settings", "Advanced"],
                "expanded": False,
                "selected": True,
            },
            "item_text": "Advanced",
            "item_visible": True,
            "item_bounding_box": {"x": 10, "y": 20, "width": 30, "height": 12},
        }
    )
    state = mcp_server.ServerState(
        connection=mcp_server.ManagedConnection(
            name="demo",
            qplaywright=FakeQPlaywright(),
            app=app,
            host="127.0.0.1",
            port=19876,
            timeout=30.0,
            active_window_wid=11,
        )
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    result = mcp_server.inspect(target=_item_target(), include_properties=True)

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["kind"] == "tree_node"
    assert result["text"] == "Advanced"
    assert result["edit_value"] == "Advanced Draft"
    assert result["visible"] is True
    assert result["properties"]["selected"] is True


def test_inspect_items_wraps_entries_with_reusable_targets(monkeypatch):
    window = FakeWindow(11, "Main")
    app = FakeApp([window])
    app._conn = FakeTransportConn(
        responses={
            "item_view_inspect": {
                "kind": "tree",
                "items": [
                    {
                        "item": {"kind": "tree_node", "path": [0]},
                        "text": "Settings",
                        "visible": True,
                        "expanded": True,
                    }
                ],
                "truncated": False,
            }
        }
    )
    state = mcp_server.ServerState(
        connection=mcp_server.ManagedConnection(
            name="demo",
            qplaywright=FakeQPlaywright(),
            app=app,
            host="127.0.0.1",
            port=19876,
            timeout=30.0,
            active_window_wid=11,
        )
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    result = mcp_server.inspect_items(owner="#tree", max_depth=2)

    assert result == {
        "ok": True,
        "owner": "#tree",
        "kind": "tree",
        "items": [
            {
                "item": {"kind": "tree_node", "path": [0]},
                "text": "Settings",
                "visible": True,
                "expanded": True,
                "target": {"owner": "#tree", "item": {"kind": "tree_node", "path": [0]}},
            }
        ],
        "truncated": False,
    }
    assert app._conn.calls[-1]["method"] == "item_view_inspect"


def test_inspect_items_wraps_tab_entries_with_reusable_targets(monkeypatch):
    window = FakeWindow(11, "Main")
    app = FakeApp([window])
    app._conn = FakeTransportConn(
        responses={
            "item_view_inspect": {
                "kind": "tab",
                "items": [
                    {
                        "item": {"kind": "tab_item", "index": 1},
                        "text": "Data",
                        "selected": False,
                    }
                ],
                "truncated": False,
            }
        }
    )
    state = mcp_server.ServerState(
        connection=mcp_server.ManagedConnection(
            name="demo",
            qplaywright=FakeQPlaywright(),
            app=app,
            host="127.0.0.1",
            port=19876,
            timeout=30.0,
            active_window_wid=11,
        )
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    result = mcp_server.inspect_items(owner="#main_tabs", max_items=10)

    assert result == {
        "ok": True,
        "owner": "#main_tabs",
        "kind": "tab",
        "items": [
            {
                "item": {"kind": "tab_item", "index": 1},
                "text": "Data",
                "selected": False,
                "target": {"owner": "#main_tabs", "item": {"kind": "tab_item", "index": 1}},
            }
        ],
        "truncated": False,
    }


def test_click_accepts_item_target(monkeypatch):
    window = FakeWindow(11, "Main")
    app = FakeApp([window])
    app._conn = FakeTransportConn(responses={"item_dblclick": True})
    state = mcp_server.ServerState(
        connection=mcp_server.ManagedConnection(
            name="demo",
            qplaywright=FakeQPlaywright(),
            app=app,
            host="127.0.0.1",
            port=19876,
            timeout=30.0,
            active_window_wid=11,
        )
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(mcp_server, "_finalize_action_result", lambda *args, **kwargs: kwargs)

    target = _item_target()
    result = mcp_server.click(target=target, count=2, include_snapshot=True)

    assert app._conn.calls[-1]["method"] == "item_dblclick"
    assert result["state_target"] == target
    assert result["snapshot_target"] == "#tree"


def test_click_without_target_uses_active_window_transport(monkeypatch):
    window = FakeWindow(11, "Main")
    app = FakeApp([window])
    app._conn = FakeTransportConn(responses={"click": True})
    state = mcp_server.ServerState(
        connection=mcp_server.ManagedConnection(
            name="demo",
            qplaywright=FakeQPlaywright(),
            app=app,
            host="127.0.0.1",
            port=19876,
            timeout=30.0,
            active_window_wid=11,
        )
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(mcp_server, "_finalize_action_result", lambda *args, **kwargs: kwargs)

    result = mcp_server.click(x=12, y=34, include_snapshot=True)

    assert app._conn.calls[-1] == {
        "method": "click",
        "params": {"x": 12, "y": 34, "window_wid": 11},
        "timeout": 30.0,
    }
    assert result["target"] is None
    assert result["x"] == 12
    assert result["y"] == 34
    assert result["snapshot_target"] is None


def test_click_rejects_mixed_target_and_coordinates(monkeypatch):
    window = FakeWindow(11, "Main")
    app = FakeApp([window])
    state = mcp_server.ServerState(
        connection=mcp_server.ManagedConnection(
            name="demo",
            qplaywright=FakeQPlaywright(),
            app=app,
            host="127.0.0.1",
            port=19876,
            timeout=30.0,
            active_window_wid=11,
        )
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    with pytest.raises(ValueError, match="does not accept x/y together with target"):
        mcp_server.click(target="w2", x=1, y=2)


def test_hover_without_target_uses_active_window_transport(monkeypatch):
    window = FakeWindow(11, "Main")
    app = FakeApp([window])
    app._conn = FakeTransportConn(responses={"hover": True})
    state = mcp_server.ServerState(
        connection=mcp_server.ManagedConnection(
            name="demo",
            qplaywright=FakeQPlaywright(),
            app=app,
            host="127.0.0.1",
            port=19876,
            timeout=30.0,
            active_window_wid=11,
        )
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(mcp_server, "_finalize_action_result", lambda *args, **kwargs: kwargs)

    result = mcp_server.hover(x=7, y=9)

    assert app._conn.calls[-1] == {
        "method": "hover",
        "params": {"x": 7, "y": 9, "window_wid": 11},
        "timeout": 30.0,
    }
    assert result["target"] is None
    assert result["x"] == 7
    assert result["y"] == 9


def test_wait_accepts_item_target_visible_state(monkeypatch):
    window = FakeWindow(11, "Main")
    app = FakeApp([window])
    app._conn = FakeTransportConn(responses={"item_visible": [False, True]})
    state = mcp_server.ServerState(
        connection=mcp_server.ManagedConnection(
            name="demo",
            qplaywright=FakeQPlaywright(),
            app=app,
            host="127.0.0.1",
            port=19876,
            timeout=30.0,
            active_window_wid=11,
        )
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(mcp_server, "_finalize_action_result", lambda *args, **kwargs: kwargs)

    result = mcp_server.wait(target=_item_target(), state="visible", timeout=0.2)

    assert result["state"] == "visible"
    assert [call["method"] for call in app._conn.calls][-2:] == ["item_visible", "item_visible"]


def test_wait_accepts_item_target_text_condition(monkeypatch):
    window = FakeWindow(11, "Main")
    app = FakeApp([window])
    app._conn = FakeTransportConn(responses={"item_text": ["Loading", "Ready"]})
    state = mcp_server.ServerState(
        connection=mcp_server.ManagedConnection(
            name="demo",
            qplaywright=FakeQPlaywright(),
            app=app,
            host="127.0.0.1",
            port=19876,
            timeout=30.0,
            active_window_wid=11,
        )
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(mcp_server, "_finalize_action_result", lambda *args, **kwargs: kwargs)

    result = mcp_server.wait(target=_item_target(), condition="text_contains", expected="ead", timeout=0.2)

    assert result["condition"] == "text_contains"
    assert [call["method"] for call in app._conn.calls][-2:] == ["item_text", "item_text"]


def test_set_expanded_uses_item_expand(monkeypatch):
    window = FakeWindow(11, "Main")
    app = FakeApp([window])
    app._conn = FakeTransportConn(responses={"item_expand": True})
    state = mcp_server.ServerState(
        connection=mcp_server.ManagedConnection(
            name="demo",
            qplaywright=FakeQPlaywright(),
            app=app,
            host="127.0.0.1",
            port=19876,
            timeout=30.0,
            active_window_wid=11,
        )
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(mcp_server, "_finalize_action_result", lambda *args, **kwargs: kwargs)

    target = _item_target()
    result = mcp_server.set_expanded(target=target, expanded=True)

    assert app._conn.calls[-1]["method"] == "item_expand"
    assert result["expanded"] is True
    assert result["snapshot_target"] == "#tree"


def test_handle_for_wid_is_stable_across_calls():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    assert connection.handle_for_wid(1) == "w1"
    assert connection.handle_for_wid(1) == "w1"
    assert connection.handle_for_wid(2) == "w2"
    assert connection.handle_to_wid == {"w1": 1, "w2": 2}


def test_snapshot_payload_returns_v2_handle_shape():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=1,
    )

    payload = mcp_server._snapshot_payload(
        connection,
        [{"wid": 1, "class": "DemoWindow", "objectName": "", "text": "Title", "children": []}],
    )

    assert payload["ok"] is True
    assert payload["root_handle"] == "w1"
    assert payload["widgets"] == [{"handle": "w1", "class": "DemoWindow", "text": "Title"}]
    assert "refs" not in payload
    assert "epoch" not in payload


def test_target_not_found_message_handles_stable_handle():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    message = mcp_server._target_not_found_message(connection, "w9")

    assert "stable handle 'w9'" in message
    assert "Run snapshot, find, or inspect" in message


def test_inspect_target_uses_target_payload(monkeypatch):
    locator = FakeLocator(count=1)

    class HandleConnection:
        def handle_for_wid(self, wid: int | None) -> str | None:
            return f"w{wid}" if wid is not None else None

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state: HandleConnection())
    monkeypatch.setattr(mcp_server, "_resolve_locator", lambda *args, **kwargs: locator)

    result = mcp_server.inspect(target="#amount", include_methods=True, include_properties=True)

    assert result["target"] == "#amount"
    assert result["handle"] == "w101"
    assert result["geometry"] == [11, 22, 130, 28]
    assert result["global_bounding_box"] == [1, 2, 3, 4]
    assert result["methods"][0]["name"] == "setAmount"
    assert result["properties"]["myText"] == "pressme"


def test_session_attach_status_launch_and_close(monkeypatch):
    state = mcp_server.ServerState()
    created: list[FakeQPlaywright] = []

    def fake_factory():
        instance = FakeQPlaywright()
        created.append(instance)
        return instance

    monkeypatch.setattr(mcp_server, "QPlaywright", fake_factory)
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    attached = mcp_server.session(action="attach", port=19877, timeout=5.0)

    assert attached["ok"] is True
    assert attached["action"] == "attach"
    assert attached["session"] == {
        "connected": True,
        "host": "127.0.0.1",
        "port": 19877,
        "launched_executable": None,
    }
    assert attached["active_window"] is None
    assert created[0].connected == ("127.0.0.1", 19877, 5.0)

    status = mcp_server.session(action="status")
    assert status["action"] == "status"
    assert status["session"]["port"] == 19877

    launched = mcp_server.session(action="launch", executable="demo_app.exe", args=["--flag"], port=19878, timeout=6.0)
    assert launched["action"] == "launch"
    assert launched["session"]["launched_executable"] == "demo_app.exe"
    assert created[1].launched == ("demo_app.exe", ["--flag"], "127.0.0.1", 19878, 6.0)

    closed = mcp_server.session(action="close")
    assert closed == {"ok": True, "action": "close", "closed": True}
    assert state.connection is None


def test_session_close_clears_stale_connection(monkeypatch):
    state = mcp_server.ServerState()
    app = FakeApp([])
    app._conn = FakeTransportConn(error=ConnectionError("Agent closed connection"))
    qplaywright = FakeQPlaywright()
    state.connection = mcp_server.ManagedConnection(
        name="default",
        qplaywright=qplaywright,
        app=app,
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    closed = mcp_server.session(action="close")

    assert closed == {"ok": True, "action": "close", "closed": True}
    assert state.connection is None
    assert app.closed is True
    assert qplaywright.closed is True


def test_window_tool_lists_selects_resizes_and_closes(monkeypatch):
    state = mcp_server.ServerState()
    first = FakeWindow(11, "First")
    second = FakeWindow(22, "Second", is_modal=True)
    state.connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([first, second]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    listed = mcp_server.window(action="list")
    selected = mcp_server.window(action="select", wid=22)
    resized = mcp_server.window(action="resize", wid=22, width=800, height=600)
    closed = mcp_server.window(action="close", wid=22)

    assert [window["wid"] for window in listed["windows"]] == [11, 22]
    assert listed["active_window"]["wid"] == 11
    assert listed["windows"][0]["is_active"] is True
    assert listed["windows"][1]["is_modal"] is True
    assert listed["windows"][0]["geometry"] == [None, None, None, None]
    assert selected["active_window"]["wid"] == 22
    assert selected["active_window"]["is_modal"] is True
    assert selected["active_window"]["geometry"] == [None, None, None, None]
    assert "refs_cleared" not in selected
    assert resized["active_window"]["wid"] == 22
    assert "windows" not in resized
    assert first.resized_to is None
    assert second.resized_to == (800, 600)
    assert closed["active_window"]["wid"] == 11
    assert "windows" not in closed
    assert second.closed is True


def test_window_select_requires_explicit_selector(monkeypatch):
    state = mcp_server.ServerState()
    state.connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([FakeWindow(11, "First")]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    with pytest.raises(ValueError, match="exactly one of index, wid, or title"):
        mcp_server.window(action="select")

    with pytest.raises(ValueError, match="exactly one of index, wid, or title"):
        mcp_server.window(action="select", index=0, wid=11)


def test_snapshot_uses_active_window_scope_and_save_to(monkeypatch):
    state = mcp_server.ServerState()
    state.connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([FakeWindow(11, "Main")]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    captured = {}

    def fake_snapshot_result(managed_connection, **kwargs):
        captured["kwargs"] = kwargs
        return _v2_snapshot_payload("Main")

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(mcp_server, "_snapshot_result", fake_snapshot_result)
    monkeypatch.setattr(mcp_server, "_write_text_file", lambda path, content: path)

    result = mcp_server.snapshot(depth=4, topmost_only=True, save_to="snapshot.txt")

    assert captured["kwargs"] == {"target": None, "depth": 4, "topmost_only": True, "include_infrastructure": False}
    assert result["ok"] is True
    assert result["window"]["wid"] == 11
    assert result["topmost_only"] is True
    assert result["warnings"] == [mcp_server._TOPMOST_ONLY_WARNING]
    assert result["save_to"] == "snapshot.txt"


def test_format_widget_snapshot_marks_item_view_owner_for_inspect_items():
    snapshot = mcp_server._format_widget_snapshot(
        [
            {
                "wid": 11,
                "class": "FancyOrdersTable",
                "objectName": "orders_table",
                "itemView": {"kind": "table", "discoverableBy": "inspect_items"},
                "children": [],
            }
        ]
    )

    assert snapshot == "- FancyOrdersTable [item-view=table; use inspect_items]"


def test_snapshot_entry_preserves_item_view_hint():
    entry = mcp_server._snapshot_entry(
        {
            "wid": 11,
            "class": "FancyOrdersTable",
            "itemView": {"kind": "table", "discoverableBy": "inspect_items"},
        },
        "w1",
    )

    assert entry["item_view"] == {"kind": "table", "discoverableBy": "inspect_items"}


def test_inspect_without_target_returns_active_window_tree(monkeypatch):
    state = mcp_server.ServerState()
    state.connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([FakeWindow(11, "Main")]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    captured = {}

    def fake_widget_tree_raw(managed_connection, **kwargs):
        captured["kwargs"] = kwargs
        return [{"wid": 11, "class": "DemoWindow", "children": []}]

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(mcp_server, "_widget_tree_raw", fake_widget_tree_raw)

    result = mcp_server.inspect(depth=6, topmost_only=True)

    assert captured["kwargs"] == {"max_depth": 6, "window_wid": 11, "topmost_only": True}
    assert result == {
        "ok": True,
        "target": None,
        "depth": 6,
        "include_infrastructure": False,
        "tree": [{"wid": 11, "class": "DemoWindow"}],
        "warnings": [mcp_server._TOPMOST_ONLY_WARNING],
    }


def test_filter_infrastructure_nodes_drops_qt_internal_support_widgets():
    nodes = [
        {
            "wid": 1,
            "class": "DemoWindow",
            "objectName": "",
            "children": [
                {
                    "wid": 2,
                    "class": "QWidget",
                    "objectName": "qt_scrollarea_viewport",
                    "children": [],
                },
                {
                    "wid": 3,
                    "class": "QLineEdit",
                    "objectName": "username_input",
                    "children": [],
                },
                {
                    "wid": 4,
                    "class": "QAbstractScrollAreaScrollBarContainer",
                    "objectName": "",
                    "children": [],
                },
            ],
        }
    ]

    filtered = mcp_server._filter_infrastructure_nodes(nodes)

    assert [child["wid"] for child in filtered[0]["children"]] == [3]


def test_filter_infrastructure_nodes_promotes_meaningful_descendants_of_internal_widgets():
    nodes = [
        {
            "wid": 1,
            "class": "DemoWindow",
            "objectName": "",
            "children": [
                {
                    "wid": 2,
                    "class": "QStackedWidget",
                    "objectName": "qt_tabwidget_stackedwidget",
                    "children": [
                        {
                            "wid": 3,
                            "class": "QWidget",
                            "objectName": "tab_login",
                            "children": [
                                {
                                    "wid": 4,
                                    "class": "QLineEdit",
                                    "objectName": "username",
                                    "children": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    filtered = mcp_server._filter_infrastructure_nodes(nodes)

    assert [child["wid"] for child in filtered[0]["children"]] == [3]
    assert filtered[0]["children"][0]["children"][0]["wid"] == 4


def test_inspect_without_target_filters_infrastructure_by_default(monkeypatch):
    state = mcp_server.ServerState()
    state.connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([FakeWindow(11, "Main")]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(
        mcp_server,
        "_widget_tree_raw",
        lambda managed_connection, **kwargs: [
            {
                "wid": 11,
                "class": "DemoWindow",
                "children": [
                    {"wid": 12, "class": "QWidget", "objectName": "qt_scrollarea_viewport", "children": []},
                    {"wid": 13, "class": "QLineEdit", "objectName": "username_input", "children": []},
                ],
            }
        ],
    )

    result = mcp_server.inspect()

    assert [child["wid"] for child in result["tree"][0]["children"]] == [13]


def test_inspect_without_target_can_include_infrastructure(monkeypatch):
    state = mcp_server.ServerState()
    state.connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([FakeWindow(11, "Main")]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(
        mcp_server,
        "_widget_tree_raw",
        lambda managed_connection, **kwargs: [
            {
                "wid": 11,
                "class": "DemoWindow",
                "children": [
                    {"wid": 12, "class": "QWidget", "objectName": "qt_scrollarea_viewport", "children": []},
                    {"wid": 13, "class": "QLineEdit", "objectName": "username_input", "children": []},
                ],
            }
        ],
    )

    result = mcp_server.inspect(include_infrastructure=True)

    assert [child["wid"] for child in result["tree"][0]["children"]] == [12, 13]


def test_snapshot_omits_topmost_warning_for_targeted_snapshot(monkeypatch):
    state = mcp_server.ServerState()
    state.connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([FakeWindow(11, "Main")]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(
        mcp_server,
        "_snapshot_result",
        lambda managed_connection, **kwargs: _v2_snapshot_payload("Target"),
    )

    result = mcp_server.snapshot(target="#amount", topmost_only=True)

    assert "warnings" not in result


def test_inspect_locator_handles_empty_and_present_results():
    empty = mcp_server._inspect_locator(FakeLocator(count=0))
    assert empty == {"exists": False, "count": 0}

    present = mcp_server._inspect_locator(FakeLocator(count=2), property_name="placeholderText")
    assert present["exists"] is True
    assert present["count"] == 2
    assert present["text"] == "Save"
    assert present["value"] == "ready"
    assert present["object_name"] == "amount_editor"
    assert present["accessible_name"] == "Amount editor"
    assert present["geometry"] == [11, 22, 130, 28]
    assert present["global_bounding_box"] == [1, 2, 3, 4]
    assert present["property_value"] == "attr:placeholderText"

    with_methods = mcp_server._inspect_locator(FakeLocator(count=1), include_methods=True, include_properties=True)
    assert with_methods["methods"][0]["name"] == "setAmount"
    assert with_methods["properties"]["myText"] == "pressme"


def test_inspect_locator_omits_empty_text_and_value_for_a11y_only_widget():
    class A11yOnlyLocator(FakeLocator):
        def text_content(self) -> str:
            return ""

        def input_value(self) -> str:
            return ""

        def all_text_contents(self) -> list[str]:
            return []

        def properties(self) -> dict[str, object]:
            return {
                "objectName": "measure_type_btn",
                "accessibleName": "功率扫描",
                "accessibleDescription": "切换测量类型为功率扫描",
            }

    result = mcp_server._inspect_locator(A11yOnlyLocator(count=1))

    assert result["object_name"] == "measure_type_btn"
    assert result["accessible_name"] == "功率扫描"
    assert result["accessible_description"] == "切换测量类型为功率扫描"
    assert "text" not in result
    assert "value" not in result


def test_inspect_locator_wraps_special_attributes():
    class TransparentLocator(FakeLocator):
        def properties(self) -> dict[str, object]:
            return super().properties() | {
                "attributes": {"WA_TransparentForMouseEvents": True},
            }

    result = mcp_server._inspect_locator(TransparentLocator(count=1))

    assert result["attribute"] == {"transparent_for_mouse_events": True}


def test_invoke_locator_method_uses_first_match():
    result = mcp_server._invoke_locator_method(
        FakeLocator(count=1),
        method_name="setAmount",
        args={"value": "88.00"},
    )

    assert result == {
        "method_name": "setAmount",
        "args": {"value": "88.00"},
    }

    with pytest.raises(ValueError, match="No widget found for invoke.*snapshot, find, or inspect"):
        mcp_server._invoke_locator_method(FakeLocator(count=0), method_name="setAmount")


def test_invoke_locator_method_raises_detailed_failure_for_structured_invoke_result():
    locator = FakeLocator(
        count=1,
        invoke_result={
            "ok": False,
            "value": None,
            "errorCode": 2,
            "errorMessage": "Missing required argument: value",
        },
    )

    with pytest.raises(ValueError, match=r"Invoke failed for method 'setAmount' \(errorCode=2\): Missing required argument: value"):
        mcp_server._invoke_locator_method(locator, method_name="setAmount", args={})


def test_wait_can_include_snapshot(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    locator = FakeLocator(count=1)

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state: connection)
    monkeypatch.setattr(mcp_server, "_resolve_widget_handle_locator", lambda *args, **kwargs: locator)
    monkeypatch.setattr(
        mcp_server,
        "_list_windows_raw",
        lambda managed_connection, **kwargs: [{"wid": 11, "title": "Main", "class": "DemoWindow", "geometry": {"x": 5, "y": 7, "width": 640, "height": 720}, "is_modal": False}],
    )
    monkeypatch.setattr(
        mcp_server,
        "_action_result_with_snapshot",
        lambda managed_connection, **payload: payload | _v2_snapshot_payload("DemoWindow"),
    )

    result = mcp_server.wait(target="w7", state="visible", timeout=5.0, include_snapshot=True)

    assert locator.wait_calls == [{"state": "visible", "timeout": 5.0}]
    assert result["ok"] is True
    assert result["target"] == "w7"
    assert result["window_changed"] is False
    assert result["active_window"]["wid"] == 11
    assert result["snapshot"] == "- DemoWindow @w1"
    assert result["root_handle"] == "w1"
    assert result["widgets"] == [{"handle": "w1", "class": "DemoWindow"}]
    assert "refs" not in result


def test_wait_can_use_text_contains_condition(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    locator = FakeLocator(count=1)

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state: connection)
    monkeypatch.setattr(mcp_server, "_resolve_widget_handle_locator", lambda *args, **kwargs: locator)
    monkeypatch.setattr(
        mcp_server,
        "_list_windows_raw",
        lambda managed_connection, **kwargs: [{"wid": 11, "title": "Main", "class": "DemoWindow", "geometry": {"x": 5, "y": 7, "width": 640, "height": 720}, "is_modal": False}],
    )

    result = mcp_server.wait(target="w7", condition="text_contains", expected="ave", timeout=5.0)

    assert locator.wait_calls == []
    assert result["ok"] is True
    assert result["condition"] == "text_contains"
    assert result["expected"] == "ave"
    assert result["window_changed"] is False


def test_wait_rejects_state_and_condition_together(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state: connection)

    with pytest.raises(ValueError, match="mutually exclusive"):
        mcp_server.wait(target="w7", state="visible", condition="text_contains", expected="ok")


def test_wait_condition_requires_expected(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state: connection)

    with pytest.raises(ValueError, match="expected is required"):
        mcp_server.wait(target="w7", condition="text_contains")


def test_finalize_action_result_can_include_compact_state(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    locator = FakeLocator(count=1)

    monkeypatch.setattr(mcp_server, "_resolve_widget_handle_locator", lambda *args, **kwargs: locator)
    monkeypatch.setattr(
        mcp_server,
        "_list_windows_raw",
        lambda managed_connection, **kwargs: [{"wid": 11, "title": "Main", "class": "DemoWindow", "geometry": {"x": 5, "y": 7, "width": 640, "height": 720}, "is_modal": False}],
    )

    result = mcp_server._finalize_action_result(
        connection,
        include_state=True,
        state_target="w1",
        ok=True,
        target="w1",
    )

    assert result["ok"] is True
    assert result["window_changed"] is False
    assert result["active_window"]["wid"] == 11
    assert result["state"] == {
        "exists": True,
        "count": 1,
        "handle": "w1",
        "object_name": "amount_editor",
        "accessible_name": "Amount editor",
        "accessible_description": "输入金额",
        "class": "FancyAmountEdit",
        "geometry": [11, 22, 130, 28],
        "bounding_box": [1, 2, 3, 4],
        "global_bounding_box": [1, 2, 3, 4],
        "visible": True,
        "enabled": False,
        "checked": True,
        "text": "Save",
        "value": "ready",
    }


def test_finalize_action_result_can_include_item_compact_state(monkeypatch):
    window = FakeWindow(11, "Main")
    app = FakeApp([window])
    app._conn = FakeTransportConn(
        responses={
            "item_properties": {
                "kind": "tree_node",
                "text": "Advanced",
                "edit_value": "Advanced Draft",
                "path": ["Settings", "Advanced"],
                "expanded": False,
                "selected": True,
            },
            "item_text": "Advanced",
            "item_visible": True,
            "item_bounding_box": {"x": 10, "y": 20, "width": 30, "height": 12},
        }
    )
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=app,
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    monkeypatch.setattr(
        mcp_server,
        "_list_windows_raw",
        lambda managed_connection, **kwargs: [{"wid": 11, "title": "Main", "class": "DemoWindow", "geometry": {"x": 5, "y": 7, "width": 640, "height": 720}, "is_modal": False}],
    )

    result = mcp_server._finalize_action_result(
        connection,
        include_state=True,
        state_target=_item_target(),
        ok=True,
        target=_item_target(),
    )

    assert result["ok"] is True
    assert result["window_changed"] is False
    assert result["active_window"]["wid"] == 11
    assert result["state"] == {
        "exists": True,
        "count": 1,
        "owner_handle": "w1",
        "kind": "tree_node",
        "path": ["Settings", "Advanced"],
        "bounding_box": [10, 20, 30, 12],
        "global_bounding_box": [10, 20, 30, 12],
        "visible": True,
        "text": "Advanced",
        "edit_value": "Advanced Draft",
        "expanded": False,
        "selected": True,
    }


def test_finalize_action_result_can_include_state_and_snapshot_together(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    locator = FakeLocator(count=1)

    monkeypatch.setattr(mcp_server, "_resolve_widget_handle_locator", lambda *args, **kwargs: locator)
    monkeypatch.setattr(
        mcp_server,
        "_list_windows_raw",
        lambda managed_connection, **kwargs: [{"wid": 11, "title": "Main", "class": "DemoWindow", "geometry": {"x": 5, "y": 7, "width": 640, "height": 720}, "is_modal": False}],
    )
    monkeypatch.setattr(
        mcp_server,
        "_action_result_with_snapshot",
        lambda managed_connection, **payload: payload | _v2_snapshot_payload("DemoWindow"),
    )

    result = mcp_server._finalize_action_result(
        connection,
        include_state=True,
        include_snapshot=True,
        state_target="w1",
        snapshot_target="w1",
        ok=True,
        target="w1",
    )

    assert result["state"]["visible"] is True
    assert result["snapshot"] == "- DemoWindow @w1"
    assert result["root_handle"] == "w1"
    assert result["widgets"] == [{"handle": "w1", "class": "DemoWindow"}]
    assert "refs" not in result


def test_wait_rejects_undocumented_state(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state: connection)

    with pytest.raises(ValueError, match="state must be one of"):
        mcp_server.wait(target="w7", state="attached")


def test_wait_rejects_undocumented_condition(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state: connection)

    with pytest.raises(ValueError, match="condition must be one of"):
        mcp_server.wait(target="w7", condition="text_matches", expected="ok")


def test_choose_ignores_blank_unused_string_values(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    locator = FakeLocator(count=1)

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state: connection)
    monkeypatch.setattr(mcp_server, "_resolve_widget_handle_locator", lambda *args, **kwargs: locator)
    monkeypatch.setattr(
        mcp_server,
        "_list_windows_raw",
        lambda managed_connection, **kwargs: [{"wid": 11, "title": "Main", "class": "DemoWindow", "geometry": {"x": 5, "y": 7, "width": 640, "height": 720}, "is_modal": False}],
    )

    result = mcp_server.choose(target="w3", value="", label="CNY")

    assert locator.action_calls == [("select_option", {"value": None, "index": None, "label": "CNY"})]
    assert result["ok"] is True
    assert result["label"] == "CNY"
    assert result["value"] is None


@pytest.mark.parametrize(
    ("tool_name", "call_kwargs", "expected_calls", "expected_payload"),
    [
        ("click", {"target": "w2", "include_snapshot": True}, [("click", {})], {"target": "w2", "count": 1}),
        ("click", {"target": "w2", "count": 2, "include_snapshot": True}, [("dblclick", {})], {"target": "w2", "count": 2}),
        ("input", {"target": "w3", "text": "123.45", "include_snapshot": True}, [("fill", {"value": "123.45"})], {"target": "w3", "text": "123.45", "mode": "replace", "delay": 0, "submitted": False}),
        ("invoke", {"target": "w3", "method": "setAmount", "args": {"value": "88.00"}, "include_snapshot": True}, [("invoke", {"method_name": "setAmount", "args": {"value": "88.00"}})], {"target": "w3", "method": "setAmount", "args": {"value": "88.00"}}),
        ("input", {"target": "w3", "text": "abc", "mode": "append", "delay": 25, "submit": True, "include_snapshot": True}, [("type", {"text": "abc", "delay": 25}), ("press", {"key": "Enter"})], {"target": "w3", "text": "abc", "mode": "append", "delay": 25, "submitted": True}),
        ("press_key", {"target": "w3", "key": "Enter", "include_snapshot": True}, [("press", {"key": "Enter"})], {"target": "w3", "key": "Enter"}),
        ("set_checked", {"target": "w4", "checked": True, "include_snapshot": True}, [("check", {})], {"target": "w4", "checked": True}),
        ("set_checked", {"target": "w4", "checked": False, "include_snapshot": True}, [("uncheck", {})], {"target": "w4", "checked": False}),
        ("choose", {"target": "w5", "label": "CNY", "include_snapshot": True}, [("select_option", {"value": None, "index": None, "label": "CNY"})], {"target": "w5", "label": "CNY", "value": None, "index": None}),
        ("hover", {"target": "w6", "include_snapshot": True}, [("hover", {})], {"target": "w6"}),
        ("scroll", {"target": "w6", "delta_x": 5, "delta_y": 10, "include_snapshot": True}, [("scroll", {"delta_x": 5, "delta_y": 10})], {"target": "w6", "delta_x": 5, "delta_y": 10}),
    ],
)
def test_native_action_tools_can_include_snapshot(monkeypatch, tool_name, call_kwargs, expected_calls, expected_payload):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    locator = FakeLocator(count=1)

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state: connection)
    monkeypatch.setattr(mcp_server, "_resolve_widget_handle_locator", lambda *args, **kwargs: locator)
    monkeypatch.setattr(
        mcp_server,
        "_list_windows_raw",
        lambda managed_connection, **kwargs: [{"wid": 11, "title": "Main", "class": "DemoWindow", "geometry": {"x": 5, "y": 7, "width": 640, "height": 720}, "is_modal": False}],
    )
    monkeypatch.setattr(
        mcp_server,
        "_action_result_with_snapshot",
        lambda managed_connection, **payload: payload | _v2_snapshot_payload("DemoWindow"),
    )

    result = getattr(mcp_server, tool_name)(**call_kwargs)

    assert locator.action_calls == expected_calls
    assert result["ok"] is True
    assert result["window_changed"] is False
    assert result["active_window"]["wid"] == 11
    for key, value in expected_payload.items():
        assert result[key] == value
    assert result["snapshot"] == "- DemoWindow @w1"
    assert result["root_handle"] == "w1"
    assert result["widgets"] == [{"handle": "w1", "class": "DemoWindow"}]
    assert "refs" not in result


def test_finalize_action_result_switches_active_window_and_uses_window_snapshot(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    captured = {}

    monkeypatch.setattr(
        mcp_server,
        "_list_windows_raw",
        lambda managed_connection, **kwargs: [{"wid": 22, "title": "Dialog", "class": "QDialog", "geometry": {"x": 50, "y": 60, "width": 480, "height": 320}, "is_modal": False}],
    )

    def fake_action_result_with_snapshot(managed_connection, *, target=None, **payload):
        captured["target"] = target
        return payload | _v2_snapshot_payload("QDialog", class_name="QDialog")

    monkeypatch.setattr(mcp_server, "_action_result_with_snapshot", fake_action_result_with_snapshot)

    result = mcp_server._finalize_action_result(
        connection,
        include_snapshot=True,
        snapshot_target="w2",
        ok=True,
        target="w2",
    )

    assert result["window_changed"] is True
    assert result["active_window"]["wid"] == 22
    assert connection.active_window_wid == 22
    assert captured["target"] is None


def test_press_key_without_target_uses_active_window_transport(monkeypatch):
    state = mcp_server.ServerState()
    transport = FakeTransportConn()
    app = FakeApp([FakeWindow(11, "Main")])
    app._conn = transport
    state.connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=app,
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(
        mcp_server,
        "_list_windows_raw",
        lambda managed_connection, **kwargs: [{"wid": 11, "title": "Main", "class": "DemoWindow", "geometry": {"x": 5, "y": 7, "width": 640, "height": 720}, "is_modal": False}],
    )

    result = mcp_server.press_key(key="Enter")

    assert transport.calls[-1] == {"method": "press", "params": {"key": "Enter", "window_wid": 11}, "timeout": 30.0}
    assert result["ok"] is True
    assert result["target"] is None
    assert result["key"] == "Enter"


def test_mcp_tool_input_schema_describes_all_parameters():
    assert mcp_server.mcp is not None

    async def list_tools():
        assert mcp_server.mcp is not None
        return await mcp_server.mcp.list_tools()

    tools = anyio.run(list_tools)
    dumped = [tool.model_dump(mode="json") for tool in tools]

    for tool in dumped:
        properties = tool["inputSchema"].get("properties", {})
        for property_name, schema in properties.items():
            assert schema.get("description"), f"{tool['name']}.{property_name} is missing description"

    click_tool = next(tool for tool in dumped if tool["name"] == "click")
    assert "post-action snapshot" in click_tool["inputSchema"]["properties"]["include_snapshot"]["description"]
    click_schema = click_tool["inputSchema"]
    click_target_any_of = click_schema["properties"]["target"]["anyOf"]
    assert {entry["type"] for entry in click_target_any_of} == {"string", "object"}
    assert click_schema["oneOf"] == [
        {"required": ["target"]},
        {"required": ["x", "y"]},
    ]
    assert click_schema["allOf"] == [
        {"not": {"required": ["target", "x"]}},
        {"not": {"required": ["target", "y"]}},
    ]
    assert "Omit target only when using both x and y" in click_schema["properties"]["target"]["description"]
    assert "Window-relative x coordinate" in click_schema["properties"]["x"]["description"]
    assert "Window-relative y coordinate" in click_schema["properties"]["y"]["description"]

    hover_tool = next(tool for tool in dumped if tool["name"] == "hover")
    hover_schema = hover_tool["inputSchema"]
    hover_target_any_of = hover_schema["properties"]["target"]["anyOf"]
    assert {entry["type"] for entry in hover_target_any_of} == {"string", "object"}
    assert hover_schema["oneOf"] == [
        {"required": ["target"]},
        {"required": ["x", "y"]},
    ]
    assert hover_schema["allOf"] == [
        {"not": {"required": ["target", "x"]}},
        {"not": {"required": ["target", "y"]}},
    ]
    assert "Omit target only when using both x and y" in hover_schema["properties"]["target"]["description"]

    find_tool = next(tool for tool in dumped if tool["name"] == "find")
    assert "class" in find_tool["inputSchema"]["properties"]
    assert "class_" not in find_tool["inputSchema"]["properties"]


def test_find_tool_accepts_class_argument_via_mcp_transport(monkeypatch):
    assert mcp_server.mcp is not None
    tool = cast(Any, mcp_server.mcp._tool_manager.get_tool("find"))
    assert tool is not None

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state: object())
    monkeypatch.setattr(mcp_server, "_find_result", lambda connection_state, **kwargs: kwargs)

    async def run_tool():
        return await tool.run({"class": "QPushButton", "accessible_name": "Submit"})

    result = anyio.run(run_tool)

    assert result["ok"] is True
    assert result["widget_class"] == "QPushButton"
    assert result["accessible_name"] == "Submit"


def test_summarize_windows_uses_geometry_payload():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    summaries = mcp_server._summarize_windows(
        connection,
        [{"wid": 11, "title": "Main", "class": "DemoWindow", "geometry": {"x": 5, "y": 7, "width": 640, "height": 720}, "is_modal": False}],
    )

    assert summaries == [
        {
            "index": 0,
            "wid": 11,
            "title": "Main",
            "class": "DemoWindow",
            "geometry": [5, 7, 640, 720],
            "is_active": True,
            "is_modal": False,
        }
    ]


def test_summarize_windows_prefers_explicit_active_window():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    summaries = mcp_server._summarize_windows(
        connection,
        [
            {
                "wid": 11,
                "title": "Main",
                "class": "DemoWindow",
                "geometry": {"x": 5, "y": 7, "width": 640, "height": 720},
                "is_active": False,
                "is_modal": False,
                "blocked_by_modal": False,
            },
            {
                "wid": 22,
                "title": "Dialog",
                "class": "QDialog",
                "geometry": {"x": 40, "y": 50, "width": 480, "height": 320},
                "is_active": True,
                "is_modal": False,
                "blocked_by_modal": False,
            },
        ],
    )

    assert summaries[0]["is_active"] is False
    assert summaries[1]["is_active"] is True


def test_summarize_windows_prefers_unblocked_modal_window():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    summaries = mcp_server._summarize_windows(
        connection,
        [
            {
                "wid": 11,
                "title": "Main",
                "class": "DemoWindow",
                "geometry": {"x": 5, "y": 7, "width": 640, "height": 720},
                "is_modal": False,
                "blocked_by_modal": True,
            },
            {
                "wid": 22,
                "title": "Payment Review",
                "class": "QDialog",
                "geometry": {"x": 40, "y": 50, "width": 480, "height": 320},
                "is_modal": True,
                "blocked_by_modal": False,
            },
        ],
    )

    assert summaries[0]["is_active"] is False
    assert summaries[1]["is_active"] is True


def test_active_window_summary_prefers_precomputed_active_window():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    active_window = mcp_server._active_window_summary(
        connection,
        windows=[
            {
                "wid": 22,
                "title": "Payment Review",
                "class": "QDialog",
                "geometry": {"x": 40, "y": 50, "width": 480, "height": 320},
                "is_active": True,
                "is_modal": True,
            },
            {
                "wid": 11,
                "title": "Main",
                "class": "DemoWindow",
                "geometry": {"x": 5, "y": 7, "width": 640, "height": 720},
                "is_active": False,
                "is_modal": False,
            },
        ],
    )

    assert active_window == {
        "wid": 22,
        "title": "Payment Review",
        "class": "QDialog",
        "geometry": [40, 50, 480, 320],
        "is_active": True,
        "is_modal": True,
    }


def test_scroll_rejects_zero_delta(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state: connection)

    with pytest.raises(ValueError, match="cannot both be 0"):
        mcp_server.scroll(target="w6")


def test_configure_stdio_for_mcp_reconfigures_utf8_streams(monkeypatch):
    class FakeStream:
        def __init__(self):
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    fake_stdin = FakeStream()
    fake_stdout = FakeStream()
    fake_stderr = FakeStream()

    monkeypatch.setattr(mcp_server.sys, "stdin", fake_stdin)
    monkeypatch.setattr(mcp_server.sys, "stdout", fake_stdout)
    monkeypatch.setattr(mcp_server.sys, "stderr", fake_stderr)

    mcp_server._configure_stdio_for_mcp("stdio")

    assert fake_stdin.calls == [{"encoding": "utf-8", "errors": "strict"}]
    assert fake_stdout.calls == [{"encoding": "utf-8", "errors": "strict"}]
    assert fake_stderr.calls == [{"encoding": "utf-8", "errors": "backslashreplace"}]


def test_configure_stdio_for_mcp_skips_non_stdio(monkeypatch):
    class FakeStream:
        def __init__(self):
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    fake_stdout = FakeStream()
    monkeypatch.setattr(mcp_server.sys, "stdout", fake_stdout)

    mcp_server._configure_stdio_for_mcp("streamable-http")

    assert fake_stdout.calls == []


def test_initialize_active_window_uses_first_visible_window():
    first = FakeWindow(11, "First")
    second = FakeWindow(22, "Second")
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([first, second]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    windows = mcp_server._initialize_active_window(connection)

    assert connection.active_window_wid == 11
    assert windows[0]["wid"] == 11
    assert windows[0]["is_active"] is True


def test_format_widget_snapshot_omits_selector_hints():
    snapshot = mcp_server._format_widget_snapshot(
        [
            {
                "class": "QPushButton",
                "objectName": "login_btn",
                "text": "Login",
                "children": [],
            }
        ],
        depth=3,
    )

    assert snapshot == '- QPushButton "Login"'


def test_format_widget_snapshot_marks_accessibility_derived_labels():
    snapshot = mcp_server._format_widget_snapshot(
        [
            {
                "class": "MenuButton",
                "objectName": "measure_type_btn",
                "accessibleName": "功率扫描",
                "children": [],
            }
        ],
        depth=3,
    )

    assert snapshot == '- MenuButton "功率扫描" [a11y]'


def test_format_widget_snapshot_uses_a11y_label_when_no_object_name():
    snapshot = mcp_server._format_widget_snapshot(
        [
            {
                "class": "ui_toolbar_icon_button_t",
                "accessibleName": "AddTraceButton",
                "children": [],
            }
        ],
        depth=3,
    )

    assert snapshot == '- ui_toolbar_icon_button_t "AddTraceButton" [a11y]'


def test_format_widget_snapshot_marks_mouse_transparent_widgets():
    snapshot = mcp_server._format_widget_snapshot(
        [
            {
                "class": "QWidget",
                "objectName": "overlay_hint",
                "attributes": {"WA_TransparentForMouseEvents": True},
                "children": [],
            }
        ],
        depth=3,
    )

    assert "!transparent" in snapshot


def test_snapshot_entry_wraps_special_attributes():
    entry = mcp_server._snapshot_entry(
        {
            "wid": 11,
            "class": "QWidget",
            "objectName": "overlay_hint",
            "attributes": {"WA_TransparentForMouseEvents": True},
        },
        "w1",
    )

    assert entry["attribute"] == {"transparent_for_mouse_events": True}


def test_snapshot_payload_creates_stable_handles():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=1,
    )

    payload = mcp_server._snapshot_payload(
        connection,
        [
            {
                "wid": 1,
                "class": "DemoWindow",
                "objectName": "",
                "text": "Title",
                "children": [
                    {
                        "wid": 2,
                        "class": "QPushButton",
                        "objectName": "login_btn",
                        "text": "Login",
                        "children": [],
                    }
                ],
            }
        ],
    )

    assert "@w1" in payload["snapshot"]
    assert "@w2" in payload["snapshot"]
    assert connection.handle_to_wid == {"w1": 1, "w2": 2}
    assert payload["widgets"][1]["handle"] == "w2"
    assert payload["widgets"][1]["object_name"] == "login_btn"


def test_snapshot_payload_filters_infrastructure_widgets_by_default():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=1,
    )

    payload = mcp_server._snapshot_payload(
        connection,
        [
            {
                "wid": 1,
                "class": "DemoWindow",
                "objectName": "",
                "text": "Title",
                "children": [
                    {
                        "wid": 2,
                        "class": "QWidget",
                        "objectName": "qt_scrollarea_viewport",
                        "children": [],
                    },
                    {
                        "wid": 3,
                        "class": "QPushButton",
                        "objectName": "login_btn",
                        "text": "Login",
                        "children": [],
                    },
                ],
            }
        ],
    )

    assert "qt_scrollarea_viewport" not in payload["snapshot"]
    assert [entry["handle"] for entry in payload["widgets"]] == ["w1", "w2"]
    assert connection.handle_to_wid == {"w1": 1, "w2": 3}


def test_snapshot_payload_can_include_infrastructure_widgets_when_requested():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=1,
    )

    payload = mcp_server._snapshot_payload(
        connection,
        [
            {
                "wid": 1,
                "class": "DemoWindow",
                "objectName": "",
                "text": "Title",
                "children": [
                    {
                        "wid": 2,
                        "class": "QWidget",
                        "objectName": "qt_scrollarea_viewport",
                        "children": [],
                    }
                ],
            }
        ],
        include_infrastructure=True,
    )

    assert payload["widgets"][1]["object_name"] == "qt_scrollarea_viewport"


def test_snapshot_payload_preserves_existing_handle_bindings():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        wid_to_handle={99: "w9"},
        handle_to_wid={"w9": 99},
        handle_counter=9,
    )

    payload = mcp_server._snapshot_payload(
        connection,
        [
            {
                "wid": 1,
                "class": "DemoWindow",
                "objectName": "",
                "windowTitle": "Title",
                "geometry": {"x": 10, "y": 20, "width": 640, "height": 480},
                "children": [],
            }
        ],
    )

    assert payload["widgets"] == [
        {
            "handle": "w10",
            "class": "DemoWindow",
            "geometry": [10, 20, 640, 480],
            "window_title": "Title",
        }
    ]
    assert connection.handle_to_wid == {"w9": 99, "w10": 1}
    assert connection.wid_to_handle == {99: "w9", 1: "w10"}


def test_snapshot_result_uses_handle_and_passes_depth_for_target_snapshot():
    transport = FakeTransportConn(
        responses={
            mcp_server.METHOD_FIND: {
                "wid": 42,
                "class": "DemoWindow",
                "objectName": "",
                "text": "Dialog",
                "geometry": {"x": 0, "y": 0, "width": 320, "height": 180},
                "children": [
                    {
                        "wid": 43,
                        "class": "QPushButton",
                        "objectName": "confirm_btn",
                        "text": "Confirm",
                        "geometry": {"x": 40, "y": 60, "width": 80, "height": 24},
                        "children": [],
                    }
                ],
            }
        }
    )
    app = FakeApp([])
    app._conn = transport
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=app,
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        wid_to_handle={42: "w9"},
        handle_to_wid={"w9": 42},
        handle_counter=9,
    )

    result = mcp_server._snapshot_result(connection, target="w9", depth=3)

    assert transport.calls == [
        {"method": "find", "params": {"wid": 42, "max_depth": 3}, "timeout": 30.0},
        {"method": "list_windows", "params": None, "timeout": None},
    ]
    assert connection.handle_to_wid == {"w9": 42, "w10": 43}
    assert connection.wid_to_handle == {42: "w9", 43: "w10"}
    assert result["root_handle"] == "w9"
    assert result["widgets"] == [
        {
            "handle": "w9",
            "class": "DemoWindow",
            "geometry": [0, 0, 320, 180],
            "text": "Dialog",
        },
        {
            "handle": "w10",
            "class": "QPushButton",
            "object_name": "confirm_btn",
            "geometry": [40, 60, 80, 24],
            "text": "Confirm",
        },
    ]


def test_snapshot_result_preserves_target_root_when_it_matches_infrastructure():
    transport = FakeTransportConn(
        responses={
            mcp_server.METHOD_FIND: {
                "wid": 42,
                "class": "QWidget",
                "objectName": "qt_scrollarea_viewport",
                "children": [
                    {
                        "wid": 43,
                        "class": "QPushButton",
                        "objectName": "confirm_btn",
                        "text": "Confirm",
                        "children": [],
                    }
                ],
            }
        }
    )
    app = FakeApp([])
    app._conn = transport
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=app,
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        wid_to_handle={42: "w9"},
        handle_to_wid={"w9": 42},
        handle_counter=9,
    )

    result = mcp_server._snapshot_result(connection, target="w9", depth=2)

    assert [entry["handle"] for entry in result["widgets"]] == ["w9", "w10"]


def test_snapshot_payload_deduplicates_repeated_wids_within_one_snapshot():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    payload = mcp_server._snapshot_payload(
        connection,
        [
            {"wid": 1, "class": "DemoWindow", "objectName": "", "text": "Title", "children": []},
            {"wid": 1, "class": "DemoWindow", "objectName": "", "text": "Title", "children": []},
        ],
    )

    assert payload["widgets"] == [{"handle": "w1", "class": "DemoWindow", "text": "Title"}]
    assert payload["snapshot"].count("@w1") == 1


def test_screenshot_returns_schema_fields(monkeypatch):
    state = mcp_server.ServerState()
    window = FakeWindow(11, "Main")
    state.connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([window]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    locator = FakeLocator(count=1)

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(mcp_server, "_resolve_widget_handle_locator", lambda *args, **kwargs: locator)

    result = mcp_server.screenshot(target="w5", path="amount.png")

    assert locator.screenshot_calls == [{"path": "amount.png"}]
    assert result["ok"] is True
    assert result["target"] == "w5"
    assert result["path"] == "amount.png"
    assert result["width"] == 120
    assert result["height"] == 40
    assert result["active_window"]["wid"] == 11
    assert result["active_window"]["title"] == "Main"
    assert result["active_window"]["is_active"] is True


def test_screenshot_without_path_writes_managed_temp_file(monkeypatch, tmp_path):
    state = mcp_server.ServerState()
    window = FakeWindow(11, "Main")
    state.connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([window]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    locator = FakeLocator(count=1)
    image_bytes = b"fake-png-data"

    def fake_screenshot(**kwargs):
        locator.screenshot_calls.append(kwargs)
        return {
            "data": base64.b64encode(image_bytes).decode(),
            "width": 120,
            "height": 40,
        }

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(mcp_server, "_resolve_widget_handle_locator", lambda *args, **kwargs: locator)
    monkeypatch.setattr(mcp_server, "_SCREENSHOT_TEMP_DIR", tmp_path / "qplaywright_screenshots")
    monkeypatch.setattr(locator, "screenshot", fake_screenshot)

    result = mcp_server.screenshot(target="w5")

    assert locator.screenshot_calls == [{}]
    assert result["ok"] is True
    assert result["target"] == "w5"
    assert "data" not in result
    screenshot_path = Path(result["path"])
    assert screenshot_path.exists()
    assert screenshot_path.read_bytes() == image_bytes
    assert result["width"] == 120
    assert result["height"] == 40
    assert result["active_window"]["wid"] == 11


def test_run_cli_invokes_tool_and_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(
        mcp_server,
        "session",
        lambda action="status", port=19876, **_: {"ok": True, "action": action, "port": port},
    )

    exit_code = mcp_server._run_cli(["session", '{"action": "attach", "port": 19877}'])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "action": "attach", "port": 19877}


def test_run_cli_supports_direct_help_meta_command(capsys):
    exit_code = mcp_server._run_cli(["help", "session"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "session.attach: attach to an already running Qt app" in output


def test_run_cli_help_click_uses_mcp_schema(capsys):
    exit_code = mcp_server._run_cli(["help", "click"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Allowed request shapes:" in output
    assert "Window-relative x coordinate in pixels." in output
    assert "Use snapshot, find, or inspect to observe the UI and capture handles first." in output
    assert "screenshot clipping" not in output


def test_run_cli_help_snapshot_mentions_targeted_subtree_capture(capsys):
    exit_code = mcp_server._run_cli(["help", "snapshot"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "inspect one subtree and capture" in output
    assert "frontmost-visible view" in output
    assert "        Use target plus depth" not in output


def test_run_cli_prints_resource_list(monkeypatch, capsys):
    def fake_selector_help():
        """Selector syntax and recommended qplaywright MCP workflow."""

        return "selector docs"

    monkeypatch.setattr(mcp_server, "selector_help", fake_selector_help)

    exit_code = mcp_server._run_cli(["resource"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "resources": [
            {
                "uri": "qplaywright://help/selectors",
                "description": "Selector syntax and recommended qplaywright MCP workflow.",
            }
        ],
    }


def test_run_cli_reads_named_resource(monkeypatch, capsys):
    def fake_selector_help():
        """Selector syntax and recommended qplaywright MCP workflow."""

        return "selector docs"

    monkeypatch.setattr(mcp_server, "selector_help", fake_selector_help)

    exit_code = mcp_server._run_cli(["resource", '{"uri": "qplaywright://help/selectors"}'])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "uri": "qplaywright://help/selectors",
        "content": "selector docs",
    }


def test_run_cli_supports_direct_resources_meta_command(monkeypatch, capsys):
    def fake_selector_help():
        """Selector syntax and recommended qplaywright MCP workflow."""

        return "selector docs"

    monkeypatch.setattr(mcp_server, "selector_help", fake_selector_help)

    exit_code = mcp_server._run_cli(["resources"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Available resources:" in output
    assert "qplaywright://help/selectors" in output


def test_run_cli_typed_resource_read(monkeypatch, capsys):
    def fake_selector_help():
        """Selector syntax and recommended qplaywright MCP workflow."""

        return "selector docs"

    monkeypatch.setattr(mcp_server, "selector_help", fake_selector_help)

    exit_code = mcp_server._run_cli(["resource", "read", "qplaywright://help/selectors"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "uri": "qplaywright://help/selectors",
        "content": "selector docs",
    }


def test_run_cli_typed_session_attach(monkeypatch, capsys):
    monkeypatch.setattr(
        mcp_server,
        "session",
        lambda **kwargs: {"ok": True, **kwargs},
    )

    exit_code = mcp_server._run_cli(["session", "attach", "--port", "19877", "--timeout", "5"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "action": "attach",
        "agent_name": "GitHub Copilot",
        "host": "127.0.0.1",
        "port": 19877,
        "timeout": 5.0,
    }


def test_run_cli_typed_window_select(monkeypatch, capsys):
    monkeypatch.setattr(
        mcp_server,
        "window",
        lambda **kwargs: {"ok": True, **kwargs},
    )

    exit_code = mcp_server._run_cli(["window", "select", "--title", "Dialog"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "action": "select",
        "title": "Dialog",
    }


def test_try_run_typed_cli_from_command_line_keeps_quoted_title(monkeypatch, capsys):
    monkeypatch.setattr(
        mcp_server,
        "window",
        lambda **kwargs: {"ok": True, **kwargs},
    )

    exit_code = mcp_server._try_run_typed_cli_from_command_line('window select --title "Payment Review"')

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "action": "select",
        "title": "Payment Review",
    }


def test_run_cli_typed_snapshot(monkeypatch, capsys):
    monkeypatch.setattr(
        mcp_server,
        "snapshot",
        lambda **kwargs: {"ok": True, **kwargs},
    )

    exit_code = mcp_server._run_cli(["snapshot", "--depth", "4", "--topmost-only", "--save-to", "snapshot.txt"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "depth": 4,
        "include_infrastructure": False,
        "save_to": "snapshot.txt",
        "target": None,
        "topmost_only": True,
    }


def test_run_cli_typed_find(monkeypatch, capsys):
    monkeypatch.setattr(
        mcp_server,
        "find",
        lambda **kwargs: {"ok": True, **kwargs},
    )

    exit_code = mcp_server._run_cli(["find", "--root", "w12", "--role", "button", "--has-text", "submit", "--limit", "3"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "root": "w12",
        "role": "button",
        "has_text": "submit",
        "text": None,
        "class_": None,
        "object_name": None,
        "accessible_name": None,
        "include_infrastructure": False,
        "limit": 3,
    }


def test_run_cli_typed_resolve_object_names(monkeypatch, capsys):
    monkeypatch.setattr(
        mcp_server,
        "resolve_object_names",
        lambda **kwargs: {"ok": True, **kwargs},
    )

    exit_code = mcp_server._run_cli(
        [
            "resolve_object_names",
            "--root",
            "w12",
            "--object-name",
            "username",
            "--object-name",
            "password",
            "--depth",
            "4",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "root": "w12",
        "object_names": ["username", "password"],
        "depth": 4,
        "include_infrastructure": False,
    }


def test_run_cli_typed_inspect_accepts_positional_target(monkeypatch, capsys):
    monkeypatch.setattr(
        mcp_server,
        "inspect",
        lambda **kwargs: {"ok": True, **kwargs},
    )

    exit_code = mcp_server._run_cli(["inspect", "w2", "--include-properties"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "target": "w2",
        "property": None,
        "include_methods": False,
        "include_properties": True,
        "depth": 10,
        "topmost_only": False,
        "include_infrastructure": False,
    }


def test_run_cli_typed_click_and_input(monkeypatch, capsys):
    captured: list[tuple[str, dict[str, object]]] = []

    def fake_click(**kwargs):
        captured.append(("click", kwargs))
        return {"ok": True, **kwargs}

    def fake_input(**kwargs):
        captured.append(("input", kwargs))
        return {"ok": True, **kwargs}

    monkeypatch.setattr(mcp_server, "click", fake_click)
    monkeypatch.setattr(mcp_server, "input", fake_input)

    click_exit_code = mcp_server._run_cli(["click", "w12", "--count", "2", "--include-snapshot"])
    click_payload = json.loads(capsys.readouterr().out)

    input_exit_code = mcp_server._run_cli(["input", "w7", "123.45", "--mode", "append", "--delay", "25", "--submit"])
    input_payload = json.loads(capsys.readouterr().out)

    assert click_exit_code == 0
    assert input_exit_code == 0
    assert click_payload == {
        "ok": True,
        "count": 2,
        "include_state": False,
        "include_snapshot": True,
        "target": "w12",
    }
    assert input_payload == {
        "ok": True,
        "delay": 25,
        "include_state": False,
        "include_snapshot": False,
        "mode": "append",
        "submit": True,
        "target": "w7",
        "text": "123.45",
    }
    assert captured == [
        (
            "click",
            {"target": "w12", "count": 2, "include_state": False, "include_snapshot": True},
        ),
        (
            "input",
            {
                "target": "w7",
                "text": "123.45",
                "mode": "append",
                "delay": 25,
                "submit": True,
                "include_state": False,
                "include_snapshot": False,
            },
        ),
    ]


def test_run_cli_typed_click_supports_include_state(monkeypatch, capsys):
    captured = {}

    def fake_click(**kwargs):
        captured.update(kwargs)
        return {"ok": True, **kwargs}

    monkeypatch.setattr(mcp_server, "click", fake_click)

    exit_code = mcp_server._run_cli(["click", "w12", "--include-state"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "target": "w12",
        "count": 1,
        "include_state": True,
        "include_snapshot": False,
    }
    assert captured == {
        "target": "w12",
        "count": 1,
        "include_state": True,
        "include_snapshot": False,
    }


def test_run_cli_typed_click_accepts_window_coordinates(monkeypatch, capsys):
    captured = {}

    def fake_click(**kwargs):
        captured.update(kwargs)
        return {"ok": True, **kwargs}

    monkeypatch.setattr(mcp_server, "click", fake_click)

    exit_code = mcp_server._run_cli(["click", "--x", "12", "--y", "34"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "target": None,
        "count": 1,
        "x": 12,
        "y": 34,
        "include_state": False,
        "include_snapshot": False,
    }
    assert captured == {
        "target": None,
        "count": 1,
        "x": 12,
        "y": 34,
        "include_state": False,
        "include_snapshot": False,
    }


def test_run_cli_typed_wait_supports_condition(monkeypatch, capsys):
    captured = {}

    def fake_wait(**kwargs):
        captured.update(kwargs)
        return {"ok": True, **kwargs}

    monkeypatch.setattr(mcp_server, "wait", fake_wait)

    exit_code = mcp_server._run_cli(["wait", "w9", "--condition", "checked_equals", "--expected", "true", "--include-state"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "target": "w9",
        "condition": "checked_equals",
        "expected": True,
        "timeout": None,
        "include_state": True,
        "include_snapshot": False,
    }
    assert captured == {
        "target": "w9",
        "condition": "checked_equals",
        "expected": True,
        "timeout": None,
        "include_state": True,
        "include_snapshot": False,
    }


def test_main_cli_dispatches_to_cli_runner(monkeypatch):
    called = {}

    def fake_run_cli(argv):
        called["argv"] = list(argv)
        return 0

    monkeypatch.setattr(mcp_server, "_MCP_VERSION_ERROR", None)
    monkeypatch.setattr(mcp_server, "_run_cli", fake_run_cli)

    with pytest.raises(SystemExit) as exc_info:
        mcp_server.main(["cli", "window", '{"action": "list"}'])

    assert exc_info.value.code == 0
    assert called["argv"] == ["window", '{"action": "list"}']


def test_main_serve_mode_keeps_existing_transport_flow(monkeypatch):
    calls = {}

    def fake_run_transport(transport):
        calls["run_transport"] = transport
        return 0

    monkeypatch.setattr(mcp_server, "_MCP_VERSION_ERROR", None)
    monkeypatch.setattr(mcp_server, "_configure_stdio_for_mcp", lambda transport: calls.setdefault("transport", transport))
    monkeypatch.setattr(mcp_server, "_run_mcp_transport", fake_run_transport)

    with pytest.raises(SystemExit) as exc_info:
        mcp_server.main(["--transport", "streamable-http"])

    assert exc_info.value.code == 0
    assert calls == {"transport": "streamable-http", "run_transport": "streamable-http"}


def test_main_rejects_too_old_mcp_dependency(monkeypatch):
    monkeypatch.setattr(mcp_server, "_MCP_VERSION_ERROR", "mcp is too old")

    with pytest.raises(SystemExit) as exc_info:
        mcp_server.main([])

    assert exc_info.value.code == "mcp is too old"


def test_run_mcp_transport_returns_nonzero_on_unexpected_exception(monkeypatch):
    class FakeMcp:
        def run(self, *, transport):
            raise RuntimeError(f"boom on {transport}")

    monkeypatch.setattr(mcp_server, "mcp", FakeMcp())

    assert mcp_server._run_mcp_transport("stdio") == 1


@pytest.mark.anyio
async def test_patched_mcp_session_receive_loop_ignores_cancelled_notification():
    read_send, read_recv = anyio.create_memory_object_stream(1)
    write_send, _ = anyio.create_memory_object_stream(1)
    incoming_send, incoming_recv = anyio.create_memory_object_stream(1)
    received_notifications = []

    class FakeSession:
        def __init__(self):
            self._read_stream = read_recv
            self._write_stream = write_send
            self._incoming_message_stream_writer = incoming_send
            self._response_streams = {}
            self._receive_request_type = None
            self._receive_notification_type = mcp_server.ClientNotification

        async def _received_request(self, responder):
            raise AssertionError("request branch should not run")

        async def _received_notification(self, notification):
            received_notifications.append(notification)

    await read_send.send(
        mcp_server.JSONRPCMessage(
            mcp_server.JSONRPCNotification(
                jsonrpc="2.0",
                method="notifications/cancelled",
                params={"requestId": 2, "reason": "timeout"},
            )
        )
    )
    await read_send.aclose()

    await mcp_server._patched_mcp_session_receive_loop(FakeSession())

    assert received_notifications == []
    with pytest.raises(anyio.EndOfStream):
        await incoming_recv.receive()


def test_screenshot_clip_kwargs_validates_required_fields():
    assert mcp_server._screenshot_clip_kwargs(x=1, y=2, width=3, height=4) == {
        "x": 1,
        "y": 2,
        "width": 3,
        "height": 4,
    }

    with pytest.raises(ValueError, match="requires x, y, width, and height together"):
        mcp_server._screenshot_clip_kwargs(x=1, y=2, width=3)

    with pytest.raises(ValueError, match="requires non-negative x/y and positive width/height"):
        mcp_server._screenshot_clip_kwargs(x=-1, y=2, width=3, height=4)


def test_target_params_accept_stable_handle():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        wid_to_handle={42: "w2"},
        handle_to_wid={"w2": 42},
    )

    params = mcp_server._target_params(connection, "w2")

    assert params == {"wid": 42}


def test_action_result_with_snapshot_merges_payload(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    monkeypatch.setattr(
        mcp_server,
        "_snapshot_result",
        lambda managed_connection, **kwargs: _v2_snapshot_payload("item"),
    )

    result = mcp_server._action_result_with_snapshot(
        connection,
        target="w1",
        ok=True,
    )

    assert result["ok"] is True
    assert result["snapshot"] == "- item @w1"
    assert result["root_handle"] == "w1"
    assert result["widgets"] == [{"handle": "w1", "class": "DemoWindow"}]
    assert "refs" not in result


def test_widget_tree_raw_includes_optional_window_wid():
    captured = {}

    class FakeConn:
        def send(self, method, params, timeout=None):
            captured["method"] = method
            captured["params"] = params
            return []

    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )
    connection.app._conn = FakeConn()

    mcp_server._widget_tree_raw(connection, max_depth=4, window_wid=12, topmost_only=True)

    assert captured == {"method": mcp_server.METHOD_WIDGET_TREE, "params": {"max_depth": 4, "topmost_only": True, "wid": 12}}


def test_find_widgets_raw_uses_protocol_method_and_root_wid():
    captured = {}

    class FakeConn:
        def send(self, method, params, timeout=None):
            captured["method"] = method
            captured["params"] = params
            captured["timeout"] = timeout
            return {"rootWid": 12, "count": 0, "truncated": False, "results": []}

    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )
    connection.app._conn = FakeConn()

    result = mcp_server._find_widgets_raw(
        connection,
        root_wid=12,
        role="button",
        has_text="Submit",
        widget_class="QPushButton",
        object_name="submit_btn",
        accessible_name="Submit",
        visible=True,
        enabled=True,
        interactable=True,
        include_infrastructure=True,
        limit=7,
    )

    assert result == {"rootWid": 12, "count": 0, "truncated": False, "results": []}
    assert captured == {
        "method": mcp_server.METHOD_FIND_WIDGETS,
        "params": {
            "wid": 12,
            "include_infrastructure": True,
            "limit": 7,
            "role": "button",
            "has_text": "Submit",
            "class": "QPushButton",
            "object_name": "submit_btn",
            "accessible_name": "Submit",
            "visible": True,
            "enabled": True,
            "interactable": True,
        },
        "timeout": 30.0,
    }


def test_find_result_returns_v2_handle_shape():
    transport = FakeTransportConn(
        responses={
            mcp_server.METHOD_FIND_WIDGETS: {
                "rootWid": 11,
                "count": 1,
                "truncated": False,
                "results": [
                    {
                        "wid": 22,
                        "class": "QPushButton",
                        "objectName": "submit_btn",
                        "text": "Submit",
                        "accessibleName": "Submit payment",
                        "currentText": "Ready",
                        "visible": True,
                        "enabled": False,
                        "interactable": False,
                        "geometry": {"x": 310, "y": 412, "width": 96, "height": 28},
                        "matchReason": ["role=button", "has_text~=Submit", "visible=true"],
                        "ancestorSummary": [
                            {"wid": 11, "class": "QGroupBox", "text": "Payment"},
                        ],
                    }
                ],
            }
        }
    )
    app = FakeApp([])
    app._conn = transport
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=app,
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        wid_to_handle={11: "w1"},
        handle_to_wid={"w1": 11},
        handle_counter=1,
    )

    result = mcp_server._find_result(connection, root="w1", role="button", has_text="Submit", visible=True, limit=5)

    assert transport.calls == [
        {
            "method": "find_widgets",
            "params": {"wid": 11, "include_infrastructure": False, "limit": 5, "role": "button", "has_text": "Submit", "visible": True},
            "timeout": 30.0,
        }
    ]
    assert result == {
        "root_handle": "w1",
        "count": 1,
        "truncated": False,
        "results": [
            {
                "handle": "w2",
                "class": "QPushButton",
                "object_name": "submit_btn",
                "text": "Submit",
                "accessible_name": "Submit payment",
                "current_text": "Ready",
                "visible": True,
                "enabled": False,
                "interactable": False,
                "geometry": [310, 412, 96, 28],
                "match_reason": ["role=button", "has_text~=Submit", "visible=true"],
                "ancestor_summary": [
                    {"handle": "w1", "class": "QGroupBox", "label": "Payment"},
                ],
            }
        ],
    }


def test_find_tool_returns_ok_payload(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([FakeWindow(11, "Main")]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", mcp_server.ServerState(connection=connection))
    monkeypatch.setattr(
        mcp_server,
        "_find_result",
        lambda managed_connection, **kwargs: {
            "root_handle": "w1",
            "count": 1,
            "truncated": False,
            "results": [{"handle": "w2", "class": "QPushButton", "text": "Submit"}],
        },
    )

    result = mcp_server.find(root="#payment_panel", role="button", has_text="Submit", limit=3)

    assert result == {
        "ok": True,
        "root_handle": "w1",
        "count": 1,
        "truncated": False,
        "results": [{"handle": "w2", "class": "QPushButton", "text": "Submit"}],
    }


def test_resolve_object_names_result_maps_handles_and_reports_missing_and_ambiguous(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([FakeWindow(11, "Main")]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
        wid_to_handle={11: "w1"},
        handle_to_wid={"w1": 11},
        handle_counter=1,
    )
    captured = {}

    def fake_widget_tree_raw(managed_connection, **kwargs):
        captured["connection"] = managed_connection
        captured["kwargs"] = kwargs
        return [
            {
                "wid": 11,
                "class": "QWidget",
                "objectName": "payment_panel",
                "children": [
                    {"wid": 22, "class": "QLineEdit", "objectName": "username", "text": "alice"},
                    {
                        "wid": 30,
                        "class": "QStackedWidget",
                        "objectName": "qt_tabwidget_stackedwidget",
                        "children": [
                            {"wid": 33, "class": "QLineEdit", "objectName": "password"},
                        ],
                    },
                    {"wid": 40, "class": "QPushButton", "objectName": "dup", "text": "First"},
                    {"wid": 41, "class": "QPushButton", "objectName": "dup", "text": "Second"},
                ],
            }
        ]

    monkeypatch.setattr(mcp_server, "_widget_tree_raw", fake_widget_tree_raw)

    result = mcp_server._resolve_object_names_result(
        connection,
        root="w1",
        object_names=["username", "password", "missing", "dup", "username"],
        depth=4,
    )

    assert captured == {
        "connection": connection,
        "kwargs": {
            "max_depth": 4,
            "window_wid": 11,
            "topmost_only": False,
            "timeout": None,
        },
    }
    assert result == {
        "root_handle": "w1",
        "requested": ["username", "password", "missing", "dup"],
        "handles": {
            "username": "w2",
            "password": "w3",
        },
        "resolved": {
            "username": {
                "handle": "w2",
                "class": "QLineEdit",
                "object_name": "username",
                "text": "alice",
            },
            "password": {
                "handle": "w3",
                "class": "QLineEdit",
                "object_name": "password",
            },
        },
        "missing": ["missing"],
        "ambiguous": {
            "dup": [
                {
                    "handle": "w4",
                    "class": "QPushButton",
                    "object_name": "dup",
                    "text": "First",
                },
                {
                    "handle": "w5",
                    "class": "QPushButton",
                    "object_name": "dup",
                    "text": "Second",
                },
            ],
        },
    }


def test_resolve_object_names_tool_returns_ok_payload(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([FakeWindow(11, "Main")]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", mcp_server.ServerState(connection=connection))
    monkeypatch.setattr(
        mcp_server,
        "_resolve_object_names_result",
        lambda managed_connection, **kwargs: {
            "root_handle": "w1",
            "requested": ["username", "password"],
            "handles": {"username": "w2", "password": "w3"},
            "resolved": {
                "username": {"handle": "w2", "class": "QLineEdit", "object_name": "username"},
                "password": {"handle": "w3", "class": "QLineEdit", "object_name": "password"},
            },
            "missing": [],
            "ambiguous": {},
        },
    )

    result = mcp_server.resolve_object_names(root="#payment_panel", object_names=["username", "password"], depth=5)

    assert result == {
        "ok": True,
        "root_handle": "w1",
        "requested": ["username", "password"],
        "handles": {"username": "w2", "password": "w3"},
        "resolved": {
            "username": {"handle": "w2", "class": "QLineEdit", "object_name": "username"},
            "password": {"handle": "w3", "class": "QLineEdit", "object_name": "password"},
        },
        "missing": [],
        "ambiguous": {},
    }


def test_snapshot_result_scopes_to_active_window(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([FakeWindow(11, "Main"), FakeWindow(22, "Dialog")]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=22,
    )
    captured = {}

    def fake_widget_tree_raw(managed_connection, **kwargs):
        captured["kwargs"] = kwargs
        return [{"wid": 22, "class": "DialogWindow", "objectName": "", "text": "Dialog", "children": []}]

    monkeypatch.setattr(mcp_server, "_widget_tree_raw", fake_widget_tree_raw)

    payload = mcp_server._snapshot_result(connection, depth=3, topmost_only=True)

    assert captured["kwargs"] == {"max_depth": 3, "window_wid": 22, "topmost_only": True, "timeout": None}
    assert 'DialogWindow "Dialog"' in payload["snapshot"]
    assert payload["root_handle"] == "w1"
    assert payload["widgets"][0]["handle"] == "w1"


def test_snapshot_window_payload_preserves_active_window_geometry_array(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    monkeypatch.setattr(
        mcp_server,
        "_active_window_summary",
        lambda managed_connection: {
            "wid": 11,
            "title": "Main",
            "class": "DemoWindow",
            "geometry": [510, 139, 900, 720],
            "is_active": True,
            "is_modal": False,
        },
    )

    payload = mcp_server._snapshot_window_payload(connection)

    assert payload == {
        "handle": "w1",
        "title": "Main",
        "class": "DemoWindow",
        "geometry": [510, 139, 900, 720],
    }


def test_target_not_found_message_suggests_discovery_for_missing_handle():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    message = mcp_server._target_not_found_message(connection, "w9")

    assert "stable handle 'w9'" in message
    assert "Run snapshot, find, or inspect" in message


def test_target_not_found_message_includes_selector_examples():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    message = mcp_server._target_not_found_message(connection, "#missing_btn")

    assert "No widget found for target '#missing_btn'" in message
    assert "Run snapshot, find, or inspect" in message
    assert "prefer a returned stable handle" in message
    assert "#objectName, role=button, text=Submit, has-text=partial, a11y-name=Submit, .QLabel" in message


def test_selector_help_text_prefers_handles_for_repeatable_actions():
    text = mcp_server._selector_help_text()

    assert "observe the UI and capture stable handles for repeatable actions" in text
    assert "use snapshot with target+depth when you want one subtree and several child handles" in text
    assert '{"owner": "w12", "item": {"kind": "table_cell", "row": 3, "column": 1}}' in text
    assert "invoke with those handles" in text


def test_cli_tool_help_includes_action_level_session_and_window_guidance():
    session_help = mcp_server._cli_tool_help("session", mcp_server.session)
    window_help = mcp_server._cli_tool_help("window", mcp_server.window)

    assert "session.attach: attach to an already running Qt app" in session_help
    assert "session.status: report current session and active window" in session_help
    assert "window.select: switch active window" in window_help
    assert "window.close: close one window or the active window" in window_help
