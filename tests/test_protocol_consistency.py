from __future__ import annotations

import re
from pathlib import Path

from qplaywright import agent_header_path
from qplaywright.protocol import METHOD_HANDSHAKE, METHOD_PING, PROTOCOL_VERSION, ROLE_MAP


def _python_agent_server_path() -> Path:
    return Path(__file__).resolve().parents[1] / "qplaywright" / "agent" / "_server.py"


def test_cpp_header_protocol_version_matches_python_protocol_version():
    header_text = agent_header_path().read_text(encoding="utf-8")
    match = re.search(r"QPLAYWRIGHT_PROTOCOL_VERSION\s*=\s*(\d+)\s*;", header_text)

    assert match is not None
    assert int(match.group(1)) == PROTOCOL_VERSION


def test_cpp_header_dispatch_exposes_required_handshake_methods():
    header_text = agent_header_path().read_text(encoding="utf-8")

    assert f'if (method == "{METHOD_HANDSHAKE}")' in header_text
    assert 'r["protocol_version"] = QPLAYWRIGHT_PROTOCOL_VERSION;' in header_text
    assert 'r["agent_kind"] = QStringLiteral("cpp");' in header_text
    assert f'if (method == "{METHOD_PING}")' in header_text


def test_python_agent_dispatch_exposes_required_handshake_methods():
    server_text = _python_agent_server_path().read_text(encoding="utf-8")

    assert "if method == METHOD_HANDSHAKE:" in server_text
    assert '"protocol_version": PROTOCOL_VERSION' in server_text
    assert '"agent_kind": "python"' in server_text
    assert "if method == METHOD_PING:" in server_text


def test_cpp_header_role_map_covers_python_qwidget_roles():
    header_text = agent_header_path().read_text(encoding="utf-8")

    # menuitem currently maps to QAction on the Python side, but the C++
    # header role matcher only inspects QWidget class hierarchies.
    for role in ROLE_MAP:
        if role == "menuitem":
            continue
        assert f'{{"{role}",' in header_text


def test_spinbox_role_includes_date_time_editors_in_python_and_cpp():
    header_text = agent_header_path().read_text(encoding="utf-8")

    assert {"QDateEdit", "QTimeEdit", "QDateTimeEdit"}.issubset(set(ROLE_MAP["spinbox"]))
    assert '"QDateEdit"' in header_text
    assert '"QTimeEdit"' in header_text
    assert '"QDateTimeEdit"' in header_text