"""Tests for exponential backoff in QPlaywright.connect()."""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from qplaywright.protocol import METHOD_HANDSHAKE, METHOD_SET_SESSION_INFO, PROTOCOL_VERSION
from qplaywright.sync_api._api import QPlaywright


def test_connect_uses_exponential_backoff_on_repeated_failures():
    """connect() should double the sleep interval after each failure up to max_backoff."""
    sleep_calls: list[float] = []

    # Time advances only when sleep is called so we control the loop iterations.
    _time = [0.0]
    timeout = 10.0

    def fake_monotonic() -> float:
        return _time[0]

    def advance_time_on_sleep(t: float) -> None:
        sleep_calls.append(t)
        _time[0] += t

    fake_conn = MagicMock()
    fake_conn.connect.side_effect = ConnectionRefusedError("refused")

    with (
        patch("qplaywright.sync_api._api.Connection", return_value=fake_conn),
        patch("qplaywright.sync_api._api.time.monotonic", side_effect=fake_monotonic),
        patch("qplaywright.sync_api._api.time.sleep", side_effect=advance_time_on_sleep),
    ):
        with pytest.raises(ConnectionError):
            QPlaywright().connect(timeout=timeout)

    # At least 3 retry cycles should have occurred.
    assert len(sleep_calls) >= 3

    # Verify exponential growth: each sleep should be double the previous,
    # capped at max_backoff (2.0).
    expected_backoff = 0.1
    max_backoff = 2.0
    for actual in sleep_calls:
        assert actual == pytest.approx(expected_backoff)
        expected_backoff = min(expected_backoff * 2, max_backoff)


def test_connect_raises_after_timeout():
    """connect() should raise ConnectionError when timeout is exhausted."""
    _time = [0.0]

    def fake_monotonic() -> float:
        return _time[0]

    def advance_time_on_sleep(t: float) -> None:
        _time[0] += t + 100  # jump past deadline on first sleep

    fake_conn = MagicMock()
    fake_conn.connect.side_effect = ConnectionRefusedError("refused")

    with (
        patch("qplaywright.sync_api._api.Connection", return_value=fake_conn),
        patch("qplaywright.sync_api._api.time.monotonic", side_effect=fake_monotonic),
        patch("qplaywright.sync_api._api.time.sleep", side_effect=advance_time_on_sleep),
    ):
        with pytest.raises(ConnectionError, match="Could not connect"):
            QPlaywright().connect(timeout=1.0)


def test_connect_succeeds_on_second_attempt():
    """connect() should return an Application when connection eventually succeeds."""
    _time = [0.0]

    def fake_monotonic() -> float:
        return _time[0]

    def fake_sleep(t: float) -> None:
        _time[0] += t

    attempt = [0]

    def connect_side_effect():
        attempt[0] += 1
        if attempt[0] < 2:
            raise ConnectionRefusedError("refused")

    fake_conn = MagicMock()
    fake_conn.connect.side_effect = connect_side_effect
    fake_conn.send.return_value = {"protocol_version": PROTOCOL_VERSION, "agent_kind": "python"}

    with (
        patch("qplaywright.sync_api._api.Connection", return_value=fake_conn),
        patch("qplaywright.sync_api._api.time.monotonic", side_effect=fake_monotonic),
        patch("qplaywright.sync_api._api.time.sleep", side_effect=fake_sleep),
    ):
        from qplaywright.sync_api._api import Application

        app = QPlaywright().connect(timeout=30.0)

    assert isinstance(app, Application)
    assert attempt[0] == 2
    assert fake_conn.send.mock_calls[-1] == call(METHOD_HANDSHAKE)


def test_connect_advertises_agent_name_after_successful_handshake():
    fake_conn = MagicMock()
    fake_conn.send.side_effect = [
        {"protocol_version": PROTOCOL_VERSION, "agent_kind": "python"},
        {"agentName": "GitHub Copilot"},
    ]

    with patch("qplaywright.sync_api._api.Connection", return_value=fake_conn):
        QPlaywright().connect(timeout=30.0, agent_name="GitHub Copilot")

    assert fake_conn.send.mock_calls == [
        call(METHOD_HANDSHAKE),
        call(METHOD_SET_SESSION_INFO, {"agentName": "GitHub Copilot"}),
    ]


def test_connect_fails_immediately_on_protocol_mismatch():
    sleep_calls: list[float] = []
    fake_conn = MagicMock()
    fake_conn.send.return_value = {"protocol_version": PROTOCOL_VERSION + 1, "agent_kind": "python"}

    with (
        patch("qplaywright.sync_api._api.Connection", return_value=fake_conn),
        patch("qplaywright.sync_api._api.time.sleep", side_effect=lambda value: sleep_calls.append(value)),
    ):
        with pytest.raises(ConnectionError, match="protocol mismatch"):
            QPlaywright().connect(timeout=30.0)

    assert fake_conn.connect.call_count == 1
    assert sleep_calls == []
