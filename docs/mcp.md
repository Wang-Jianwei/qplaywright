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

## Exposed MCP Interfaces

### Resource

The MCP server currently exposes one resource:

- `qplaywright://help/selectors`: selector syntax and recommended workflow

### Transports

The server can be exposed through:

- `stdio`
- `streamable-http`

### Native qplaywright Tools

These are the primary MCP tools backed directly by the qplaywright sync client:

| Tool | Purpose |
|---|---|
| `connect` | Connect to a running Qt app that already embedded the qplaywright agent |
| `launch` | Launch a Qt executable with agent support and connect to it |
| `disconnect` | Close one MCP-managed connection |
| `list_live_connections` | List all live connections tracked by the MCP server |
| `list_windows` | List visible top-level windows |
| `widget_tree` | Return the current visible widget tree |
| `inspect_widget` | Inspect selector match state such as text, value, visibility, checked state, and optional methods |
| `get_widget_methods` | Return custom widget method metadata from `qplaywrightClassMetadata` |
| `click` | Click or double-click the first matched widget |
| `fill` | Clear and fill the first matched editable widget |
| `invoke_widget_method` | Invoke one exposed custom widget method by exact name |
| `type_text` | Type text without clearing existing content |
| `press_key` | Send one key press to the matched widget |
| `set_checked` | Check or uncheck the matched widget |
| `select_option` | Select one combobox option by `value`, `index`, or `label` |
| `wait_for` | Wait until a widget reaches a supported state |
| `screenshot` | Capture a screenshot of a window or matched widget |
| `resize_window` | Resize a top-level window |
| `close_window` | Close a top-level window |
| `hover` | Hover over the first matched widget |

### playwright-mcp Compatibility Tools

These tools provide a compatibility subset for hosts that expect playwright-mcp
style names and iterative snapshot-driven interaction:

| Tool | Purpose |
|---|---|
| `browser_click` | Click a widget using `target` or a snapshot ref |
| `browser_close` | Close the current top-level Qt window |
| `browser_fill_form` | Fill multiple fields in one call |
| `browser_hover` | Hover over a widget |
| `browser_press_key` | Press a key on a widget |
| `browser_resize` | Resize the current window |
| `browser_select_option` | Select one combobox option |
| `browser_snapshot` | Return a text snapshot of the widget tree or a targeted widget |
| `browser_tabs` | List, select, or close top-level Qt windows through a tabs-like API |
| `browser_take_screenshot` | Capture a screenshot of the current window or a targeted widget |
| `browser_type` | Fill or type into an editable widget and optionally submit |
| `browser_wait_for` | Wait by time or wait for text to appear or disappear in the snapshot |
| `browser_verify_element_visible` | Assert that a visible widget exists for a role plus accessible/displayed name |
| `browser_verify_text_visible` | Assert that a text fragment is visible in the current snapshot |
| `browser_verify_value` | Assert the current widget value equals the expected value |

### Current Compatibility Constraints

The compatibility layer is intentionally narrow where QWidget semantics do not
cleanly match browser semantics:

- `browser_click` currently supports left click only
- `browser_click` does not support modifier-assisted clicks yet
- `browser_tabs` supports `list`, `select`, and `close`, but not `new`
- `browser_select_option` currently supports selecting one value at a time
- `browser_take_screenshot` does not distinguish viewport and full-page capture
- DOM, network, cookies, storage, JS evaluation, DevTools, PDF, and vision-style browser tools are not exposed

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
