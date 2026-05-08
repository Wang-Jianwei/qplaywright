from __future__ import annotations

from types import SimpleNamespace

from qplaywright.agent import _selector as selector
from qplaywright.agent import _server as server
from qplaywright.protocol import QPlaywrightClassMetadata, QPlaywrightClassMethod, QPlaywrightMethodArg, Request
from qplaywright.sync_api._api import Window
from qplaywright.sync_api._locator import Locator


class FakeInvokeWidget:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self._metadata = QPlaywrightClassMetadata().role("textbox")
        self._metadata.addMethod(
            QPlaywrightClassMethod()
            .name("setAmount")
            .brief("Update the current amount")
            .returnType("QVariant")
            .addArg(
                QPlaywrightMethodArg()
                .name("value")
                .type("QString")
                .brief("Formatted amount text")
                .required(True)
            )
        )
        self._metadata.addMethod(
            QPlaywrightClassMethod()
            .name("summary")
            .brief("Render a short summary")
            .returnType("QString")
            .addArg(
                QPlaywrightMethodArg()
                .name("prefix")
                .type("QString")
                .brief("Optional output prefix")
                .required(False)
                .defaultValue("")
            )
        )
        self._metadata.addMethod(
            QPlaywrightClassMethod()
            .name("toggle")
            .brief("Toggle bool state")
            .returnType("bool")
            .addArg(
                QPlaywrightMethodArg()
                .name("enabled")
                .type("bool")
                .brief("Whether the state should be enabled")
                .required(True)
            )
        )
        self._metadata.addMethod(
            QPlaywrightClassMethod().name("snapshot").brief("Return a structured snapshot").returnType("QVariant")
        )

    def property(self, name):
        if isinstance(name, bytes):
            name = name.decode()
        if name == "qplaywrightClassMetadata":
            return self._metadata
        return None

    def setAmount(self, value):
        self.calls.append(("setAmount", (value,)))
        return {"amount": value}

    def summary(self, prefix=""):
        self.calls.append(("summary", (prefix,)))
        return f"{prefix}ok"

    def toggle(self, enabled):
        self.calls.append(("toggle", (enabled,)))
        return enabled

    def snapshot(self):
        self.calls.append(("snapshot", ()))
        return [1, "two", True]


class FakeConnection:
    def __init__(self):
        self.calls: list[tuple[str, dict, float]] = []

    def send(self, method: str, params: dict | None = None, *, timeout: float | None = None):
        payload = params or {}
        self.calls.append((method, payload, timeout))
        return {"method": method, "params": payload}


class SequencedConnection(FakeConnection):
    def __init__(self, responses: dict[str, list[object] | object]):
        super().__init__()
        self.responses = responses

    def send(self, method: str, params: dict | None = None, *, timeout: float | None = None):
        payload = params or {}
        self.calls.append((method, payload, timeout))
        response = self.responses[method]
        if isinstance(response, list):
            if len(response) > 1:
                return response.pop(0)
            return response[0]
        return response


def test_selector_declared_method_schema_reads_class_metadata():
    widget = FakeInvokeWidget()

    result = selector._declared_method_schema(widget)

    assert result[0] == {
        "name": "setAmount",
        "brief": "Update the current amount",
        "returnType": "QVariant",
        "args": [
            {
                "name": "value",
                "type": "QString",
                "brief": "Formatted amount text",
                "required": True,
                "defaultValue": None,
            }
        ],
    }
    assert result[1]["args"][0]["defaultValue"] == ""


def test_selector_prepare_invoke_call_applies_defaults_and_type_conversion():
    widget = FakeInvokeWidget()

    prepared = selector._prepare_invoke_call(
        widget,
        {
            "method": "toggle",
            "args": {"enabled": "true"},
        },
    )

    assert prepared["method"]["name"] == "toggle"
    assert prepared["orderedArgs"] == [True]

    defaulted = selector._prepare_invoke_call(
        widget,
        {
            "method": "summary",
            "args": {},
        },
    )

    assert defaulted["orderedArgs"] == [""]


def test_selector_prepare_invoke_call_rejects_missing_and_unexpected_args():
    widget = FakeInvokeWidget()

    try:
        selector._prepare_invoke_call(widget, {"method": "setAmount", "args": {}})
    except ValueError as exc:
        assert str(exc) == "Missing required argument: value"
    else:
        raise AssertionError("Expected missing argument failure")

    try:
        selector._prepare_invoke_call(
            widget,
            {"method": "summary", "args": {"prefix": "x", "extra": 1}},
        )
    except ValueError as exc:
        assert str(exc) == "Unexpected argument: extra"
    else:
        raise AssertionError("Expected unexpected argument failure")


def test_server_invoke_widget_method_returns_structured_success(monkeypatch):
    widget = FakeInvokeWidget()
    monkeypatch.setattr(server, "_process_events", lambda ms=10: None)

    result = server._invoke_widget_method(widget, {"method": "snapshot", "args": {}})

    assert result == {
        "ok": True,
        "value": [1, "two", True],
        "errorCode": 0,
        "errorMessage": "",
    }
    assert widget.calls == [("snapshot", ())]


def test_server_invoke_widget_method_returns_structured_failure(monkeypatch):
    widget = FakeInvokeWidget()
    monkeypatch.setattr(server, "_process_events", lambda ms=10: None)

    result = server._invoke_widget_method(widget, {"method": "setAmount", "args": {}})

    assert result == {
        "ok": False,
        "value": None,
        "errorCode": 2,
        "errorMessage": "Missing required argument: value",
    }


def test_locator_invoke_sends_structured_request():
    conn = FakeConnection()
    locator = Locator(conn, "#amount", timeout=12.0)

    result = locator.invoke("setAmount", {"value": "42"})

    assert result == {
        "method": "invoke",
        "params": {
            "selector": "#amount",
            "request": {
                "method": "setAmount",
                "args": {"value": "42"},
            },
        },
    }
    assert conn.calls == [
        (
            "invoke",
            {
                "selector": "#amount",
                "request": {
                    "method": "setAmount",
                    "args": {"value": "42"},
                },
            },
            12.0,
        )
    ]


def test_locator_methods_requests_method_schema():
    conn = FakeConnection()
    locator = Locator(conn, "#amount", timeout=8.0)

    result = locator.methods()

    assert result == {
        "method": "get_methods",
        "params": {
            "selector": "#amount",
        },
    }
    assert conn.calls == [
        (
            "get_methods",
            {
                "selector": "#amount",
            },
            8.0,
        )
    ]


def test_locator_properties_requests_all_property_map():
    conn = FakeConnection()
    locator = Locator(conn, "#amount", timeout=8.0)

    result = locator.properties()

    assert result == {
        "method": "get_properties",
        "params": {
            "selector": "#amount",
        },
    }
    assert conn.calls == [
        (
            "get_properties",
            {
                "selector": "#amount",
            },
            8.0,
        )
    ]


def test_server_get_property_and_get_properties_use_qt_property_storage(monkeypatch):
    class FakeMetaProperty:
        def __init__(self, name: str):
            self._name = name

        def name(self) -> str:
            return self._name

    class FakeMetaObject:
        def propertyCount(self) -> int:
            return 2

        def property(self, index: int):
            return [FakeMetaProperty("text"), FakeMetaProperty("qplaywrightClassMetadata")][index]

    class PropertyWidget(FakeInvokeWidget):
        def metaObject(self):
            return FakeMetaObject()

        def dynamicPropertyNames(self):
            return [b"myText"]

        def property(self, name):
            if isinstance(name, bytes):
                name = name.decode()
            if name == "qplaywrightClassMetadata":
                return self._metadata
            if name == "text":
                return "Painter text"
            if name == "myText":
                return "pressme"
            return None

    widget = PropertyWidget()

    monkeypatch.setattr(server, "_import_qt", lambda: None)
    monkeypatch.setattr(server, "_QtCore", SimpleNamespace(Qt=object()))
    monkeypatch.setattr(server, "_QtGui", SimpleNamespace(QCursor=object()))
    monkeypatch.setattr(server, "_resolve_one", lambda params: widget)

    single = server._handle_command(Request(id=1, method="get_property", params={"wid": 1, "property": "myText"}))
    all_properties = server._handle_command(Request(id=2, method="get_properties", params={"wid": 1}))

    assert single == "pressme"
    assert all_properties["text"] == "Painter text"
    assert all_properties["myText"] == "pressme"
    assert all_properties["qplaywrightClassMetadata"]["methods"][0]["name"] == "setAmount"


def test_locator_can_send_direct_widget_id_params():
    conn = FakeConnection()
    locator = Locator(conn, "", widget_wid=42, timeout=9.0)

    result = locator.click()

    assert result is None
    assert conn.calls == [
        (
            "click",
            {
                "wid": 42,
            },
            9.0,
        )
    ]


def test_locator_wait_for_checked_and_unchecked_poll_is_checked():
    checked_conn = SequencedConnection({
        "count": [1, 1],
        "is_checked": [False, True],
    })
    checked_locator = Locator(checked_conn, "#remember", timeout=0.5)

    checked_locator.wait_for(state="checked", timeout=0.2)

    assert checked_conn.calls == [
        ("count", {"selector": "#remember"}, 0.5),
        ("is_checked", {"selector": "#remember", "nth": 0}, 0.5),
        ("count", {"selector": "#remember"}, 0.5),
        ("is_checked", {"selector": "#remember", "nth": 0}, 0.5),
    ]

    unchecked_conn = SequencedConnection({
        "count": [1, 1],
        "is_checked": [True, False],
    })
    unchecked_locator = Locator(unchecked_conn, "#remember", timeout=0.5)

    unchecked_locator.wait_for(state="unchecked", timeout=0.2)

    assert unchecked_conn.calls == [
        ("count", {"selector": "#remember"}, 0.5),
        ("is_checked", {"selector": "#remember", "nth": 0}, 0.5),
        ("count", {"selector": "#remember"}, 0.5),
        ("is_checked", {"selector": "#remember", "nth": 0}, 0.5),
    ]


def test_window_screenshot_passes_clip_region():
    conn = FakeConnection()
    window = Window(conn, wid=7, timeout=6.0)

    result = window.screenshot(path="clip.png", x=10, y=20, width=30, height=40)

    assert result == {
        "method": "screenshot",
        "params": {
            "wid": 7,
            "path": "clip.png",
            "x": 10,
            "y": 20,
            "width": 30,
            "height": 40,
        },
    }
    assert conn.calls == [
        (
            "screenshot",
            {
                "wid": 7,
                "path": "clip.png",
                "x": 10,
                "y": 20,
                "width": 30,
                "height": 40,
            },
            None,
        )
    ]


def test_window_click_at_sends_window_relative_request():
    conn = FakeConnection()
    window = Window(conn, wid=7, timeout=6.0)

    window.click_at(10, 20)

    assert conn.calls == [
        (
            "click",
            {"window_wid": 7, "x": 10, "y": 20},
            None,
        )
    ]


def test_window_click_at_count_2_uses_dblclick():
    conn = FakeConnection()
    window = Window(conn, wid=7, timeout=6.0)

    window.click_at(3, 4, count=2)

    assert conn.calls == [
        (
            "dblclick",
            {"window_wid": 7, "x": 3, "y": 4},
            None,
        )
    ]


def test_window_hover_at_sends_window_relative_request():
    conn = FakeConnection()
    window = Window(conn, wid=7, timeout=6.0)

    window.hover_at(11, 12)

    assert conn.calls == [
        (
            "hover",
            {"window_wid": 7, "x": 11, "y": 12},
            None,
        )
    ]


def test_locator_screenshot_passes_clip_region():
    conn = FakeConnection()
    locator = Locator(conn, "#amount", timeout=8.0)

    result = locator.screenshot(path="widget.png", x=1, y=2, width=3, height=4)

    assert result == {
        "method": "screenshot_widget",
        "params": {
            "selector": "#amount",
            "path": "widget.png",
            "x": 1,
            "y": 2,
            "width": 3,
            "height": 4,
        },
    }
    assert conn.calls == [
        (
            "screenshot_widget",
            {
                "selector": "#amount",
                "path": "widget.png",
                "x": 1,
                "y": 2,
                "width": 3,
                "height": 4,
            },
            8.0,
        )
    ]