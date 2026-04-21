# QPlaywright MCP Server

QPlaywright can run as an MCP server on top of the existing Python sync client.
The Qt-side integration does not change: your target app still embeds the
qplaywright agent and exposes the same TCP protocol.

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

## Typical Tool Flow

1. `connect` to a running Qt app with an embedded qplaywright agent.
2. `list_windows` to discover the target top-level window.
3. `widget_tree` or `inspect_widget` to understand the UI structure.
4. Use action tools like `click`, `fill`, `type_text`, `set_checked`,
   `press_key`, `select_option`, `wait_for`, and `screenshot`.
5. `disconnect` when finished.

## End-to-End Demo

If you have PySide6 installed, you can run the full MCP flow against the demo
Qt application:

```bash
python examples/test_mcp_demo.py
```

The script starts `examples/demo_app.py`, launches the qplaywright MCP server as
an stdio subprocess, exercises several tools, and writes a screenshot to
`demo_mcp_screenshot.png`.

## OpenCode

如果你希望在 OpenCode 中把 qplaywright 作为本地 MCP 使用，请参考：

- [docs/opencode.md](docs/opencode.md)

## Selector Syntax

Supported selectors match the existing qplaywright syntax:

- `role=button`
- `text=Submit`
- `has-text=partial`
- `#objectName`
- `name=objectName`
- `.QLabel`

## Playwright MCP Compatibility

QPlaywright now exposes a compatibility subset using playwright-mcp style tool
names for the overlap that makes sense in a Qt widget application.

Available compatibility tools currently include:

- `browser_click`
- `browser_close`
- `browser_fill_form`
- `browser_hover`
- `browser_press_key`
- `browser_resize`
- `browser_select_option`
- `browser_snapshot`
- `browser_tabs`
- `browser_take_screenshot`
- `browser_type`
- `browser_verify_element_visible`
- `browser_verify_text_visible`
- `browser_verify_value`
- `browser_wait_for`

Important differences from browser automation:

- `target` expects a qplaywright selector such as `#login_btn` or `role=button`.
- `browser_snapshot` now returns stable snapshot refs such as `e1`, `e2`. These
  refs can be passed back into `browser_click`, `browser_type`,
  `browser_select_option`, `browser_take_screenshot`, and other compatibility
  tools on the same live connection.
- `browser_click`, `browser_fill_form`, `browser_hover`, `browser_press_key`,
  `browser_select_option`, and `browser_type` now return a fresh snapshot after
  the action, which is closer to playwright-mcp's iterative tool loop.
- `browser_tabs` is backed by top-level Qt windows, not browser tabs.
- Actions tied to web navigation, network inspection, DOM evaluation, cookies,
  storage, DevTools, PDF, or coordinate-based vision tools are intentionally not
  exposed because they do not map cleanly to a QWidget application.

## Playwright-Style Demo

You can also run the compatibility layer against the sample Qt app:

```bash
python examples/test_playwright_mcp_compat.py
```

## Claude Desktop Example

```json
{
  "mcpServers": {
    "qplaywright": {
      "command": "python",
      "args": [
        "-m",
        "qplaywright.mcp_server"
      ]
    }
  }
}
```

If your Python environment is not on PATH, replace `python` with the absolute
path to the interpreter that has `qplaywright[mcp]` installed.
