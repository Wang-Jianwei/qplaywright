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