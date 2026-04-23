from __future__ import annotations

import json

import pytest

import qplaywright.mcp_server as mcp_server


class FakeQPlaywright:
    def __init__(self):
        self.closed = False
        self.connected = None
        self.launched = None

    def connect(self, *, host: str, port: int, timeout: float):
        self.connected = (host, port, timeout)
        return FakeApp([])

    def launch(self, executable, *args, host: str, port: int, timeout: float):
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
        return self.responses.get(method, {"ok": True})


class FakeWindow:
    def __init__(self, wid: int, title: str):
        self.wid = wid
        self._title = title
        self.closed = False
        self.resized_to = None

    def title(self) -> str:
        return self._title

    def resize(self, width: int, height: int) -> None:
        self.resized_to = (width, height)

    def close(self) -> None:
        self.closed = True


class FakeLocator:
    def __init__(self, *, count: int, invoke_result=None):
        self._count = count
        self._invoke_result = invoke_result
        self.action_calls = []
        self.wait_calls = []

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
        connections={
            "default": mcp_server.ManagedConnection(
                name="default",
                qplaywright=existing_qplaywright,
                app=existing_app,
                host="127.0.0.1",
                port=19876,
                timeout=30.0,
            )
        }
    )

    result = mcp_server.connect_connection(state, name="default", host="127.0.0.1", port=19877, timeout=5.0)

    assert result["replaced"] is True
    assert state.connections["default"].port == 19877
    assert existing_qplaywright.closed is True
    assert existing_app.closed is True
    assert created[0].connected == ("127.0.0.1", 19877, 5.0)


def test_legacy_connect_and_launch_preserve_response_shape(monkeypatch):
    state = mcp_server.ServerState()
    created: list[FakeQPlaywright] = []

    def fake_factory():
        instance = FakeQPlaywright()
        created.append(instance)
        return instance

    monkeypatch.setattr(mcp_server, "QPlaywright", fake_factory)
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    connected = mcp_server.connect(name="demo", port=19877, timeout=5.0)
    launched = mcp_server.launch("demo_app.exe", args=["--flag"], name="demo2", port=19878, timeout=6.0)

    assert connected == {
        "connection": "demo",
        "host": "127.0.0.1",
        "port": 19877,
        "timeout": 5.0,
        "replaced": False,
        "current_window_wid": None,
        "windows": [],
    }
    assert launched == {
        "connection": "demo2",
        "host": "127.0.0.1",
        "port": 19878,
        "timeout": 6.0,
        "replaced": False,
        "launched_executable": "demo_app.exe",
        "current_window_wid": None,
        "windows": [],
    }
    assert created[0].connected == ("127.0.0.1", 19877, 5.0)
    assert created[1].launched == ("demo_app.exe", ["--flag"], "127.0.0.1", 19878, 6.0)


def test_get_connection_removes_stale_connection_from_state():
    app = FakeApp([])
    app._conn = FakeTransportConn(error=ConnectionError("Agent closed connection"))
    qplaywright = FakeQPlaywright()
    state = mcp_server.ServerState(
        connections={
            "default": mcp_server.ManagedConnection(
                name="default",
                qplaywright=qplaywright,
                app=app,
                host="127.0.0.1",
                port=19876,
                timeout=30.0,
            )
        }
    )

    with pytest.raises(ConnectionError, match="Call connect again to establish a fresh session"):
        mcp_server._get_connection(state, "default")

    assert "default" not in state.connections
    assert app.closed is True
    assert qplaywright.closed is True


def test_list_connections_reports_dead_connection_without_raising():
    live_app = FakeApp([FakeWindow(1, "Main")])
    live_app._conn = FakeTransportConn(
        responses={
            mcp_server.METHOD_LIST_WINDOWS: [
                {"wid": 1, "title": "Main", "class": "", "width": None, "height": None, "index": 0}
            ]
        }
    )
    dead_app = FakeApp([FakeWindow(2, "Restarted")])
    dead_app._conn = FakeTransportConn(error=ConnectionError("Agent closed connection"))

    state = mcp_server.ServerState(
        connections={
            "alive": mcp_server.ManagedConnection(
                name="alive",
                qplaywright=FakeQPlaywright(),
                app=live_app,
                host="127.0.0.1",
                port=19876,
                timeout=30.0,
            ),
            "dead": mcp_server.ManagedConnection(
                name="dead",
                qplaywright=FakeQPlaywright(),
                app=dead_app,
                host="127.0.0.1",
                port=19877,
                timeout=30.0,
            ),
        }
    )

    result = {entry["connection"]: entry for entry in mcp_server.list_connections(state)}

    assert result["alive"]["alive"] is True
    assert result["alive"]["window_count"] == 1
    assert result["alive"]["error"] is None
    assert result["dead"]["alive"] is False
    assert result["dead"]["window_count"] is None
    assert "Call connect again to establish a fresh session" in result["dead"]["error"]


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


def test_resolve_locator_accepts_snapshot_ref_as_widget_id():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        snapshot_refs={"e2": 42},
    )
    connection.app._conn = FakeTransportConn()

    locator = mcp_server._resolve_locator(connection, target="e2")
    locator.click()

    assert connection.app._conn.calls == [
        {"method": mcp_server.METHOD_CLICK, "params": {"wid": 42}, "timeout": 30.0}
    ]


def test_resolve_locator_rejects_missing_snapshot_ref_with_refresh_hint():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        snapshot_refs={"e1": 41},
    )

    with pytest.raises(ValueError, match="Snapshot ref 'e9' is not available"):
        mcp_server._resolve_locator(connection, target="e9")


def test_inspect_widget_uses_target_payload(monkeypatch):
    locator = FakeLocator(count=1)

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state, name: object())
    monkeypatch.setattr(mcp_server, "_resolve_locator", lambda *args, **kwargs: locator)

    result = mcp_server.inspect_widget(target="#amount", connection="demo", include_methods=True)

    assert result["target"] == "#amount"
    assert result["include_methods"] is True
    assert result["methods"][0]["name"] == "setAmount"


def test_session_attach_status_and_close(monkeypatch):
    state = mcp_server.ServerState()
    created: list[FakeQPlaywright] = []

    def fake_factory():
        instance = FakeQPlaywright()
        created.append(instance)
        return instance

    monkeypatch.setattr(mcp_server, "QPlaywright", fake_factory)
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    attached = mcp_server.session(action="attach", connection="demo", port=19877, timeout=5.0)

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

    status = mcp_server.session(action="status", connection="demo")

    assert status["ok"] is True
    assert status["action"] == "status"
    assert status["session"]["port"] == 19877

    closed = mcp_server.session(action="close", connection="demo")

    assert closed == {"ok": True, "action": "close", "closed": True}
    assert state.connections == {}


def test_legacy_disconnect_preserves_launched_executable(monkeypatch):
    state = mcp_server.ServerState(
        connections={
            "demo": mcp_server.ManagedConnection(
                name="demo",
                qplaywright=FakeQPlaywright(),
                app=FakeApp([]),
                host="127.0.0.1",
                port=19876,
                timeout=30.0,
                launched_executable="demo_app.exe",
            )
        }
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    result = mcp_server.disconnect("demo")

    assert result == {
        "connection": "demo",
        "closed": True,
        "launched_executable": "demo_app.exe",
    }


def test_window_tool_selects_and_closes_windows(monkeypatch):
    state = mcp_server.ServerState()
    first = FakeWindow(11, "First")
    second = FakeWindow(22, "Second")
    state.connections["demo"] = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([first, second]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    selected = mcp_server.window(action="select", connection="demo", wid=22)

    assert selected["ok"] is True
    assert selected["action"] == "select"
    assert selected["active_window"]["wid"] == 22
    assert selected["refs_cleared"] is True

    closed = mcp_server.window(action="close", connection="demo", wid=22)

    assert closed["ok"] is True
    assert closed["action"] == "close"
    assert closed["active_window"]["wid"] == 11


def test_legacy_window_tools_wrap_window_actions(monkeypatch):
    state = mcp_server.ServerState()
    first = FakeWindow(11, "First")
    second = FakeWindow(22, "Second")
    state.connections["demo"] = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([first, second]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=22,
    )
    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)

    windows = mcp_server.list_windows(connection="demo")
    resized = mcp_server.resize_window(width=800, height=600, connection="demo", window_wid=11)
    closed = mcp_server.close_window(connection="demo", window_wid=22)

    assert [window["wid"] for window in windows] == [11, 22]
    assert resized == {"ok": True, "width": 800, "height": 600, "connection": "demo"}
    assert first.resized_to == (800, 600)
    assert closed == {"ok": True, "connection": "demo", "window_wid": 22}
    assert second.closed is True
    assert state.connections["demo"].active_window_wid == 11


def test_snapshot_uses_active_window_scope_and_save_to(monkeypatch):
    state = mcp_server.ServerState()
    state.connections["demo"] = mcp_server.ManagedConnection(
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
        return {"snapshot": "- Main [ref=e1]", "refs": [{"ref": "e1"}]}

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(mcp_server, "_compat_snapshot_result", fake_snapshot_result)
    monkeypatch.setattr(mcp_server, "_write_text_file", lambda path, content: path)

    result = mcp_server.snapshot(connection="demo", depth=4, save_to="snapshot.txt")

    assert captured["kwargs"] == {"snapshot_target": None, "depth": 4, "window_wid": 11}
    assert result["ok"] is True
    assert result["window"]["wid"] == 11
    assert result["save_to"] == "snapshot.txt"


def test_inspect_without_target_returns_active_window_tree(monkeypatch):
    state = mcp_server.ServerState()
    state.connections["demo"] = mcp_server.ManagedConnection(
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

    result = mcp_server.inspect(connection="demo", depth=6)

    assert captured["kwargs"] == {"max_depth": 6, "window_wid": 11}
    assert result == {
        "ok": True,
        "target": None,
        "depth": 6,
        "tree": [{"wid": 11, "class": "DemoWindow", "children": []}],
    }


def test_inspect_locator_handles_empty_and_present_results():
    empty = mcp_server._inspect_locator(FakeLocator(count=0))
    assert empty == {"exists": False, "count": 0}

    present = mcp_server._inspect_locator(FakeLocator(count=2), property_name="placeholderText")
    assert present["exists"] is True
    assert present["count"] == 2
    assert present["text"] == "Save"
    assert present["value"] == "ready"
    assert present["property_value"] == "attr:placeholderText"

    with_methods = mcp_server._inspect_locator(FakeLocator(count=1), include_methods=True)
    assert with_methods["methods"][0]["name"] == "setAmount"


def test_locator_methods_returns_first_match_methods():
    methods = mcp_server._locator_methods(FakeLocator(count=1))

    assert methods[0]["args"][0]["name"] == "value"
    assert methods[0]["returnType"] == "QVariant"

    with pytest.raises(ValueError, match="No widget found for method introspection"):
        mcp_server._locator_methods(FakeLocator(count=0))


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

    with pytest.raises(ValueError, match="No widget found for invoke.*#objectName"):
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

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state, name: connection)
    monkeypatch.setattr(mcp_server, "_resolve_locator", lambda *args, **kwargs: locator)
    monkeypatch.setattr(
        mcp_server,
        "_window_summary",
        lambda managed_connection: [{"wid": 11, "title": "Main", "class": "DemoWindow", "index": 0, "width": 640, "height": 720}],
    )
    monkeypatch.setattr(
        mcp_server,
        "_action_result_with_snapshot",
        lambda managed_connection, **payload: payload | {"snapshot": "- DemoWindow [ref=e1]", "refs": [{"ref": "e1"}]},
    )

    result = mcp_server.wait(
        target="#status_label",
        connection="demo",
        state="visible",
        timeout=5.0,
        include_snapshot=True,
    )

    assert locator.wait_calls == [{"state": "visible", "timeout": 5.0}]
    assert result["ok"] is True
    assert result["target"] == "#status_label"
    assert result["window_changed"] is False
    assert result["active_window"]["wid"] == 11
    assert result["snapshot"] == "- DemoWindow [ref=e1]"
    assert result["refs"] == [{"ref": "e1"}]


def test_browser_wait_for_time_can_include_snapshot(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
    )

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state, name: connection)
    monkeypatch.setattr(
        mcp_server,
        "_action_result_with_snapshot",
        lambda managed_connection, **payload: payload | {"snapshot": "- DemoWindow [ref=e1]", "refs": [{"ref": "e1"}]},
    )

    result = mcp_server.browser_wait_for(connection="demo", time=0, include_snapshot=True)

    assert result["ok"] is True
    assert result["waited"] == 0
    assert result["snapshot"] == "- DemoWindow [ref=e1]"
    assert result["refs"] == [{"ref": "e1"}]


@pytest.mark.parametrize(
    ("tool_name", "call_kwargs", "expected_calls", "expected_payload"),
    [
        ("click", {"target": "#submit", "include_snapshot": True}, [("click", {})], {"target": "#submit", "count": 1}),
        (
            "click",
            {"target": "#submit", "count": 2, "include_snapshot": True},
            [("dblclick", {})],
            {"target": "#submit", "count": 2},
        ),
        (
            "input",
            {"target": "#amount", "text": "123.45", "include_snapshot": True},
            [("fill", {"value": "123.45"})],
            {"target": "#amount", "text": "123.45", "mode": "replace", "delay": 0, "submitted": False},
        ),
        (
            "invoke",
            {"target": "#amount", "method": "setAmount", "args": {"value": "88.00"}, "include_snapshot": True},
            [("invoke", {"method_name": "setAmount", "args": {"value": "88.00"}})],
            {"target": "#amount", "method": "setAmount", "args": {"value": "88.00"}},
        ),
        (
            "input",
            {"target": "#amount", "text": "abc", "mode": "append", "delay": 25, "submit": True, "include_snapshot": True},
            [("type", {"text": "abc", "delay": 25}), ("press", {"key": "Enter"})],
            {"target": "#amount", "text": "abc", "mode": "append", "delay": 25, "submitted": True},
        ),
        (
            "press_key",
            {"target": "#amount", "key": "Enter", "include_snapshot": True},
            [("press", {"key": "Enter"})],
            {"target": "#amount", "key": "Enter"},
        ),
        (
            "set_checked",
            {"target": "#remember", "checked": True, "include_snapshot": True},
            [("check", {})],
            {"target": "#remember", "checked": True},
        ),
        (
            "set_checked",
            {"target": "#remember", "checked": False, "include_snapshot": True},
            [("uncheck", {})],
            {"target": "#remember", "checked": False},
        ),
        (
            "choose",
            {"target": "#currency", "label": "CNY", "include_snapshot": True},
            [("select_option", {"value": None, "index": None, "label": "CNY"})],
            {"target": "#currency", "label": "CNY", "value": None, "index": None},
        ),
        (
            "hover",
            {"target": "#item", "include_snapshot": True},
            [("hover", {})],
            {"target": "#item"},
        ),
        (
            "scroll",
            {"target": "#item", "delta_x": 5, "delta_y": 10, "include_snapshot": True},
            [("scroll", {"delta_x": 5, "delta_y": 10})],
            {"target": "#item", "delta_x": 5, "delta_y": 10},
        ),
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

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state, name: connection)
    monkeypatch.setattr(mcp_server, "_resolve_locator", lambda *args, **kwargs: locator)
    monkeypatch.setattr(
        mcp_server,
        "_window_summary",
        lambda managed_connection: [{"wid": 11, "title": "Main", "class": "DemoWindow", "index": 0, "width": 640, "height": 720}],
    )
    monkeypatch.setattr(
        mcp_server,
        "_action_result_with_snapshot",
        lambda managed_connection, **payload: payload | {"snapshot": "- DemoWindow [ref=e1]", "refs": [{"ref": "e1"}]},
    )

    result = getattr(mcp_server, tool_name)(connection="demo", **call_kwargs)

    assert locator.action_calls == expected_calls
    assert result["ok"] is True
    assert result["window_changed"] is False
    assert result["active_window"]["wid"] == 11
    for key, value in expected_payload.items():
        assert result[key] == value
    assert result["snapshot"] == "- DemoWindow [ref=e1]"
    assert result["refs"] == [{"ref": "e1"}]


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
        "_window_summary",
        lambda managed_connection: [{"wid": 22, "title": "Dialog", "class": "QDialog", "index": 0, "width": 480, "height": 320}],
    )

    def fake_action_result_with_snapshot(managed_connection, *, snapshot_target=None, **payload):
        captured["snapshot_target"] = snapshot_target
        return payload | {"snapshot": "- QDialog [ref=e1]", "refs": [{"ref": "e1"}]}

    monkeypatch.setattr(mcp_server, "_action_result_with_snapshot", fake_action_result_with_snapshot)

    result = mcp_server._finalize_action_result(
        connection,
        include_snapshot=True,
        snapshot_target="#submit",
        ok=True,
        target="#submit",
    )

    assert result["window_changed"] is True
    assert result["active_window"]["wid"] == 22
    assert connection.active_window_wid == 22
    assert captured["snapshot_target"] is None


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


def test_initialize_active_window_uses_first_visible_window(monkeypatch):
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


def test_browser_tabs_markdown_marks_current_window():
    first = FakeWindow(11, "First")
    second = FakeWindow(22, "Second")
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([first, second]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=22,
    )

    listing = mcp_server._browser_tabs_markdown(connection)

    assert "- 0: [First](qt://window/11)" in listing
    assert "- 1: (current) [Second](qt://window/22)" in listing


def test_format_widget_snapshot_includes_selector_hints():
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

    assert 'QPushButton "Login" target=#login_btn' in snapshot


def test_snapshot_payload_creates_stable_refs():
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

    assert "[ref=e1]" in payload["snapshot"]
    assert "[ref=e2]" in payload["snapshot"]
    assert connection.snapshot_refs == {"e1": 1, "e2": 2}
    assert payload["refs"][1]["target"] == "#login_btn"

    second_payload = mcp_server._snapshot_payload(
        connection,
        [
            {
                "wid": 3,
                "class": "QComboBoxPrivateContainer",
                "objectName": "",
                "text": "",
                "children": [],
            },
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
            },
        ],
    )

    refs_by_wid = {entry["wid"]: entry["ref"] for entry in second_payload["refs"]}
    assert refs_by_wid[1] == "e1"
    assert refs_by_wid[2] == "e2"
    assert refs_by_wid[3] == "e3"


def test_snapshot_payload_preserves_existing_ref_bindings():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        snapshot_refs={"e1": 99},
        snapshot_wids={99: "e1"},
    )

    payload = mcp_server._snapshot_payload(
        connection,
        [{"wid": 1, "class": "DemoWindow", "objectName": "", "text": "Title", "children": []}],
    )

    assert payload["refs"] == [{"ref": "e2", "wid": 1, "target": ".DemoWindow", "class": "DemoWindow", "text": "Title"}]
    assert connection.snapshot_refs == {"e1": 99, "e2": 1}
    assert connection.snapshot_wids == {99: "e1", 1: "e2"}


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

    assert payload["refs"] == [{"ref": "e1", "wid": 1, "target": ".DemoWindow", "class": "DemoWindow", "text": "Title"}]
    assert payload["snapshot"].count("[ref=e1]") == 1


def test_run_cli_invokes_tool_and_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(
        mcp_server,
        "connect",
        lambda name="default", port=19876, **_: {"ok": True, "name": name, "port": port},
    )

    exit_code = mcp_server._run_cli(["connect", '{"name": "probe", "port": 19877}'])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "name": "probe", "port": 19877}


def test_main_cli_dispatches_to_cli_runner(monkeypatch):
    called = {}

    def fake_run_cli(argv):
        called["argv"] = list(argv)
        return 0

    monkeypatch.setattr(mcp_server, "_run_cli", fake_run_cli)

    with pytest.raises(SystemExit) as exc_info:
        mcp_server.main(["cli", "list_windows", '{"connection": "probe"}'])

    assert exc_info.value.code == 0
    assert called["argv"] == ["list_windows", '{"connection": "probe"}']


def test_main_serve_mode_keeps_existing_transport_flow(monkeypatch):
    calls = {}

    monkeypatch.setattr(mcp_server, "_configure_stdio_for_mcp", lambda transport: calls.setdefault("transport", transport))
    monkeypatch.setattr(mcp_server.mcp, "run", lambda *, transport: calls.setdefault("run_transport", transport))

    mcp_server.main(["--transport", "streamable-http"])

    assert calls == {"transport": "streamable-http", "run_transport": "streamable-http"}


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


def test_browser_target_params_accept_snapshot_ref():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        snapshot_refs={"e2": 42},
    )

    params = mcp_server._browser_target_params(connection, "e2")

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
        "_compat_snapshot_result",
        lambda managed_connection, **kwargs: {"snapshot": "- item [ref=e1]", "refs": [{"ref": "e1"}]},
    )

    result = mcp_server._action_result_with_snapshot(
        connection,
        snapshot_target="e1",
        ok=True,
        connection="demo",
    )

    assert result["ok"] is True
    assert result["connection"] == "demo"
    assert result["snapshot"] == "- item [ref=e1]"
    assert result["refs"] == [{"ref": "e1"}]


def test_widget_tree_raw_includes_optional_window_wid(monkeypatch):
    captured = {}

    class FakeConn:
        def send(self, method, params):
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

    mcp_server._widget_tree_raw(connection, max_depth=4, window_wid=12)

    assert captured == {"method": mcp_server.METHOD_WIDGET_TREE, "params": {"max_depth": 4, "wid": 12}}


def test_compat_snapshot_result_scopes_to_explicit_window(monkeypatch):
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([FakeWindow(11, "Main"), FakeWindow(22, "Dialog")]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        active_window_wid=11,
    )

    monkeypatch.setattr(
        mcp_server,
        "_widget_tree_raw",
        lambda managed_connection, **kwargs: [{"wid": kwargs.get("window_wid"), "class": "DialogWindow", "objectName": "", "text": "Dialog", "children": []}],
    )

    payload = mcp_server._compat_snapshot_result(connection, depth=3, window_index=1)

    assert 'DialogWindow "Dialog"' in payload["snapshot"]
    assert payload["refs"][0]["wid"] == 22


def test_target_not_found_message_suggests_refresh_for_missing_snapshot_ref():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        snapshot_refs={"e1": 42},
    )

    message = mcp_server._target_not_found_message(connection, "e9")

    assert "Snapshot ref 'e9' is not available" in message
    assert "Run browser_snapshot to refresh refs" in message


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
    assert "widget_tree, or inspect_widget" in message
    assert "#objectName, role=button, text=Submit, has-text=partial, .QLabel" in message