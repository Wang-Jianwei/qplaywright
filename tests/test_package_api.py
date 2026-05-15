from __future__ import annotations

import logging
from io import StringIO

import qplaywright.agent._server as agent_server
from qplaywright import (
    QPlaywrightActionError,
    QPlaywrightConnectionError,
    QPlaywrightLookupError,
    QPlaywrightProtocolError,
    agent_header_path,
    configure_logging,
)


def test_agent_header_path_points_to_cpp_header():
    header = agent_header_path()

    assert header.name == "qplaywright_agent.h"
    assert header.is_file()
    assert header.read_text(encoding="utf-8").startswith("/**")


def test_public_error_types_are_exported():
    assert issubclass(QPlaywrightProtocolError, QPlaywrightConnectionError)
    assert issubclass(QPlaywrightLookupError, Exception)
    assert issubclass(QPlaywrightActionError, Exception)


def test_configure_logging_routes_child_package_logs_to_shared_handler():
    stream = StringIO()
    logger = configure_logging(level="DEBUG", stream=stream, force=True)

    logging.getLogger("qplaywright.mcp_server").debug("debug message")

    output = stream.getvalue()
    assert logger.name == "qplaywright"
    assert "DEBUG qplaywright.mcp_server: debug message" in output


def test_start_agent_configures_logging_from_env(monkeypatch):
    calls: dict[str, object] = {}

    class FakeApp:
        pass

    class FakeDispatcher:
        def setObjectName(self, name: str) -> None:
            calls["dispatcher_name"] = name

    class FakeServer:
        def __init__(self, host, port, dispatcher, command_event, main_thread_call_event):
            calls["server_args"] = (host, port, dispatcher, command_event, main_thread_call_event)

        def start(self):
            calls["started"] = True

    monkeypatch.setattr(agent_server, "configure_logging_from_env", lambda: calls.setdefault("logging_configured", True))
    monkeypatch.setattr(agent_server, "_import_qt", lambda: None)
    monkeypatch.setattr(agent_server, "_qt_application_class", lambda: type("FakeQtAppClass", (), {"instance": staticmethod(lambda: FakeApp())}))
    monkeypatch.setattr(agent_server, "_create_dispatcher", lambda: (FakeDispatcher, object(), object()))
    monkeypatch.setattr(agent_server, "_AgentServer", FakeServer)
    monkeypatch.setattr(agent_server, "_ensure_overlay_manager", lambda: None)
    monkeypatch.setattr(agent_server, "_OVERLAY_MANAGER", None)
    monkeypatch.setattr(agent_server, "_VISUAL_FEEDBACK_ENABLED", False)

    server = agent_server.start_agent(app=FakeApp())

    assert calls["logging_configured"] is True
    assert calls["dispatcher_name"] == "_qplaywright_dispatcher"
    assert calls["started"] is True
    assert isinstance(server, FakeServer)


def test_fill_widget_supports_abstract_spinbox_text_entry(monkeypatch):
    events: list[tuple[str, object]] = []

    class FakeSpinBox:
        def lineEdit(self):
            return object()

        def stepEnabled(self):
            return 0

    monkeypatch.setattr(agent_server, "_import_qt", lambda: None)
    monkeypatch.setattr(agent_server, "_widget_class_name", lambda widget: "QSpinBox")
    monkeypatch.setattr(agent_server, "_clear_text_via_keyboard", lambda widget: events.append(("clear_keyboard", None)))
    monkeypatch.setattr(agent_server, "_type_text", lambda widget, text, delay=0: events.append(("type", (text, delay))))

    agent_server._fill_widget(FakeSpinBox(), "12.5")

    assert events == [
        ("clear_keyboard", None),
        ("type", ("12.5", 0)),
    ]


def test_fill_widget_clears_abstract_spinbox_without_typing(monkeypatch):
    events: list[tuple[str, object]] = []

    class FakeDateTimeEdit:
        def lineEdit(self):
            return object()

        def stepEnabled(self):
            return 0

    monkeypatch.setattr(agent_server, "_import_qt", lambda: None)
    monkeypatch.setattr(agent_server, "_widget_class_name", lambda widget: "QDateTimeEdit")
    monkeypatch.setattr(agent_server, "_clear_text_via_keyboard", lambda widget: events.append(("clear_keyboard", None)))
    monkeypatch.setattr(agent_server, "_type_text", lambda widget, text, delay=0: events.append(("type", (text, delay))))

    agent_server._fill_widget(FakeDateTimeEdit(), "")

    assert events == [
        ("clear_keyboard", None),
    ]


def test_fill_widget_replaces_datetime_edit_via_keyboard(monkeypatch):
    events: list[tuple[str, object]] = []

    class FakeDateTimeEdit:
        def lineEdit(self):
            return object()

        def stepEnabled(self):
            return 0

    monkeypatch.setattr(agent_server, "_import_qt", lambda: None)
    monkeypatch.setattr(agent_server, "_widget_class_name", lambda widget: "QDateTimeEdit")
    monkeypatch.setattr(agent_server, "_clear_text_via_keyboard", lambda widget: events.append(("clear_keyboard", None)))
    monkeypatch.setattr(agent_server, "_type_text", lambda widget, text, delay=0: events.append(("type", (text, delay))))

    agent_server._fill_widget(FakeDateTimeEdit(), "2026-05-15 09:30")

    assert events == [
        ("clear_keyboard", None),
        ("type", ("2026-05-15 09:30", 0)),
    ]


def test_fill_widget_replaces_line_edit_via_keyboard(monkeypatch):
    events: list[tuple[str, object]] = []

    class FakeLineEdit:
        def clear(self):
            raise AssertionError("direct clear should not be used")

        def setText(self, value):
            raise AssertionError("direct setText should not be used")

    monkeypatch.setattr(agent_server, "_import_qt", lambda: None)
    monkeypatch.setattr(agent_server, "_widget_class_name", lambda widget: "QLineEdit")
    monkeypatch.setattr(agent_server, "_clear_text_via_keyboard", lambda widget: events.append(("clear_keyboard", None)))
    monkeypatch.setattr(agent_server, "_type_text", lambda widget, text, delay=0: events.append(("type", (text, delay))))

    agent_server._fill_widget(FakeLineEdit(), "admin")

    assert events == [
        ("clear_keyboard", None),
        ("type", ("admin", 0)),
    ]


def test_fill_widget_replaces_plain_text_edit_via_keyboard(monkeypatch):
    events: list[tuple[str, object]] = []

    class FakePlainTextEdit:
        def setPlainText(self, value):
            raise AssertionError("direct setPlainText should not be used")

    monkeypatch.setattr(agent_server, "_import_qt", lambda: None)
    monkeypatch.setattr(agent_server, "_widget_class_name", lambda widget: "QPlainTextEdit")
    monkeypatch.setattr(agent_server, "_clear_text_via_keyboard", lambda widget: events.append(("clear_keyboard", None)))
    monkeypatch.setattr(agent_server, "_type_text", lambda widget, text, delay=0: events.append(("type", (text, delay))))

    agent_server._fill_widget(FakePlainTextEdit(), "notes")

    assert events == [
        ("clear_keyboard", None),
        ("type", ("notes", 0)),
    ]


def test_clear_text_via_keyboard_uses_ctrl_a_then_delete(monkeypatch):
    events: list[tuple[str, object]] = []

    class FakeQt:
        ControlModifier = "ctrl"

    class FakeCore:
        Qt = FakeQt

    monkeypatch.setattr(agent_server, "_qt_core_module", lambda: FakeCore)
    monkeypatch.setattr(
        agent_server,
        "_press_key",
        lambda widget, key_str, modifiers=None: events.append(("press", key_str, modifiers)),
    )

    agent_server._clear_text_via_keyboard(object())

    assert events == [
        ("press", "A", "ctrl"),
        ("press", "Delete", None),
    ]