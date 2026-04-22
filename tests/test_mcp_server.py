from __future__ import annotations

import pytest

import qplaywright.mcp_server as mcp_server


class FakeQPlaywright:
    def __init__(self):
        self.closed = False
        self.connected = None

    def connect(self, *, host: str, port: int, timeout: float):
        self.connected = (host, port, timeout)
        return FakeApp([])

    def close(self) -> None:
        self.closed = True


class FakeApp:
    def __init__(self, windows):
        self._windows = windows
        self.closed = False
        self._conn = None

    def windows(self):
        return self._windows

    def close(self) -> None:
        self.closed = True


class FakeWindow:
    def __init__(self, wid: int, title: str):
        self.wid = wid
        self._title = title
        self.closed = False

    def title(self) -> str:
        return self._title

    def close(self) -> None:
        self.closed = True


class FakeLocator:
    def __init__(self, *, count: int, invoke_result=None):
        self._count = count
        self._invoke_result = invoke_result

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
        if self._invoke_result is not None:
            return self._invoke_result
        return {
            "method_name": method_name,
            "args": dict(args or {}),
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