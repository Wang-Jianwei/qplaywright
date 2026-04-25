# QPlaywright MCP End-State Schema

本文档是 [docs/mcp_end_state.md](docs/mcp_end_state.md) 的配套契约附录。

前者回答“为什么这样设计”，本文档回答“每个终态工具到底长什么样”。

本文档描述的是终态目标接口，不要求当前代码已经完全实现。

## Conventions

- JSON 字段统一使用 `snake_case`
- 成功响应统一包含 `ok: true`
- 除非特别说明，目标工具在 `target` 匹配多个控件时不报错，而是返回第一个匹配项的标量字段，同时用 `count` 暴露总匹配数
- `target` 的 selector 语法保持原子匹配，不在终态契约中定义内联布尔组合语法；需要组合条件时，先用 `snapshot` 或 `inspect` 缩小范围，再使用 snapshot ref

## Request Model

除 `session` 和 `window` 之外，终态工具默认都是单一意图工具，不再额外包一层 `action`。

终态工具分为三类：

1. 资源工具：`session`、`window`
2. 观察工具：`snapshot`、`inspect`、`screenshot`
3. 动作工具：`click`、`input`、`choose`、`set_checked`、`press_key`、`hover`、`scroll`、`invoke`、`wait`

## Value Types

### Target

大多数工具使用统一的 `target` 参数。

类型：`string`

解释规则：

1. 如果值匹配当前 ref 表中的键，例如 `e12`，按 snapshot ref 解析。
2. 否则按 qplaywright selector 解析。

示例：

- `e12`
- `#amount_editor`
- `role=button`
- `text=保存`

补充说明：

- 终态契约中的 selector 仍沿用 qplaywright 的单表达式语法，例如 `role=button`、`text=保存`、`has-text=partial`
- 终态契约当前不定义 `role=button >> has-text=Submit` 或 `role=button[has-text=Submit]` 这类复合语法
- 当需要“角色 + 文本”等复合定位时，推荐流程是先 `snapshot` 或 `inspect` 观察并拿到更稳定的 target，再使用 snapshot ref 继续动作

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
  "geometry": {
    "x": 120,
    "y": 80,
    "width": 480,
    "height": 320
  }
}
```

字段说明：

- `wid`: agent 侧窗口标识
- `title`: 窗口标题
- `class`: Qt 类名
- `index`: 当前窗口列表中的索引
- `is_active`: 是否为当前 active window
- `is_modal`: 是否为模态窗口
- `geometry`: 窗口布局数据，统一使用 `{x, y, width, height}`

### RefEntry

```json
{
  "ref": "e12",
  "wid": 103,
  "target": "#amount_editor",
  "class": "FancyAmountEdit",
  "geometry": {
    "x": 12,
    "y": 48,
    "width": 220,
    "height": 80
  },
  "text": "123.45"
}
```

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
  "geometry": {
    "x": 12,
    "y": 48,
    "width": 220,
    "height": 80
  },
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
    "geometry": {
      "x": 120,
      "y": 80,
      "width": 480,
      "height": 320
    }
  },
  "snapshot": "...",
  "refs": []
}
```

其中 `refs` 的元素类型为 `RefEntry[]`。

字段说明：

- `window_changed`: 本次动作后 active window 是否变化
- `active_window`: 当前 active window 摘要
- `snapshot`: post-action 文本快照
- `refs`: 与该快照一致的 ref 集

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
- ref expired
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
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
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
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
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
    "geometry": {
      "x": 120,
      "y": 80,
      "width": 480,
      "height": 320
    }
  },
  "refs_cleared": true
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
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 800,
      "height": 600
    }
  }
}
```

补充说明：

- 当 `action="close"` 且关闭的是当前 active window 时，服务端应自动把 `active_window` 切换到下一个可见窗口
- 如果没有剩余可见窗口，则 `active_window` 允许为 `null`
- 当 `close` 导致 active window 变化时，refs 按 `select` 的同一规则处理并清空；旧窗口上下文中的 snapshot ref 不再可用

## Snapshot

工具名：`snapshot`

职责：返回当前窗口或某个目标的文本快照和稳定 refs。

### Snapshot Request

```json
{
  "target": "e12",
  "depth": 8,
  "topmost_only": false,
  "save_to": "snapshot.txt"
}
```

字段约束：

- `target` 可选，缺省表示当前 active window
- `depth` 默认为 `10`
- `topmost_only` 默认为 `false`，仅对 window-wide snapshot 有意义
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
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
  },
  "target": null,
  "snapshot": "...",
  "refs": [],
  "warnings": [
    "topmost_only is an approximate frontmost-visible filter and may omit widgets or content. Rerun with topmost_only=false when you need a complete tree."
  ],
  "save_to": "snapshot.txt"
}
```

其中 `refs` 的元素类型为 `RefEntry[]`。
当 `topmost_only=true` 且 `target=null` 时，`warnings` 应明确指出结果可能不完整。

## Inspect

工具名：`inspect`

职责：精查单个目标，或在 debug-only 模式下返回全量树检查结果。

### Inspect Request

```json
{
  "target": "#amount_editor",
  "property": "placeholderText",
  "include_methods": true,
  "include_properties": true,
  "depth": 6,
  "topmost_only": false
}
```

字段约束：

- `target` 可选
- 当 `target` 为空时，进入 debug-only 全量模式
- `include_methods` 默认为 `false`
- `include_properties` 默认为 `false`，用于返回目标当前全部 Qt properties
- `depth` 只在 `target=null` 时有意义
- `topmost_only` 只在 `target=null` 时有意义
- 当 `target` 匹配多个控件时，`text`、`value`、`is_visible`、`is_enabled`、`is_checked`、`geometry`、`globalBoundingBox`、`bounding_box`、`property_value`、`methods`、`properties` 都取第一个匹配项；`count` 反映总匹配数

### Inspect Response: Target Mode

```json
{
  "ok": true,
  "target": "#amount_editor",
  "exists": true,
  "count": 1,
  "text": "123.45",
  "value": "123.45",
  "is_visible": true,
  "is_enabled": true,
  "is_checked": false,
  "geometry": {
    "x": 12,
    "y": 48,
    "width": 220,
    "height": 80
  },
  "globalBoundingBox": {
    "x": 300,
    "y": 220,
    "width": 220,
    "height": 80
  },
  "bounding_box": {
    "x": 300,
    "y": 220,
    "width": 220,
    "height": 80
  },
  "property_value": null,
  "properties": {
    "objectName": "amount_editor",
    "myText": "pressme"
  },
  "methods": []
}
```

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
      "geometry": {
        "x": 0,
        "y": 0,
        "width": 640,
        "height": 720
      },
      "children": []
    }
  ],
  "warnings": [
    "topmost_only is an approximate frontmost-visible filter and may omit widgets or content. Rerun with topmost_only=false when you need a complete tree."
  ]
}
```

## Click

工具名：`click`

职责：对目标执行单击或双击。

### Click Request

```json
{
  "target": "e12",
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
  "target": "e12",
  "count": 1,
  "window_changed": false,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
  }
}
```

当 `include_snapshot=true` 时，附加 `snapshot` 和 `refs`。

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
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
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
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
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
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
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
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
  }
}
```

## Hover

工具名：`hover`

职责：将鼠标移动到目标上以触发 hover 态、tooltip 或状态提示。

### Hover Request

```json
{
  "target": "e21",
  "include_snapshot": true
}
```

### Hover Response

```json
{
  "ok": true,
  "target": "e21",
  "window_changed": false,
  "active_window": {
    "wid": 1,
    "title": "QPlaywright Demo App",
    "class": "DemoWindow",
    "index": 0,
    "is_active": true,
    "is_modal": false,
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
  },
  "snapshot": "...",
  "refs": []
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
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
  },
  "snapshot": "...",
  "refs": []
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
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
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

字段约束：

- `target` 必填
- `state` 必填
- `state` 允许值：`visible`、`hidden`、`enabled`、`disabled`、`checked`、`unchecked`
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
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
  }
}
```

当 `include_snapshot=true` 时，附加 `snapshot` 和 `refs`。

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
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
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
    "geometry": {
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 720
    }
  }
}
```

补充说明：

- 当提供 `path` 时，响应返回 `path`
- 当省略 `path` 时，响应返回 `data`，其值为 PNG 图片的 base64 编码

## Ref Lifetime Rules

snapshot refs 的失效规则必须固定，不允许依赖调用方猜测。

规则如下：

1. 窗口切换时，refs 立即清空。
2. session 重新 attach 或 launch 时，refs 立即清空。
3. 目标控件被销毁后，旧 ref 解析必须失败，并返回明确错误。
4. 每次生成新 snapshot 时，refs 以该 snapshot 返回值为准。

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
