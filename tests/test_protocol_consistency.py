from __future__ import annotations

import re
from pathlib import Path

from qplaywright import agent_header_path
from qplaywright.protocol import METHOD_HANDSHAKE, METHOD_PING, PROTOCOL_VERSION


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