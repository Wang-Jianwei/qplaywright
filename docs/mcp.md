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
qplaywright> inspect {"target": "text=Start"}
qplaywright> click {"target": "w12"}
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
qplaywright-mcp cli resource list
qplaywright-mcp cli resource read qplaywright://help/selectors
```

The CLI also supports typed subcommands for common MCP flows:

```bash
qplaywright-mcp cli session attach --port 19877
qplaywright-mcp cli session status
qplaywright-mcp cli session launch D:/path/to/app.exe -- --flag
qplaywright-mcp cli window list
qplaywright-mcp cli window select --title Dialog
qplaywright-mcp cli snapshot --depth 4 --topmost-only
qplaywright-mcp cli click w12 --count 2
qplaywright-mcp cli click --x 320 --y 180
qplaywright-mcp cli hover --x 320 --y 180
qplaywright-mcp cli input w7 123.45 --submit
```

`session attach` and `session launch` perform a formal protocol handshake as
part of connection setup. A reachable agent with a mismatched
`protocol_version` is rejected immediately; attach does not fall through to a
partially connected session.

Use `snapshot`, `find`, `resolve_object_names`, or `inspect` to observe the UI and capture widget handles first. Exact widget actions then reuse those stable handles.
Use targeted `snapshot` when you want one subtree and several child handles in one call; use `find` when you want a short candidate list for one predicate; use `resolve_object_names` when one known subtree already exposes several deliberate stable `object_name` values.

When `click` or `hover` omits `target`, `x` and `y` are interpreted as coordinates relative to the active window.
If the active window is not the desired scope, switch it first with `window select`.

## Typical Tool Flow

1. `session` with `action="attach"` or `action="launch"` to establish the active session through TCP connect plus formal protocol handshake.
2. `window` with `action="list"` to list visible top-level windows.
3. `window` with `action="select"` when the desired scope is not the current active window.
4. `snapshot`, `find`, `resolve_object_names`, or `inspect` to understand the widget tree and obtain stable handles.
5. `inspect_items` when the target widget is a table, tree, or list and you need structured descendant item targets.
6. Use action tools like `click`, `input`, `invoke`, `set_expanded`, `press_key`, `hover`, `scroll`, `choose`, `wait`, and targeted `screenshot` with those handles, or reuse the structured item targets returned by `inspect_items`.
7. `session` with `action="close"` when finished.

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
| `inspect` | Inspect one widget or item target, or return the active window widget tree in debug mode |
| `resolve_object_names` | Resolve several exact `object_name` values to stable handles under one known root scope |
| `inspect_items` | Enumerate structured table/tree/list/tab descendants for one owner widget |
| `click` | Click or double-click one stable-handle widget, one item target, or one active-window coordinate |
| `input` | Replace or append text, optionally submitting with Enter |
| `invoke` | Invoke one exposed custom widget method by exact name |
| `press_key` | Send one key press to one stable-handle widget |
| `set_expanded` | Expand or collapse one structured tree node item target |
| `choose` | Select one combobox option by `value`, `index`, or `label` |
| `wait` | Wait until a widget or item target reaches a supported state |
| `screenshot` | Capture a screenshot of the active window or one stable-handle widget |
| `hover` | Hover over one stable-handle widget, one item target, or one active-window coordinate |
| `scroll` | Send a mouse wheel scroll event to one stable-handle widget |

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

- `geometry: [x, y, width, height]`

There is no parallel top-level `width` / `height` return shape anymore.

### Target Rules

Observation and search tools accept a single `target` value.
That value may be either:

- a stable widget handle such as `w12`
- a qplaywright selector such as `#amount_editor`, `role=button`, `text=Submit`, or `.QLabel`
- a structured item target object such as `{"owner": "w12", "item": {"kind": "table_cell", "row": 3, "column": 1}}`
- a structured item target object such as `{"owner": "w9", "item": {"kind": "tree_node", "path": [0, 1]}}`
- a structured item target object such as `{"owner": "w5", "item": {"kind": "list_item", "row": 2}}`
- a structured item target object such as `{"owner": "w3", "item": {"kind": "tab_item", "index": 1}}

Exact widget actions use the same `target` parameter name, but for widgets they only accept stable handles such as `w12`.
That applies to `click`, `input`, `invoke`, `press_key`, `hover`, `scroll`, `choose`, `wait`, and targeted `screenshot`.
Selectors remain valid for observation/search scopes such as `snapshot`, `find`, `inspect`, and `inspect_items` owner resolution.

The selector side keeps the existing atomic qplaywright forms.
This contract does not define inline composite syntax such as `role=button >> has-text=Submit`.
When you need compound disambiguation, use `snapshot`, `find`, or `inspect` first, then continue with the returned stable handle.
When you need structured item descendants, first resolve the owner widget, then call `inspect_items` and reuse the returned item `target` objects.

### Optional Post-Action Observation

Action tools support `include_snapshot=false` by default.
When `include_snapshot=true`, the response also includes `observation`, where:

- `observation.root_handle`
- `observation.widgets`

`window_changed` and `active_window` remain top-level action result fields.

Action tools also support `include_state=false` by default.
When `include_state=true`, the response includes a compact target-level `state`
payload.

- widget targets may return compact widget fields such as `exists`, `count`, `visible`, `enabled`, `checked`, `text`, `current_text`, `value`, `object_name`, `class`, `accessible_name`, `accessible_description`, `geometry`, `bounding_box`, `global_bounding_box`, and `attribute`
- item targets may return compact item fields such as `exists`, `count`, `kind`, `row`, `column`, `path`, `visible`, `text`, `edit_value`, `selected`, `expanded`, `bounding_box`, and `global_bounding_box`

All layout and box arrays use `[x, y, width, height]` in that fixed order.
The optional `attribute` object groups exceptional widget flags such as `{"transparent_for_mouse_events": true}`.

`include_state` is intentionally compact. It is not a replacement for full `snapshot`
or the richer widget/item payloads returned by `inspect` and `inspect_items`.

`include_state` and `include_snapshot` are independent and may both be `true`
in the same request.

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

`attach` and `launch` only succeed after the remote agent completes the formal
handshake and reports the same `protocol_version` as the client.

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

`window select` only updates the server's active-window scope. Session-stable widget handles are not invalidated just because the active window changes.

Selection fields:

- `wid`
- `title`
- `index`

Resize also requires:

- `width`
- `height`

All returned window summaries use:

- `wid`
- `title`
- `class`
- `geometry`
- `is_active`
- `is_modal`

`window list` returns both `windows` and `active_window`.
`window select`, `window resize`, and `window close` return `active_window`.

### snapshot

Request:

```json
{
  "target": null,
  "depth": 10,
  "topmost_only": false,
  "include_infrastructure": false,
  "save_to": "snapshot.txt"
}
```

Response includes:

- `session`
- `window`
- `target`
- `root_handle`
- `widgets`
- optional `warnings`
- optional `save_to`

Each snapshot widget entry includes:

- `handle`
- `class`
- optional compact `geometry`
- optional `attribute`
- optional sparse negative-state fields `visible`, `enabled`, and `interactable`, emitted only when the value is `false`
- any meaningful semantic label fields such as `text`, `accessible_name`, `current_text`, `window_title`, or `value`

`snapshot` is JSON-first: use `widgets` plus `root_handle` as the primary observation result.
When `save_to` is provided, qplaywright also writes an internal text snapshot export to the target file.

`handle` is the exact follow-up identity for widget actions.
`geometry` uses `[x, y, width, height]`, and `attribute` wraps exceptional widget flags such as `{"transparent_for_mouse_events": true}`.

Stable widget handles are session-stable. They survive later `snapshot`, `find`, and `inspect` calls, and only fail
once the widget is destroyed or the session is replaced.

Use `snapshot(target=..., depth=N)` when you already know a container or owner widget and want to inspect a local subtree in one round-trip.
Use `find` when you already have one narrowing predicate such as `object_name`, `text`, `role`, or `has_text` and want a small candidate set instead of a subtree dump.
Use `resolve_object_names` when a known subtree exposes several deliberate `object_name` values and you want those exact handles in one round-trip.

When `topmost_only=true` and `target` is omitted, the result is an approximate
frontmost-visible view. It may omit widgets or content and returns a warning to
make that limitation explicit.
By default, `snapshot` filters common Qt infrastructure widgets such as internal
scroll-area support nodes. Set `include_infrastructure=true` when you need the
raw tree for debugging.

### find

Request:

```json
{
  "root": "#payment_panel",
  "role": "button",
  "has_text": "Submit",
  "visible": true,
  "limit": 5
}
```

`find` performs server-side widget search within one root scope and returns a
small deterministic candidate set. Response fields include:

- `root_handle`
- `count`
- `truncated`
- `results`, where each entry includes `handle`, `class`, optional semantic fields,
  compact decision fields, `match_reason`, and optional `ancestor_summary`

Current `results[]` entries are intentionally small, but they carry enough context
for the next decision step without forcing an immediate `inspect` on every candidate.
Typical fields include:

- `object_name`, `label`, `text`, `accessible_name`, `current_text`
- `visible`, `enabled`, `interactable`
- `geometry`
- `match_reason`
- `ancestor_summary`

`find` is still a search tool, not a full inspect payload. If you need methods,
properties, or exact target-level state, follow up with `inspect` on the chosen handle.

### resolve_object_names

Request:

```json
{
  "root": "#login_form",
  "object_names": ["username", "password", "login_btn"],
  "depth": 6
}
```

`resolve_object_names` inspects one root subtree and resolves several exact
`QObject::objectName()` values in one call. It is intentionally narrower than
`find`:

- use it only when the subtree already exposes deliberate stable `object_name` values
- it does not guess between duplicates; duplicated names are returned under `ambiguous`
- misses are returned under `missing`

Response fields include:

- `root_handle`
- `requested`
- `handles`, mapping uniquely resolved `object_name` values to stable handles
- `resolved`, mapping uniquely resolved `object_name` values to compact widget entries
- `missing`
- `ambiguous`

This is the fastest path when an agent already knows a form or panel root and
needs several exact child handles before calling `input`, `click`, or `choose`.

### inspect

Request:

```json
{
  "target": "#amount_editor",
  "include_methods": true,
  "property": "placeholderText",
  "include_infrastructure": false
}
```

When `target` is omitted, `inspect` returns the active window tree in debug mode.
When `target` is provided, `inspect` returns widget or item-target state.
If multiple widgets match the target, scalar fields describe the first match and `count` reports the total number of matches.
When `target` is omitted, `inspect` filters common Qt infrastructure widgets by default.
Set `include_infrastructure=true` to inspect the unfiltered raw widget tree.
For structured item targets, `inspect` returns item metadata such as `kind`, `row`, `column`, `path`, `selected`, `expanded`, and `edit_value` when those fields apply.

Targeted `inspect` may include:

- `geometry` for widget-local layout data
- `global_bounding_box` for screen-space bounds
- `bounding_box` as the existing locator-compatible bounding box field
- `attribute` for structured exceptional widget flags such as `{"transparent_for_mouse_events": true}`

### inspect_items

Request:

```json
{
  "target": "w9",
  "max_depth": 3,
  "max_items": 50
}
```

`inspect_items` enumerates structured descendants for one table, tree, list, or tab owner widget.
Each returned entry includes an `item` descriptor plus a reusable `target` object in the form `{owner, item}`.
Use those returned `target` objects directly with `inspect`, `click`, `hover`, `wait`, and `set_expanded`.
Stable widget handles remain widget-only; structured item targets come from `inspect_items`.
When `snapshot` or widget-tree `inspect` encounters a table, tree, or list owner widget, it may include an `itemView`
hint so the next step is explicit instead of implying that per-cell delegates are normal widget descendants.

For table, tree, and list items, `text` remains the display-facing model value.
When an item is actively being edited and the live editor value differs, the same
entry may also include `edit_value`. This lets an agent distinguish committed model
state from an in-flight editor state such as `text="Active"` with `edit_value="Pending"`.

Use `target` to name the owner widget you want to enumerate.

### Action Tools

Common action request shape:

```json
{
  "target": "w12",
  "include_state": false,
  "include_snapshot": true
}
```

For item-view descendants, the same `target` field may be a structured object:

```json
{
  "target": {
    "owner": "w9",
    "item": {"kind": "tree_node", "path": [0, 1]}
  },
  "include_state": true
}
```

Tool-specific fields:

- `click`: optional `count`, or `x` + `y` together when `target` is omitted
- `input`: `text`, optional `mode`, `delay`, `submit`
- `invoke`: `method`, optional `args`
- `press_key`: `key`
- `set_expanded`: `expanded` for structured tree node item targets only
- `choose`: exactly one of `value`, `index`, or `label`
- `wait`: optional `state` or `condition` + `expected`, optional `timeout`; item targets support `visible`/`hidden` and `text_equals`/`text_contains`
- `hover`: optional `x` + `y` together when `target` is omitted
- `scroll`: optional `delta_x`, `delta_y`

For checkable widgets, use `click` or `press_key` on the resolved handle, then confirm the resulting state with `wait(condition="checked_equals", expected=true|false)` or `inspect`.

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
When `path` is omitted, the MCP server writes the capture to a managed temporary PNG file and returns that file path.
These managed screenshot files live under a dedicated qplaywright temp directory and are cleaned up when the MCP server exits.

## Item Views And Snapshot

`snapshot` and targetless `inspect` serialize the real QWidget tree.
For item views, that means:

- real child widgets such as persistent editors or `setIndexWidget()` content can appear when Qt has actually created them
- paint-only delegates and non-persistent editors do not appear as widgets, because they are not stable QWidget descendants
- item-view owner widgets may expose `itemView: {kind, discoverableBy}` to point you to `inspect_items`

If you need table cells, tree nodes, or list rows reliably, use `inspect_items` first instead of expecting `snapshot`
to materialize delegate-painted item content as standalone widgets.

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
Selectors are for observation/search scopes, not exact widget actions.
For cases like "button whose text contains Submit", first narrow to the right widget with `snapshot`, `find`, or `inspect`, then reuse its stable handle.
For structured item interactions, resolve the owner widget first and prefer its stable handle in the item target object.
