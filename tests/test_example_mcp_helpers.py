from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest


def _load_example_module():
    path = Path(__file__).resolve().parents[1] / "examples" / "test_mcp_demo.py"
    spec = importlib.util.spec_from_file_location("test_mcp_demo_module", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeLoop:
    def __init__(self, now: float):
        self.now = now

    def time(self) -> float:
        return self.now


def test_attach_session_uses_remaining_timeout(monkeypatch):
    module = _load_example_module()
    loop = FakeLoop(100.0)
    captured: dict[str, object] = {}
    attempts = {"count": 0}

    class FakeProbe:
        def close(self) -> None:
            captured["probe_closed"] = True

    def fake_create_connection(address, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise OSError("not ready")
        captured["probe_address"] = address
        captured["probe_timeout"] = timeout
        return FakeProbe()

    async def fake_sleep(delay: float) -> None:
        loop.now += delay

    async def fake_call_tool(session, name, arguments):
        captured["tool_name"] = name
        captured["tool_arguments"] = arguments
        return {"ok": True}

    monkeypatch.setattr(module.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(module.socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(module, "_call_tool", fake_call_tool)

    result = asyncio.run(module._attach_session(object(), port=29876, timeout=30.0))

    assert result == {"ok": True}
    assert captured["probe_address"] == ("127.0.0.1", 29876)
    assert captured["probe_closed"] is True
    assert captured["tool_name"] == "session"
    assert captured["tool_arguments"] == {
        "action": "attach",
        "host": "127.0.0.1",
        "port": 29876,
        "timeout": pytest.approx(29.75),
    }


def test_attach_session_falls_through_to_attach_after_probe_budget(monkeypatch):
    module = _load_example_module()
    loop = FakeLoop(50.0)
    captured: dict[str, object] = {}

    def fake_create_connection(address, timeout):
        raise OSError("not ready")

    async def fake_sleep(delay: float) -> None:
        loop.now += delay

    async def fake_call_tool(session, name, arguments):
        captured["tool_name"] = name
        captured["tool_arguments"] = arguments
        return {"ok": True}

    monkeypatch.setattr(module.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(module.socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(module, "_call_tool", fake_call_tool)

    result = asyncio.run(module._attach_session(object(), port=29876, timeout=1.5))

    assert result == {"ok": True}
    assert captured["tool_name"] == "session"
    assert captured["tool_arguments"] == {
        "action": "attach",
        "host": "127.0.0.1",
        "port": 29876,
        "timeout": pytest.approx(1.0),
    }


def test_attach_session_stops_after_total_deadline(monkeypatch):
    module = _load_example_module()
    loop = FakeLoop(10.0)
    called = {"attach": False}

    def fake_create_connection(address, timeout):
        loop.now += 1.0
        raise OSError("not ready")

    async def fake_sleep(delay: float) -> None:
        loop.now += delay

    async def fake_call_tool(session, name, arguments):
        called["attach"] = True
        return {"ok": True}

    monkeypatch.setattr(module.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(module.socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(module, "_call_tool", fake_call_tool)

    with pytest.raises(TimeoutError, match="Timed out waiting for QPlaywright agent"):
        asyncio.run(module._attach_session(object(), port=29876, timeout=0.05))

    assert called["attach"] is False