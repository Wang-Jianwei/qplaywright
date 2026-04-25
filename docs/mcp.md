# QPlaywright MCP Server

QPlaywright can run as an MCP server on top of the existing Python sync client.
The Qt-side integration does not change: your target app still embeds the
qplaywright agent and exposes the same TCP protocol.

本文件描述当前已经落地的终态 MCP 接口。
不再讨论兼容层、过渡别名或 playwright-mcp 风格工具。

## Install

```bash
pip install -e ".[mcp]"
```

## Run

For Claude Desktop, VS Code, and most local MCP hosts, use stdio:

```bash
python -m qplaywright.mcp_server
```

Or, if your environment exposes console scripts:

```bash
qplaywright-mcp
```

You can also expose Streamable HTTP:

```bash
python -m qplaywright.mcp_server --transport streamable-http
```

If you want to drive qplaywright directly from one terminal session without
writing throwaway Python scripts, start the built-in CLI / REPL:

```bash
qplaywright-mcp cli
```

Inside the REPL, use one tool call per line:

```text
qplaywright> session {"action": "attach", "port": 19877}
qplaywright> window {"action": "list"}
qplaywright> snapshot {"depth": 4}
qplaywright> click {"target": "text=Start"}
qplaywright> exit
```

Useful REPL meta commands:

- `.tools` lists all available tools
- `.resources` lists CLI-exposed MCP resources
- `.help` shows CLI usage
- `.help TOOL` shows one tool signature and docstring

You can also execute one tool directly without entering the REPL:

```bash
qplaywright-mcp cli snapshot '{"depth": 4}'
```

Or inspect help and read a resource from one-shot CLI commands:

```bash
qplaywright-mcp cli help session
qplaywright-mcp cli resources
qplaywright-mcp cli resource '{"uri": "qplaywright://help/selectors"}'
```

## Typical Tool Flow

1. `session` with `action="attach"` or `action="launch"` to establish the active session.
2. `window` with `action="list"` to discover visible top-level windows.
3. `window` with `action="select"` when the desired scope is not the current active window.
4. `snapshot` or `inspect` to understand the current UI and obtain stable refs.
5. Use action tools like `click`, `input`, `invoke`, `set_checked`, `press_key`, `hover`, `scroll`, `choose`, `wait`, and `screenshot`.
6. `session` with `action="close"` when finished.

## Exposed MCP Interfaces

### Resource

The MCP server currently exposes one resource:

- `qplaywright://help/selectors`: selector syntax and recommended workflow

### Transports

The server can be exposed through:

- `stdio`
- `streamable-http`

### Tool Surface

| Tool | Purpose |
| --- | --- |
| `session` | Attach, launch, inspect status, or close the active MCP-side session |
| `window` | List, select, resize, or close one top-level Qt window |
| `snapshot` | Return a text snapshot and stable refs for the active window or one target |
| `inspect` | Inspect one target or return the active window widget tree in debug mode |
| `click` | Click or double-click the first matched widget |
| `input` | Replace or append text, optionally submitting with Enter |
| `invoke` | Invoke one exposed custom widget method by exact name |
| `press_key` | Send one key press to the matched widget |
| `set_checked` | Check or uncheck the matched widget |
| `choose` | Select one combobox option by `value`, `index`, or `label` |
| `wait` | Wait until a widget reaches a supported state |
| `screenshot` | Capture a screenshot of the active window or a matched widget |
| `hover` | Hover over the first matched widget |
| `scroll` | Send a mouse wheel scroll event to the matched widget |

## Core Model

### Single Active Session

One MCP server instance manages one active qplaywright session.
There is no per-tool `connection` routing anymore.
If you need to automate multiple targets in parallel, start multiple MCP server instances.

### Single Active Window Scope

Most tools operate inside the current active window scope.
Use `window` with `action="select"` to change that scope explicitly.
After actions, the server updates the active window tracking automatically.

Window summaries exposed through `session`, `window`, and post-action observation
use one layout field:

- `geometry: {x, y, width, height}`

There is no parallel top-level `width` / `height` return shape anymore.

### Unified Target

Widget-oriented tools accept a single `target` value.
That value may be either:

- a qplaywright selector such as `#amount_editor`, `role=button`, `text=Submit`, or `.QLabel`
- a snapshot ref such as `e12`

The selector side of `target` keeps the existing atomic qplaywright forms.
This contract does not define inline composite syntax such as `role=button >> has-text=Submit`.
When you need compound disambiguation, use `snapshot` or `inspect` first, then continue with the returned snapshot ref.

### Optional Post-Action Observation

Action tools support `include_snapshot=false` by default.
When `include_snapshot=true`, the response also includes:

- `window_changed`
- `active_window`
- `snapshot`
- `refs`

## Tool Details

### session

Request:

```json
{
  "action": "attach",
  "port": 19876,
  "host": "127.0.0.1",
  "timeout": 30.0
}
```

Supported actions:

- `attach`
- `launch`
- `status`
- `close`

`launch` additionally accepts:

```json
{
  "action": "launch",
  "executable": "D:/path/to/app.exe",
  "args": []
}
```

`attach`, `launch`, and `status` return `active_window` when one is available.
That window summary uses:

- `wid`
- `title`
- `class`
- `geometry`
- `is_active`
- `is_modal`

### window

Request:

```json
{
  "action": "select",
  "index": 1
}
```

Supported actions:

- `list`
- `select`
- `resize`
- `close`

If `select` or `close` changes the active window, previously issued snapshot refs are cleared and should be treated as expired.

Selection fields:

- `wid`
- `title`
- `index`

Resize also requires:

- `width`
- `height`

`list`, `select`, `resize`, and `close` return window summaries using:

- `wid`
- `title`
- `class`
- `geometry`
- `is_active`
- `is_modal`

### snapshot

Request:

```json
{
  "target": null,
  "depth": 10,
  "topmost_only": false,
  "save_to": "snapshot.txt"
}
```

Response includes:

- `session`
- `window`
- `target`
- `snapshot`
- `refs`
- optional `warnings`
- optional `save_to`

Each snapshot ref entry includes:

- `ref`
- `wid`
- `target`
- `class`
- `geometry`
- any meaningful semantic label fields such as `text`, `accessibleName`, `currentText`, `windowTitle`, or `value`

When `topmost_only=true` and `target` is omitted, the result is an approximate
frontmost-visible view. It may omit widgets or content and returns a warning to
make that limitation explicit.

### inspect

Request:

```json
{
  "target": "#amount_editor",
  "include_methods": true,
  "property": "placeholderText"
}
```

When `target` is omitted, `inspect` returns the active window tree in debug mode.
When `target` is provided, `inspect` returns widget state and optional method metadata.
If multiple widgets match the target, scalar fields describe the first match and `count` reports the total number of matches.

Targeted `inspect` may include:

- `geometry` for widget-local layout data
- `globalBoundingBox` for screen-space bounds
- `bounding_box` as the existing locator-compatible bounding box field

When `target` is omitted and `topmost_only=true`, the returned tree is an
approximate frontmost-visible view and may be incomplete.

### Action Tools

Common action request shape:

```json
{
  "target": "e12",
  "include_snapshot": true
}
```

Tool-specific fields:

- `click`: optional `count`
- `input`: `text`, optional `mode`, `delay`, `submit`
- `invoke`: `method`, optional `args`
- `press_key`: `key`
- `set_checked`: `checked`
- `choose`: exactly one of `value`, `index`, or `label`
- `wait`: optional `state`, `timeout`
- `hover`: no extra fields
- `scroll`: optional `delta_x`, `delta_y`

### screenshot

Request:

```json
{
  "target": "#chart_view",
  "path": "chart.png",
  "x": 10,
  "y": 20,
  "width": 300,
  "height": 200
}
```

When `target` is omitted, the current active window is captured.
When clipping fields are provided, all of `x`, `y`, `width`, and `height` must be present.
When `path` is omitted, the response returns inline PNG data in `data` instead of a saved file path.

## End-to-End Demo

If you have PySide6 installed, you can run the full MCP flow against the demo
Qt application:

```bash
python examples/test_mcp_demo.py
```

The script starts `examples/demo_app.py`, launches the qplaywright MCP server as
an stdio subprocess, exercises several tools, and writes a screenshot to
`demo_mcp_screenshot.png`.

If you want a concrete dialog example, run:

```bash
python examples/test_dialog_mcp_demo.py
```

This script opens a real `QDialog`, verifies it appears as a second top-level
window, fills and selects controls inside the dialog, clicks the approve
button, and then asserts that the dialog closes and the main window reflects
the review result.

## OpenCode

如果你希望在 OpenCode 中把 qplaywright 作为本地 MCP 使用，请参考：

- [docs/opencode.md](docs/opencode.md)

## Selector Syntax

Supported selectors match the existing qplaywright syntax:

- `role=button`
- `text=Submit`
- `has-text=partial`
- `a11y-name=Submit`
- `a11y-desc=Help text`
- `#objectName`
- `name=objectName`
- `.QLabel`

Composite selector grammar is intentionally not part of the current contract.
For cases like "button whose text contains Submit", first discover the right widget with `snapshot` or `inspect`, then reuse its snapshot ref.
