from __future__ import annotations

import anyio
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
        return FakeLocator(count=1, target=target)

    def screenshot(self, **kwargs):
        self.screenshot_calls.append(kwargs)
        return {"path": kwargs.get("path"), "width": 320, "height": 240}


class FakeLocator:
    def __init__(self, *, count: int, invoke_result=None, target: str | None = None):
        self._count = count
        self._invoke_result = invoke_result
        self._target = target
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
            "objectName": self._target or "amount_editor",
            "accessibleName": "Amount editor",
            "accessibleDescription": "输入金额",
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
        {"method": "click", "params": {"wid": 42}, "timeout": 30.0}
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


def test_inspect_target_uses_target_payload(monkeypatch):
    locator = FakeLocator(count=1)

    monkeypatch.setattr(mcp_server, "_get_connection", lambda state: object())
    monkeypatch.setattr(mcp_server, "_resolve_locator", lambda *args, **kwargs: locator)

    result = mcp_server.inspect(target="#amount", include_methods=True, include_properties=True)

    assert result["target"] == "#amount"
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
    assert listed["windows"][0]["is_active"] is True
    assert listed["windows"][1]["is_modal"] is True
    assert selected["active_window"]["wid"] == 22
    assert selected["active_window"]["is_modal"] is True
    assert selected["refs_cleared"] is True
    assert resized["active_window"]["wid"] == 22
    assert first.resized_to is None
    assert second.resized_to == (800, 600)
    assert closed["active_window"]["wid"] == 11
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
        return {"snapshot": "- Main [ref=e1]", "refs": [{"ref": "e1"}]}

    monkeypatch.setattr(mcp_server, "_SERVER_STATE", state)
    monkeypatch.setattr(mcp_server, "_snapshot_result", fake_snapshot_result)
    monkeypatch.setattr(mcp_server, "_write_text_file", lambda path, content: path)

    result = mcp_server.snapshot(depth=4, save_to="snapshot.txt")

    assert captured["kwargs"] == {"target": None, "depth": 4}
    assert result["ok"] is True
    assert result["window"]["wid"] == 11
    assert result["save_to"] == "snapshot.txt"


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

    result = mcp_server.inspect(depth=6)

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
    assert present["objectName"] == "amount_editor"
    assert present["accessibleName"] == "Amount editor"
    assert present["property_value"] == "attr:placeholderText"

    with_methods = mcp_server._inspect_locator(FakeLocator(count=1), include_methods=True, include_properties=True)
    assert with_methods["methods"][0]["name"] == "setAmount"
    assert with_methods["properties"]["myText"] == "pressme"


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

    with pytest.raises(ValueError, match="No widget found for invoke.*snapshot or inspect"):
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
    monkeypatch.setattr(mcp_server, "_resolve_locator", lambda *args, **kwargs: locator)
    monkeypatch.setattr(
        mcp_server,
        "_window_summary",
        lambda managed_connection: [{"wid": 11, "title": "Main", "class": "DemoWindow", "index": 0, "width": 640, "height": 720, "is_active": True, "is_modal": False}],
    )
    monkeypatch.setattr(
        mcp_server,
        "_action_result_with_snapshot",
        lambda managed_connection, **payload: payload | {"snapshot": "- DemoWindow [ref=e1]", "refs": [{"ref": "e1"}]},
    )

    result = mcp_server.wait(target="#status_label", state="visible", timeout=5.0, include_snapshot=True)

    assert locator.wait_calls == [{"state": "visible", "timeout": 5.0}]
    assert result["ok"] is True
    assert result["target"] == "#status_label"
    assert result["window_changed"] is False
    assert result["active_window"]["wid"] == 11
    assert result["snapshot"] == "- DemoWindow [ref=e1]"
    assert result["refs"] == [{"ref": "e1"}]


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
        mcp_server.wait(target="#status_label", state="attached")


@pytest.mark.parametrize(
    ("tool_name", "call_kwargs", "expected_calls", "expected_payload"),
    [
        ("click", {"target": "#submit", "include_snapshot": True}, [("click", {})], {"target": "#submit", "count": 1}),
        ("click", {"target": "#submit", "count": 2, "include_snapshot": True}, [("dblclick", {})], {"target": "#submit", "count": 2}),
        ("input", {"target": "#amount", "text": "123.45", "include_snapshot": True}, [("fill", {"value": "123.45"})], {"target": "#amount", "text": "123.45", "mode": "replace", "delay": 0, "submitted": False}),
        ("invoke", {"target": "#amount", "method": "setAmount", "args": {"value": "88.00"}, "include_snapshot": True}, [("invoke", {"method_name": "setAmount", "args": {"value": "88.00"}})], {"target": "#amount", "method": "setAmount", "args": {"value": "88.00"}}),
        ("input", {"target": "#amount", "text": "abc", "mode": "append", "delay": 25, "submit": True, "include_snapshot": True}, [("type", {"text": "abc", "delay": 25}), ("press", {"key": "Enter"})], {"target": "#amount", "text": "abc", "mode": "append", "delay": 25, "submitted": True}),
        ("press_key", {"target": "#amount", "key": "Enter", "include_snapshot": True}, [("press", {"key": "Enter"})], {"target": "#amount", "key": "Enter"}),
        ("set_checked", {"target": "#remember", "checked": True, "include_snapshot": True}, [("check", {})], {"target": "#remember", "checked": True}),
        ("set_checked", {"target": "#remember", "checked": False, "include_snapshot": True}, [("uncheck", {})], {"target": "#remember", "checked": False}),
        ("choose", {"target": "#currency", "label": "CNY", "include_snapshot": True}, [("select_option", {"value": None, "index": None, "label": "CNY"})], {"target": "#currency", "label": "CNY", "value": None, "index": None}),
        ("hover", {"target": "#item", "include_snapshot": True}, [("hover", {})], {"target": "#item"}),
        ("scroll", {"target": "#item", "delta_x": 5, "delta_y": 10, "include_snapshot": True}, [("scroll", {"delta_x": 5, "delta_y": 10})], {"target": "#item", "delta_x": 5, "delta_y": 10}),
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
    monkeypatch.setattr(mcp_server, "_resolve_locator", lambda *args, **kwargs: locator)
    monkeypatch.setattr(
        mcp_server,
        "_window_summary",
        lambda managed_connection: [{"wid": 11, "title": "Main", "class": "DemoWindow", "index": 0, "width": 640, "height": 720, "is_active": True, "is_modal": False}],
    )
    monkeypatch.setattr(
        mcp_server,
        "_action_result_with_snapshot",
        lambda managed_connection, **payload: payload | {"snapshot": "- DemoWindow [ref=e1]", "refs": [{"ref": "e1"}]},
    )

    result = getattr(mcp_server, tool_name)(**call_kwargs)

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
        lambda managed_connection: [{"wid": 22, "title": "Dialog", "class": "QDialog", "index": 0, "width": 480, "height": 320, "is_active": True, "is_modal": False}],
    )

    def fake_action_result_with_snapshot(managed_connection, *, target=None, **payload):
        captured["target"] = target
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
        "_window_summary",
        lambda managed_connection: [{"wid": 11, "title": "Main", "class": "DemoWindow", "index": 0, "width": 640, "height": 720, "is_active": True, "is_modal": False}],
    )

    result = mcp_server.press_key(key="Enter")

    assert transport.calls[-1] == {"method": "press", "params": {"key": "Enter", "window_wid": 11}, "timeout": 30.0}
    assert result["ok"] is True
    assert result["target"] is None
    assert result["key"] == "Enter"


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
        mcp_server.scroll(target="#item")


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

    assert 'MenuButton "功率扫描" [a11y] target=#measure_type_btn' in snapshot


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
        [{"wid": 1, "class": "DemoWindow", "objectName": "", "windowTitle": "Title", "children": []}],
    )

    assert payload["refs"] == [{"ref": "e2", "wid": 1, "target": ".DemoWindow", "class": "DemoWindow", "windowTitle": "Title"}]
    assert connection.snapshot_refs == {"e1": 99, "e2": 1}
    assert connection.snapshot_wids == {99: "e1", 1: "e2"}


def test_snapshot_result_resets_refs_and_passes_depth_for_target_snapshot():
    transport = FakeTransportConn(
        responses={
            mcp_server.METHOD_FIND: {
                "wid": 42,
                "class": "DemoWindow",
                "objectName": "",
                "text": "Dialog",
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
        snapshot_refs={"e9": 42},
        snapshot_wids={42: "e9"},
    )

    result = mcp_server._snapshot_result(connection, target="e9", depth=3)

    assert transport.calls == [
        {"method": "find", "params": {"wid": 42, "max_depth": 3}, "timeout": 30.0}
    ]
    assert connection.snapshot_refs == {"e1": 42, "e2": 43}
    assert connection.snapshot_wids == {42: "e1", 43: "e2"}
    assert result["refs"] == [
        {"ref": "e1", "wid": 42, "target": ".DemoWindow", "class": "DemoWindow", "text": "Dialog"},
        {"ref": "e2", "wid": 43, "target": "#confirm_btn", "class": "QPushButton", "text": "Confirm"},
    ]


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
    monkeypatch.setattr(mcp_server, "_resolve_locator", lambda *args, **kwargs: locator)

    result = mcp_server.screenshot(target="#amount", path="amount.png")

    assert locator.screenshot_calls == [{"path": "amount.png"}]
    assert result["ok"] is True
    assert result["target"] == "#amount"
    assert result["path"] == "amount.png"
    assert result["width"] == 120
    assert result["height"] == 40
    assert result["active_window"]["wid"] == 11
    assert result["active_window"]["title"] == "Main"
    assert result["active_window"]["is_active"] is True


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


def test_main_cli_dispatches_to_cli_runner(monkeypatch):
    called = {}

    def fake_run_cli(argv):
        called["argv"] = list(argv)
        return 0

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

    monkeypatch.setattr(mcp_server, "_configure_stdio_for_mcp", lambda transport: calls.setdefault("transport", transport))
    monkeypatch.setattr(mcp_server, "_run_mcp_transport", fake_run_transport)

    with pytest.raises(SystemExit) as exc_info:
        mcp_server.main(["--transport", "streamable-http"])

    assert exc_info.value.code == 0
    assert calls == {"transport": "streamable-http", "run_transport": "streamable-http"}


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


def test_target_params_accept_snapshot_ref():
    connection = mcp_server.ManagedConnection(
        name="demo",
        qplaywright=FakeQPlaywright(),
        app=FakeApp([]),
        host="127.0.0.1",
        port=19876,
        timeout=30.0,
        snapshot_refs={"e2": 42},
    )

    params = mcp_server._target_params(connection, "e2")

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
        lambda managed_connection, **kwargs: {"snapshot": "- item [ref=e1]", "refs": [{"ref": "e1"}]},
    )

    result = mcp_server._action_result_with_snapshot(
        connection,
        target="e1",
        ok=True,
    )

    assert result["ok"] is True
    assert result["snapshot"] == "- item [ref=e1]"
    assert result["refs"] == [{"ref": "e1"}]


def test_widget_tree_raw_includes_optional_window_wid():
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

    payload = mcp_server._snapshot_result(connection, depth=3)

    assert captured["kwargs"] == {"max_depth": 3, "window_wid": 22}
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
    assert "Run snapshot to refresh refs" in message


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
    assert "snapshot or inspect" in message
    assert "#objectName, role=button, text=Submit, has-text=partial, a11y-name=Submit, .QLabel" in message


def test_cli_tool_help_includes_action_level_session_and_window_guidance():
    session_help = mcp_server._cli_tool_help("session", mcp_server.session)
    window_help = mcp_server._cli_tool_help("window", mcp_server.window)

    assert "session.attach: attach to an already running Qt app" in session_help
    assert "session.status: report current session and active window" in session_help
    assert "window.select: switch active window" in window_help
    assert "window.close: close one window or the active window" in window_help
