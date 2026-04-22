from pathlib import Path


def agent_header_path() -> Path:
    packaged = Path(__file__).with_name("qplaywright_agent.h")
    if packaged.exists():
        return packaged

    raise FileNotFoundError("qplaywright_agent.h is not available in the installed package")


__all__ = ["agent_header_path"]