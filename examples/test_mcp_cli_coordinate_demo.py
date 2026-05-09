"""Manual end-to-end test for coordinate click through the qplaywright MCP CLI REPL.

This script starts the Python demo app, launches the interactive qplaywright MCP
CLI, attaches to the demo session, resolves one button's center point through
CLI inspect output, then clicks it through `click --x/--y`.
"""

from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEMO_PORT = 29879
_PROMPT = "qplaywright> "


def _project_root() -> Path:
    return PROJECT_ROOT


def _python_path_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(root) if not existing else str(root) + os.pathsep + existing
    return env


class CliRepl:
    def __init__(self, process: subprocess.Popen[str]):
        self._process = process

    def wait_for_prompt(self) -> str:
        chunks: list[str] = []
        while True:
            char = self._process.stdout.read(1)
            if char == "":
                raise RuntimeError("MCP CLI exited before emitting a prompt")
            chunks.append(char)
            if "".join(chunks).endswith(_PROMPT):
                return "".join(chunks)

    def command(self, line: str) -> dict:
        if self._process.stdin is None:
            raise RuntimeError("MCP CLI stdin is unavailable")

        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()
        output = self.wait_for_prompt()
        payload = output[: -len(_PROMPT)].strip()
        if payload.startswith("ERROR:"):
            raise RuntimeError(payload)
        if not payload:
            return {}
        return json.loads(payload)

    def close(self) -> None:
        if self._process.poll() is not None:
            return
        if self._process.stdin is not None:
            try:
                self._process.stdin.write("exit\n")
                self._process.stdin.flush()
            except OSError:
                pass
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=5)


def _center_point(box: list[int]) -> tuple[int, int]:
    return box[0] + box[2] // 2, box[1] + box[3] // 2


def _window_relative_point(*, window_box: list[int], global_box: list[int]) -> tuple[int, int]:
    global_x, global_y = _center_point(global_box)
    return global_x - window_box[0], global_y - window_box[1]


def main() -> None:
    root = _project_root()
    env = _python_path_env(root)
    env["QPLAYWRIGHT_PORT"] = str(DEMO_PORT)
    env.setdefault("PYTHONUNBUFFERED", "1")

    demo_process = subprocess.Popen(
        [sys.executable, str(root / "examples" / "demo_app.py")],
        cwd=root,
        env=env,
        text=True,
    )
    cli_process = subprocess.Popen(
        [sys.executable, "-u", "-m", "qplaywright.mcp_server", "cli"],
        cwd=root,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    cli = CliRepl(cli_process)

    try:
        banner = cli.wait_for_prompt()
        print(banner[: -len(_PROMPT)].strip())

        attached = cli.command(f"session attach --port {DEMO_PORT} --timeout 60")
        active_window = attached["active_window"]
        print(f"Connected: {active_window}")

        window_inspect = cli.command("inspect --target .DemoWindow")
        window_box = window_inspect.get("global_bounding_box") or window_inspect.get("bounding_box")
        if not isinstance(window_box, list) or len(window_box) != 4:
            raise RuntimeError(f"Window inspect did not return a usable bounding box: {window_inspect}")

        clear_button = cli.command("inspect --target #clear_btn")
        clear_box = clear_button.get("global_bounding_box") or clear_button.get("bounding_box")
        if not isinstance(clear_box, list) or len(clear_box) != 4:
            raise RuntimeError(f"Clear button inspect did not return a usable bounding box: {clear_button}")

        point_x, point_y = _window_relative_point(
            window_box=window_box,
            global_box=clear_box,
        )
        print(f"Coordinate click point: x={point_x} y={point_y}")

        hover_result = cli.command(f"hover --x {point_x} --y {point_y}")
        print(f"Hover result: {hover_result}")
        assert hover_result["ok"] is True
        assert hover_result["x"] == point_x
        assert hover_result["y"] == point_y

        click_result = cli.command(f"click --x {point_x} --y {point_y} --include-state")
        print(f"Coordinate click result: {click_result}")
        assert click_result["ok"] is True
        assert click_result["x"] == point_x
        assert click_result["y"] == point_y

        status = cli.command("inspect --target #status")
        print(f"Status after coordinate click: {status['text']}")
        assert "Log cleared" in status["text"]

        closed = cli.command("session close")
        print(f"Session closed: {closed}")
        print("MCP CLI coordinate click flow completed")
    finally:
        cli.close()
        demo_process.terminate()
        try:
            demo_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            demo_process.kill()
            demo_process.wait(timeout=5)


if __name__ == "__main__":
    main()
