from pathlib import Path


def agent_header_path() -> Path:
    packaged = Path(__file__).with_name("qplaywright_agent.h")
    if packaged.exists():
        return packaged

    repo_header = Path(__file__).resolve().parents[2] / "agent_cpp" / "qplaywright_agent.h"
    if repo_header.exists():
        return repo_header

    raise FileNotFoundError("qplaywright_agent.h is not available in the installed package")


__all__ = ["agent_header_path"]