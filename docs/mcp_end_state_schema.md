# QPlaywright MCP End-State Schema

本文档是 [docs/mcp_end_state.md](docs/mcp_end_state.md) 的配套契约附录。

前者回答“为什么这样设计”，本文档回答“每个终态工具到底长什么样”。

本文档描述的是终态目标接口，不要求当前代码已经完全实现。

## Conventions

- JSON 字段统一使用 `snake_case`
- 成功响应统一包含 `ok: true`
- 除非特别说明，目标工具在 `target` 匹配多个控件时不报错，而是返回第一个匹配项的标量字段，同时用 `count` 暴露总匹配数
- widget discovery / observation scope 可以接受 stable handle 或原子 selector；exact widget action target 只接受 stable handle；需要复合条件时，先用 `snapshot`、`find` 或 `inspect` 缩小范围，再使用 stable handle
- `target`、`root`、`owner` 表示请求里的可解析目标 spec；`handle`、`root_handle`、`owner_handle` 表示响应里的已解析 stable widget identity
- 布尔状态字段统一使用 `visible`、`enabled`、`checked`、`selected`、`interactable` 这类形容词形式，不再并行维护 `is_visible`、`is_enabled` 一类别名

## Request Model

除 `session` 和 `window` 之外，终态工具默认都是单一意图工具，不再额外包一层 `action`。

终态工具分为三类：

1. 资源工具：`session`、`window`
2. 观察工具：`snapshot`、`find`、`inspect`、`inspect_items`、`screenshot`
3. 动作工具：`click`、`input`、`choose`、`set_checked`、`press_key`、`hover`、`scroll`、`invoke`、`wait`

## Value Types

### Widget Observation/Search Target

观察或搜索工具里的 widget `target` 使用统一字符串参数。

类型：`string`

解释规则：

1. 如果值匹配当前 stable handle 形状，例如 `w12`，按 stable handle 解析。
2. 否则按 qplaywright selector 解析。

适用范围：`snapshot.target`、`inspect.target`、`find.root` 的 widget scope，以及其他仅用于观察或搜索的 widget 入口。

示例：

- `w12`
- `#amount_editor`
- `role=button`
- `text=保存`

补充说明：

- 终态契约中的 selector 仍沿用 qplaywright 的单表达式语法，例如 `role=button`、`text=保存`、`has-text=partial`
- 终态契约当前不定义 `role=button >> has-text=Submit` 或 `role=button[has-text=Submit]` 这类复合语法
- 当需要“角色 + 文本”等复合定位时，推荐流程是先 `snapshot`、`find` 或 `inspect` 观察并拿到 stable handle，再继续动作

### Widget Action Target

exact widget action 也使用 `target` 这个字段名，但它只接受 stable handle。

类型：`string`

解释规则：

1. 值必须匹配当前 stable handle 形状，例如 `w12`。
2. 不再对 widget action target 做 selector 回退解析。

适用范围：`click`、`input`、`choose`、`set_checked`、`press_key`、`hover`、`scroll`、`invoke`、`wait`、targeted `screenshot` 等 exact widget 工具。

示例：

- `w12`
- `w48`

### Root / Owner

`root` 和 `owner` 与 `target` 一样，都是字符串形态的可解析目标 spec。

- `root` 用于 widget 搜索或局部观察 scope
- `owner` 用于 table/tree/list/tab 这类 item-view owner widget

它们的解析规则与 widget observation/search target 一致：优先解析 stable handle，否则按 selector 解析。

### Rect Array

所有紧凑矩形数组统一使用 `[x, y, width, height]`。

适用字段：

- `geometry`
- `bounding_box`
- `global_bounding_box`

该顺序是正式契约的一部分，调用方不得自行猜测或重排。

### Include Snapshot

大多数动作工具支持：

- `include_snapshot: boolean = false`

当为 `true` 时，返回值附带 post-action snapshot 字段。

### Timeout

除特别说明外，`timeout` 的单位统一为秒，类型为 `number`。

### WindowInfo

```json
{
  "wid": 9,
  "title": "Confirm",
  "class": "QDialog",
  "index": 1,
  "is_active": true,
  "is_modal": true,
  "geometry": [120, 80, 480, 320]
}
```

字段说明：

- `wid`: agent 侧窗口标识
- `title`: 窗口标题
- `class`: Qt 类名
- `index`: 当前窗口列表中的索引
- `is_active`: 是否为当前 active window
- `is_modal`: 是否为模态窗口
- `geometry`: 窗口布局数据，统一使用 `[x, y, width, height]`

### SnapshotWidgetEntry

```json
{
  "handle": "w12",
  "class": "FancyAmountEdit",
  "object_name": "amount_editor",
  "text": "123.45",
  "geometry": [12, 48, 220, 80]
}
```

补充说明：

- `handle` 是 exact widget follow-up action 的稳定标识
- `attribute` 为可选字段，用于承载特殊属性，例如 `{"transparent_for_mouse_events": true}`
- `geometry` 遵循 `Rect Array` 的固定槽位语义

### WidgetTreeNode

`inspect(target=null)` 的 debug tree 模式返回结构化节点，而不是文本快照。

```json
{
  "wid": 103,
  "class": "FancyAmountEdit",
  "objectName": "amount_editor",
  "text": "123.45",
  "visible": true,
  "enabled": true,
  "checked": false,
  "geometry": [12, 48, 220, 80],
  "children": []
}
```

该结构对应当前 `widget_tree` 所返回的 JSON 风格，只是在终态中降级为 debug-only 能力。

### ActionObservation

当动作工具传入 `include_snapshot=true` 时，附加以下结构：

```json
{
  "window_changed": true,
  "active_window": {
    "wid": 9,
    "title": "Confirm",
    "class": "QDialog",
    "index": 1,
    "is_active": true,
    "is_modal": true,
    "geometry": [120, 80, 480, 320]
  },
  "snapshot": "...",
  "root_handle": "w9",
  "widgets": []
}
```

其中 `widgets` 的元素类型为 `SnapshotWidgetEntry[]`。

字段说明：

- `window_changed`: 本次动作后 active window 是否变化
- `active_window`: 当前 active window 摘要
- `snapshot`: post-action 文本快照
- `root_handle`: post-action snapshot 的根 handle
- `widgets`: 与该快照一致的 widget handle 集

## Error Model

MCP 工具失败时应返回明确、可操作的错误信息。

推荐错误类别：

- no active session
- target not found
- target ambiguous
- invalid argument
- invalid state
- timeout
- window changed
- stale handle
- invoke failed
- agent disconnected

推荐错误消息要求：

1. 明确指出失败对象
2. 明确指出失败原因
3. 尽量给出下一步动作建议

## Session

工具名：`session`

职责：管理当前 active session。

### Session Request

```json
{
  "action": "attach | launch | close | status",
  "host": "127.0.0.1",
  "port": 19876,
  "timeout": 30.0,
  "executable": "D:/path/to/app.exe",
  "args": []
}
```

字段约束：

- `action` 必填
- `attach` 需要 `port`，`host` 默认为 `127.0.0.1`
- `launch` 需要 `executable`
- `close` 不需要额外参数
- `status` 不需要额外参数

### Session Response: Attach Or Launch

```json
{
  "ok": true,
  "action": "attach",
  "session": {
    "host": "127.0.0.1",
    "port": 19876,
    "connected": true,
    "launched_executable": null
  },
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  }
}
```

### Session Response: Close

```json
{
  "ok": true,
  "action": "close",
  "closed": true
}
```

### Session Response: Status

```json
{
  "ok": true,
  "action": "status",
  "session": {
    "host": "127.0.0.1",
    "port": 19876,
    "connected": true,
    "launched_executable": null
  },
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  }
}
```

## Window

工具名：`window`

职责：管理当前 session 下的顶层窗口。

### Window Request

```json
{
  "action": "list | select | close | resize",
  "index": 0,
  "wid": 1,
  "title": "Confirm",
  "width": 800,
  "height": 600
}
```

字段约束：

- `list` 不需要额外参数
- `select` 需要 `index` 或 `wid` 或 `title` 三选一
- `close` 可选 `index` 或 `wid` 或 `title`，缺省时关闭当前 active window
- `resize` 需要 `width` 和 `height`，并可选窗口定位参数；缺省作用于当前 active window

### Window Response: List

```json
{
  "ok": true,
  "action": "list",
  "windows": []
}
```

其中 `windows` 的元素类型为 `WindowInfo[]`。

### Window Response: Select

```json
{
  "ok": true,
  "action": "select",
  "active_window": {
    "wid": 9,
    "title": "Confirm",
    "class": "QDialog",
    "index": 1,
    "is_active": true,
    "is_modal": true,
    "geometry": [120, 80, 480, 320]
  }
}
```

### Window Response: Close Or Resize

```json
{
  "ok": true,
  "action": "resize",
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 800, 600]
  }
}
```

补充说明：

- 当 `action="close"` 且关闭的是当前 active window 时，服务端应自动把 `active_window` 切换到下一个可见窗口
- 如果没有剩余可见窗口，则 `active_window` 允许为 `null`
- 当 `close` 导致 active window 变化时，active window 作用域随之更新；已有 stable handle 不会仅因切窗而整体失效

## Snapshot

工具名：`snapshot`

职责：返回当前窗口或某个目标的文本快照和稳定 handles。

### Snapshot Request

```json
{
  "target": "w12",
  "depth": 8,
  "topmost_only": false,
  "include_infrastructure": false,
  "save_to": "snapshot.txt"
}
```

字段约束：

- `target` 可选，缺省表示当前 active window
- `depth` 默认为 `10`
- `topmost_only` 默认为 `false`，仅对 window-wide snapshot 有意义
- `include_infrastructure` 默认为 `false`，用于控制是否保留 qplaywright overlay/debug/support widgets
- `save_to` 可选，表示把文本快照写入文件，而不是保存图片

### Snapshot Response

```json
{
  "ok": true,
  "session": {
    "connected": true,
    "host": "127.0.0.1",
    "port": 19876,
    "launched_executable": null
  },
  "window": {
    "handle": "w1",
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "geometry": [0, 0, 640, 720]
  },
  "target": null,
  "root_handle": "w1",
  "snapshot": "...",
  "widgets": [],
  "warnings": [
    "topmost_only is an approximate frontmost-visible filter and may omit widgets or content. Rerun with topmost_only=false when you need a complete tree."
  ],
  "save_to": "snapshot.txt"
}
```

其中 `widgets` 的元素类型为 `SnapshotWidgetEntry[]`。
当 `topmost_only=true` 且 `target=null` 时，`warnings` 应明确指出结果可能不完整。

## Find

工具名：`find`

职责：在给定 scope 下做结构化 widget 搜索。

### Find Request

```json
{
  "root": "w12",
  "role": "button",
  "text": null,
  "has_text": "Submit",
  "class": null,
  "object_name": null,
  "accessible_name": null,
  "visible": true,
  "enabled": true,
  "interactable": true,
  "include_infrastructure": false,
  "limit": 5
}
```

字段约束：

- `root` 可选，缺省表示当前 active window
- 所有显式启用的谓词按 AND 关系求交
- `include_infrastructure` 默认为 `false`
- `limit` 为正整数，服务端不得返回超额候选

### Find Response

```json
{
  "ok": true,
  "root_handle": "w12",
  "count": 1,
  "truncated": false,
  "results": [
    {
      "handle": "w48",
      "class": "QPushButton",
      "object_name": "submit_btn",
      "text": "Submit",
      "geometry": [310, 412, 96, 28],
      "match_reason": ["role=button", "has_text~=Submit", "visible=true", "enabled=true", "interactable=true"],
      "ancestor_summary": [
        {"handle": "w12", "class": "QGroupBox", "label": "Payment"}
      ]
    }
  ]
}
```

## Inspect

工具名：`inspect`

职责：精查单个目标，或在 debug-only 模式下返回全量树检查结果。

### Inspect Request

```json
{
  "target": "w12",
  "property": "placeholderText",
  "include_methods": true,
  "include_properties": true,
  "depth": 6,
  "topmost_only": false,
  "include_infrastructure": false
}
```

字段约束：

- `target` 可选
- 当 `target` 为空时，进入 debug-only 全量模式
- `include_methods` 默认为 `false`
- `include_properties` 默认为 `false`，用于返回目标当前全部 Qt properties
- `depth` 只在 `target=null` 时有意义
- `topmost_only` 只在 `target=null` 时有意义
- `include_infrastructure` 只在 `target=null` 时有意义
- 当 `target` 匹配多个控件时，`text`、`value`、`visible`、`enabled`、`checked`、`interactable`、`geometry`、`attribute`、`global_bounding_box`、`bounding_box`、`property_value`、`methods`、`properties` 都取第一个匹配项；`count` 反映总匹配数

### Inspect Response: Target Mode

```json
{
  "ok": true,
  "handle": "w12",
  "exists": true,
  "count": 1,
  "class": "FancyAmountEdit",
  "object_name": "amount_editor",
  "text": "123.45",
  "value": "123.45",
  "visible": true,
  "enabled": true,
  "checked": false,
  "interactable": true,
  "geometry": [12, 48, 220, 80],
  "global_bounding_box": [300, 220, 220, 80],
  "bounding_box": [300, 220, 220, 80],
  "property_value": null,
  "properties": {
    "objectName": "amount_editor",
    "myText": "pressme"
  },
  "methods": []
}
```

可选 `attribute` 字段用于暴露结构化特殊属性，例如 `{"transparent_for_mouse_events": true}`。

### Inspect Response: Debug Tree Mode

```json
{
  "ok": true,
  "target": null,
  "depth": 6,
  "tree": [
    {
      "wid": 1,
      "class": "DemoWindow",
      "objectName": "",
      "text": "QPlaywright Demo App",
      "visible": true,
      "enabled": true,
      "checked": false,
      "geometry": [0, 0, 640, 720],
      "children": []
    }
  ],
  "warnings": [
    "topmost_only is an approximate frontmost-visible filter and may omit widgets or content. Rerun with topmost_only=false when you need a complete tree."
  ]
}
```

## Inspect Items

工具名：`inspect_items`

职责：返回 item-view owner widget 的结构化后代。

### Inspect Items Request

```json
{
  "owner": "w77",
  "max_rows": 50,
  "max_depth": 4,
  "max_items": 200,
  "include_hidden": false
}
```

### Inspect Items Response

```json
{
  "ok": true,
  "owner_handle": "w77",
  "kind": "table",
  "items": [
    {
      "item_target": {
        "owner": "w77",
        "item": {"kind": "table_cell", "row": 3, "column": 1}
      },
      "text": "Approved",
      "visible": true,
      "selected": false
    }
  ]
}
```

## Click

工具名：`click`

职责：对目标执行单击或双击。

### Click Request

```json
{
  "target": "w12",
  "count": 1,
  "include_snapshot": false
}
```

字段约束：

- `target` 必填
- `count` 默认为 `1`
- 允许值：`1`、`2`

### Click Response

```json
{
  "ok": true,
  "target": "w12",
  "count": 1,
  "window_changed": false,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  }
}
```

当 `include_snapshot=true` 时，附加 `ActionObservation` 中的 `snapshot`、`root_handle` 和 `widgets`。

## Input

工具名：`input`

职责：向目标输入文本。

### Input Request

```json
{
  "target": "#amount_editor",
  "text": "123.45",
  "mode": "replace",
  "delay": 0,
  "submit": false,
  "include_snapshot": false
}
```

字段约束：

- `target` 必填
- `text` 必填
- `mode` 默认 `replace`
- `mode` 允许值：`replace`、`append`
- `delay` 单位为毫秒，默认 `0`
- `submit=true` 表示输入完成后自动发送 Enter

### Input Response

```json
{
  "ok": true,
  "target": "#amount_editor",
  "text": "123.45",
  "mode": "replace",
  "delay": 0,
  "submitted": false,
  "window_changed": false,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  }
}
```

## Choose

工具名：`choose`

职责：对选择型控件设定目标值。

### Choose Request

```json
{
  "target": "#currency_combo",
  "label": "CNY",
  "value": null,
  "index": null,
  "include_snapshot": false
}
```

字段约束：

- `target` 必填
- `value`、`label`、`index` 三者必须且只能提供一个

### Choose Response

```json
{
  "ok": true,
  "target": "#currency_combo",
  "value": null,
  "label": "CNY",
  "index": null,
  "window_changed": false,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  }
}
```

## Set Checked

工具名：`set_checked`

职责：显式设置 checkable 控件状态。

### Set Checked Request

```json
{
  "target": "#remember_me",
  "checked": true,
  "include_snapshot": false
}
```

### Set Checked Response

```json
{
  "ok": true,
  "target": "#remember_me",
  "checked": true,
  "window_changed": false,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  }
}
```

## Press Key

工具名：`press_key`

职责：向目标发送按键，或在目标缺省时向当前焦点 / 当前窗口发送按键。

### Press Key Request

```json
{
  "target": null,
  "key": "Escape",
  "include_snapshot": false
}
```

字段约束：

- `key` 必填
- `target` 可选

缺省语义：

- 先发送给当前 focus widget
- 如果没有 focus widget，则发送给当前 active window

### Press Key Response

```json
{
  "ok": true,
  "target": null,
  "key": "Escape",
  "window_changed": true,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  }
}
```

## Hover

工具名：`hover`

职责：将鼠标移动到目标上以触发 hover 态、tooltip 或状态提示。

### Hover Request

```json
{
  "target": "w21",
  "include_snapshot": true
}
```

### Hover Response

```json
{
  "ok": true,
  "target": "w21",
  "window_changed": false,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  },
  "snapshot": "...",
  "root_handle": "w1",
  "widgets": []
}
```

## Scroll

工具名：`scroll`

职责：对可滚动目标发送滚动动作。

### Scroll Request

```json
{
  "target": "#result_table",
  "delta_x": 0,
  "delta_y": 480,
  "include_snapshot": true
}
```

字段约束：

- `target` 必填
- `delta_x` 默认 `0`
- `delta_y` 默认 `0`
- 两者不能同时为 `0`

### Scroll Response

```json
{
  "ok": true,
  "target": "#result_table",
  "delta_x": 0,
  "delta_y": 480,
  "window_changed": false,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  },
  "snapshot": "...",
  "root_handle": "w1",
  "widgets": []
}
```

## Invoke

工具名：`invoke`

职责：调用目标暴露的业务方法。

### Invoke Request

```json
{
  "target": "#amount_editor",
  "method": "setCurrency",
  "args": {
    "code": "CNY"
  },
  "include_snapshot": false
}
```

### Invoke Response

```json
{
  "ok": true,
  "target": "#amount_editor",
  "method": "setCurrency",
  "args": {
    "code": "CNY"
  },
  "result": {
    "ok": true,
    "value": null,
    "errorCode": 0,
    "errorMessage": ""
  },
  "window_changed": false,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  }
}
```

字段语义说明：

- 外层 `ok` 表示 MCP 工具调用本身成功，且请求已经到达 agent
- 内层 `result.ok` 表示业务方法本身是否成功
- 因此外层 `ok=true` 与内层 `result.ok=false` 可以同时成立，这不表示 MCP 工具失败，而表示业务方法返回了失败结果

## Wait

工具名：`wait`

职责：等待目标进入指定状态。

### Wait Request

```json
{
  "target": "#status_label",
  "state": "visible",
  "timeout": 5.0,
  "include_snapshot": false
}
```

或者：

```json
{
  "target": "#status_label",
  "condition": "text_contains",
  "expected": "Logged in",
  "timeout": 5.0,
  "include_snapshot": false
}
```

字段约束：

- `target` 必填
- `state` 与 `condition` 互斥；两者都省略时，服务端默认按 `state="visible"` 处理
- `state` 允许值：`visible`、`hidden`、`enabled`、`disabled`、`checked`、`unchecked`
- `condition` 允许值：`text_equals`、`text_contains`、`current_text_equals`、`current_text_contains`、`value_equals`、`checked_equals`、`count_equals`
- 使用 `condition` 时，`expected` 必填
- `timeout` 默认由服务端决定
- `include_snapshot` 默认 `false`

### Wait Response

```json
{
  "ok": true,
  "target": "#status_label",
  "state": "visible",
  "timeout": 5.0,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  }
}
```

条件等待成功时，响应中的状态字段替换为：

```json
{
  "ok": true,
  "target": "#status_label",
  "condition": "text_contains",
  "expected": "Logged in",
  "timeout": 5.0
}
```

当 `include_snapshot=true` 时，附加 `ActionObservation` 中的 `snapshot`、`root_handle` 和 `widgets`。

## Screenshot

工具名：`screenshot`

职责：对当前窗口或目标截图，可附带矩形裁剪。

### Screenshot Request

```json
{
  "target": "#amount_editor",
  "path": "amount.png",
  "x": 0,
  "y": 0,
  "width": 220,
  "height": 80
}
```

字段约束：

- `target` 可选，缺省表示当前 active window
- 如果提供裁剪参数，则 `x`、`y`、`width`、`height` 必须同时提供
- `x`、`y` 必须大于等于 `0`
- `width`、`height` 必须大于 `0`

### Screenshot Response

```json
{
  "ok": true,
  "target": "#amount_editor",
  "path": "amount.png",
  "width": 220,
  "height": 80,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  }
}
```

### Screenshot Response: Inline Data

```json
{
  "ok": true,
  "target": "#amount_editor",
  "data": "iVBORw0KGgoAAAANSUhEUgAA...",
  "width": 220,
  "height": 80,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": [0, 0, 640, 720]
  }
}
```

补充说明：

- 当提供 `path` 时，响应返回 `path`
- 当省略 `path` 时，响应返回 `data`，其值为 PNG 图片的 base64 编码

## Handle Lifetime Rules

stable handles 的生命周期规则必须固定，不允许依赖调用方猜测。

规则如下：

1. 窗口切换时，handles 不会整体清空。
2. session 重新 attach 或 launch 时，handles 立即清空。
3. 目标控件被销毁后，旧 handle 解析必须失败，并返回明确的 stale-handle 错误。
4. `snapshot`、`find`、`inspect` 会复用已有 handle，并为新看到的 widget 分配新 handle。

## Tool Discovery Guidance

虽然 `session` 和 `window` 采用 `action` 模式，但 tool description 需要对每个 action 给出明确单行语义。

建议风格：

- `session.attach`: attach to an already running Qt app
- `session.launch`: launch a Qt app and attach
- `session.close`: close the current session
- `session.status`: report current session and active window
- `window.list`: list top-level windows
- `window.select`: switch active window
- `window.close`: close one window
- `window.resize`: resize one window

目的是降低 LLM 对 action 分发的试探成本。
