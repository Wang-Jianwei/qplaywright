from __future__ import annotations

from qplaywright import agent_header_path


def test_agent_header_path_points_to_cpp_header():
    header = agent_header_path()

    assert header.name == "qplaywright_agent.h"
    assert header.is_file()
    assert header.read_text(encoding="utf-8").startswith("/**")