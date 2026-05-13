# QPlaywright

QPlaywright is a Playwright-compatible automation library for Qt QWidget applications.

It has two sides:

- A Qt-side agent embedded in the target application.
- A Python client with Playwright-style APIs such as locator, click, fill, invoke, expect, and MCP integration.

The Python client and the embedded agent communicate over JSON Lines on TCP.

## Install

Basic client install:

```bash
pip install qplaywright
```

Install with MCP support:

```bash
pip install "qplaywright[mcp]"
```

From source:

```bash
pip install .
pip install ".[mcp]"
```

## What Gets Installed

The Python package includes:

- The sync client API.
- The Python Qt agent.
- The MCP server entrypoint.
- The C++ header-only Qt agent.

In the source tree, the C++ agent lives under `qplaywright/cpp`.
The demo application lives separately under `examples/cpp_demo`.

If you need the packaged C++ agent header path at runtime:

```python
import qplaywright

header_path = qplaywright.agent_header_path()
print(header_path)
```

## Quick Start

### Python Qt application

```python
from qplaywright.agent import start_agent

start_agent(port=19876, visual_feedback=True)
```

Call `start_agent()` after creating `QApplication` and before entering `app.exec()`.

### C++ Qt application

```cpp
#include "qplaywright_agent.h"

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);
    QPlaywrightAgent::start(19876);
    return app.exec();
}
```

Build the bundled C++ demo from the source tree:

```bash
cd examples/cpp_demo
cmake -S . -B build -DCMAKE_PREFIX_PATH=<your-qt-path>
cmake --build build
```

### Python client

```python
from qplaywright import sync_qplaywright

with sync_qplaywright() as qp:
    app = qp.connect(port=19876, agent_name="GitHub Copilot")
    window = app.main_window()
    window.get_by_role("button", name="Submit").click()
    window.click_at(320, 180)
```

Structured descendants use explicit item locators instead of pretending model items are widgets:

```python
table = window.locator("#data_table")
assert table.cell(2, "Status").text_content() == "Active"

tree = window.locator("role=tree")
tree.node(["Settings", "Advanced"]).expand()

list_view = window.locator("#scroll_list")
list_view.list_item("Scrollable item 010").click()

tabs = window.locator("#main_tabs")
tabs.tab("Data").select()
```

When `visual_feedback` is enabled in the Qt agent and the client provides `agent_name`, the target window shows the current shared-agent overlay marker.

## Logging

QPlaywright uses the shared `qplaywright` logger namespace. If you want package logs on stderr or in a file, configure it once from Python:

```python
from qplaywright import configure_logging

configure_logging(level="DEBUG")
```

The Python agent `start_agent()` and the MCP server entrypoint also honor these environment variables:

```bash
QPLAYWRIGHT_LOG_LEVEL=DEBUG
QPLAYWRIGHT_LOG_FILE=qplaywright.log
```

When set, they enable package logging for `python -m qplaywright.mcp_server` and for Python apps that call `start_agent()`.

## MCP Server

Run the MCP server over stdio:

```bash
qplaywright-mcp
```

Or:

```bash
python -m qplaywright.mcp_server
```

Run the direct CLI / REPL when you want to keep issuing tool calls from one terminal session:

```bash
qplaywright-mcp cli
qplaywright> session {"action": "attach", "port": 19877}
qplaywright> window {"action": "list"}
qplaywright> find {"text": "Start", "limit": 1}
qplaywright> click {"target": "w12"}
```

Both direct `QPlaywright().connect(...)` and MCP `session attach` / `session launch`
now perform a formal protocol handshake immediately after the TCP connection is
established. If the remote agent reports a different `protocol_version`, the
connection is rejected immediately instead of failing later on the first tool call.
The sync client now also exposes public exception types such as `QPlaywrightConnectionError`,
`QPlaywrightProtocolError`, `QPlaywrightLookupError`, and `QPlaywrightActionError` so callers can
distinguish transport, handshake/setup, lookup, and post-resolution action failures without
string-matching exception messages.

Use `snapshot`, `find`, `resolve_object_names`, or `inspect` to observe the UI and capture widget handles first. Exact widget actions then reuse those stable handles.
Those handles remain valid across later observation calls, but you must rediscover them after the widget is destroyed or the session is replaced.
Use targeted `snapshot` when you want one subtree and several child handles in one call; use `find` when you want a short candidate list for one predicate; use `resolve_object_names` when one known subtree already exposes several deliberate stable `object_name` values.

You can also inspect CLI help and available MCP resources directly:

```bash
qplaywright-mcp cli help session
qplaywright-mcp cli resources
qplaywright-mcp cli resource list
qplaywright-mcp cli resource read qplaywright://help/selectors
```

The CLI also supports typed one-shot commands for common MCP flows:

```bash
qplaywright-mcp cli session attach --port 19877
qplaywright-mcp cli window select --title Dialog
qplaywright-mcp cli snapshot --depth 4 --topmost-only
qplaywright-mcp cli resolve_object_names --root w5 --object-name username --object-name password --object-name login_btn
qplaywright-mcp cli click w12 --count 2
qplaywright-mcp cli click --x 320 --y 180
qplaywright-mcp cli hover --x 320 --y 180
qplaywright-mcp cli input w7 123.45 --submit
qplaywright-mcp cli input w7 --mode clear
qplaywright-mcp cli focus w7 --include-state
```

When `click` or `hover` omits `target`, `x` and `y` are interpreted as coordinates relative to the active window.
Use `window select` first when the intended target window is not already active.

You can also run one tool call without starting the REPL:

```bash
qplaywright-mcp cli snapshot '{"depth": 4}'
```

Expose Streamable HTTP instead of stdio when needed:

```bash
python -m qplaywright.mcp_server --transport streamable-http
```

## 供 UI 开发使用的 Harness

当你希望 Qt UI 开发 agent 产出的界面能更高效地配合 qplaywright MCP 使用时，可以直接给它下面这段 harness 提示词：

```text
你是一个 Qt QWidget UI 开发 agent。你的目标不只是实现需求里的界面功能，还要让最终界面对 qplaywright MCP 来说容易观察、容易理解、容易稳定操作。

把自动化可用性视为一等设计目标。

请遵守以下规则：

1. 控件的 role 语义来自标准 Qt 控件类型，或者来自自定义控件显式声明的 qplaywrightClassMetadata.role。不要把控件 role 塞进 accessibleName。
2. accessibleName 是自动化场景下最主要的人类可理解语义名称。对于图标按钮、自绘控件、复合控件，以及无法通过原生可见文本 API 恢复语义的控件，都应优先提供 accessibleName。
3. accessibleDescription 用来补充说明控件做什么，或者它所在的业务上下文。它应该补充 accessibleName，而不是简单重复 accessibleName。
4. 不要默认把 objectName 当成稳定自动化标识。在很多 Qt 工程里，objectName 会被 QSS 样式复用，也可能出现重复。只有当 UI 明确把某个 objectName 设计成唯一 automation hook 时，才允许依赖它。
5. 对按钮、文本输入、复选框、单选框、下拉框、页签、表格、树、列表这类标准交互，优先使用标准 Qt 控件，这样 qplaywright 才能自然暴露正确的 role 和结构化行为。
6. 当你创建自定义业务控件或复合控件时，要暴露 qplaywrightClassMetadata 和清晰的 invoke 风格方法，用于结构化动作和状态读取。不要逼自动化依赖坐标点击、脆弱的文本匹配，或者临时拼凑的按键序列来完成业务操作。
7. 按 observe-then-act 的方式设计 UI：agent 应能先通过 snapshot、find、inspect、inspect_items 理解界面并拿到稳定 handle，再使用 click、input、choose、invoke 等精确动作。
8. 不要让关键流程依赖精确的用户可见文案，因为这些文案可能随着本地化或文案调整而变化。优先依赖 accessible 语义、标准 role、结构化方法，以及从观察结果里拿到的稳定 handle。
9. 给每个重要窗口和对话框提供清晰的 windowTitle。给重要交互控件提供清晰的 accessible 语义。如果某个 objectName 是专门给自动化使用的，就要明确表达这一点，并保证它在预期作用域内唯一。
10. 对 table、tree、list、tab 这类结构化界面，优先采用能被 qplaywright item inspection 稳定观察和寻址的结构，而不是自绘黑盒。
11. 不要为了保留脆弱的自动化表面去增加兼容层或并行旧路径，直接实现清晰的主路径。
12. 结束前输出一份 automation surface 摘要，至少列出：window titles、重要 accessibleName、刻意保留的 automation objectName hooks，以及通过 qplaywrightClassMetadata 暴露的自定义控件方法。

如果某个关键交互既没有清晰的 role，也没有 accessible 语义，也没有结构化方法表面，就把它视为 UI 尚未完成，并在当前改动里补齐。
```

同时根据项目类型提供 [自定义控件文档](docs/custom_widgets.md) 中的内容来展示如何实现自定义控件的 qplaywrightClassMetadata 和方法暴露。

## Packaging

Build wheel and sdist locally:

```bash
python -m build --no-isolation
```

When using `--no-isolation`, install the build backend into the current environment first:

```bash
python -m pip install -U setuptools wheel build
python -m build --no-isolation
```

In this repository, if you are using the checked-in virtual environment, run:

```bash
.venv\Scripts\python.exe -m pip install -U setuptools wheel build
.venv\Scripts\python.exe -m build --no-isolation
```

## Notes

- All widget operations must execute on the Qt main thread.
- The Python package has zero mandatory runtime dependencies.
- Qt bindings are imported lazily by the Python agent.
- The C++ agent is header-only, but because it contains `Q_OBJECT`, it must still be listed in your CMake sources for AUTOMOC.
- MCP uses a single active session and a single active window scope; use the `session` and `window` tools to switch explicitly.
- MCP window summaries and snapshot widget entries expose layout data through compact `geometry: [x, y, width, height]` arrays.
- Targeted MCP `inspect` responses expose compact `geometry`, `bounding_box`, and `global_bounding_box` arrays in the same `[x, y, width, height]` form.
- MCP observation/search surfaces still accept selector strings, but exact widget actions are handle-first and should reuse the stable handles returned by `snapshot`, `find`, `resolve_object_names`, or `inspect`.
- `topmost_only=true` is an approximate frontmost-visible filter for window-wide `snapshot` and targetless `inspect`; it may omit content.

## Additional Docs

- `docs/mcp.md`: current MCP server contract and tool surface
- `docs/concurrency.md`: GUI-thread ownership, dispatch boundaries, and sync client serialization rules
- `docs/custom_widgets.md`: explicit method-based custom widget automation contract
- `docs/accessibility_semantics.md`: recommended use of `accessibleName`, `accessibleDescription`, and future `accessibleIdentifier` for agent-friendly Qt UIs
