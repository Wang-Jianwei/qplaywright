# QPlaywright MCP End State

本文档描述 qplaywright MCP 的终态接口设计。

配套的精确工具契约见 [docs/mcp_end_state_schema.md](docs/mcp_end_state_schema.md)。

这不是当前实现说明，也不是兼容层说明，而是从第一性原理出发，回答一个更基本的问题：

对于 Qt QWidget 自动化，一个真正有效、直接、准确的 MCP 接口面应该是什么样。

## Status

本文档描述的是目标态，不要求当前代码已经完全实现。

当前仓库中的 qplaywright MCP 同时承担了三种角色：

- qplaywright 原生能力的 MCP 暴露
- playwright-mcp 风格的兼容层
- 调试和过渡时期的辅助接口集合

终态设计不再把这三者混为一体。

## Design Goal

终态 MCP 只服务一个目的：

让模型能够以最小的决策成本，稳定地完成 Qt 应用自动化任务。

这意味着接口设计必须优先满足以下目标：

1. 观察优先于猜测。
2. 模型的工具选择成本足够低，不需要在多个近义工具之间试探。
3. 作用域由服务端管理，而不是在每次调用里重复传递。
4. 每个工具都对应一个明确意图，而不是底层 API 的机械映射。
5. 优先暴露 Qt 应用真正有价值的能力，尤其是 widget method invoke。
6. 不为浏览器语义做兼容性妥协。

## Non Goals

终态 MCP 不追求以下目标：

- 不追求与 playwright-mcp 的工具名兼容
- 不追求与浏览器自动化的参数形态一致
- 不追求把 sync API 的所有方法逐个映射成 MCP 工具
- 不追求一套接口同时满足调试、兼容、迁移、正式使用四种场景

## Core Principles

### 1. MCP should expose intentions, not transport details

MCP 工具应该表达高层意图，例如：

- 选择窗口
- 观察当前界面
- 对目标执行点击
- 对目标输入文本
- 调用目标暴露的方法

而不是直接暴露如下细节：

- 当前用的是 selector 还是 wid
- 当前是哪一个窗口索引
- 当前是否需要额外做 snapshot 拼接

这些应该尽量由服务端维护上下文。

### 2. One server instance should have one active session

终态默认模型是：一个 MCP server 对应一个当前 active session。

因此，`connection` 不应该在所有工具里反复出现。多连接属于运维能力，不应该成为默认交互模型的负担。

如果确实需要多目标并行，优先方案是启动多个 MCP server 实例，而不是把每个工具都做成多连接路由器。

### 3. One active window should be the default scope

终态默认模型是：一个 session 有一个当前 active window。

因此，大部分工具不应该要求重复传入：

- `window_wid`
- `window_title`
- `window_index`

窗口切换应该通过专门的 window 工具完成，而不是复制到每个动作工具的参数中。

同时，服务端应持续跟踪 `QApplication::activeWindow()` 的变化。

这对以下场景尤其重要：

- 点击后弹出模态对话框
- invoke 后切出新窗口
- 旧窗口关闭后焦点自然转移

模型不应该在每次动作后都手动检查一次窗口是否变化。

### 4. Snapshot refs are first-class

对 LLM 来说，快照 ref 是最适合持续交互的定位形式之一。

终态里，target 应统一接受两类输入：

- selector
- snapshot ref

模型先通过 `snapshot` 获取 ref，再用 ref 驱动 click、input、invoke、screenshot。

统一 target 解析是所有终态工具的基础设施，应尽早落地。

补充说明：

- 终态里的 `target` 统一成一个字符串，并不等于必须把复合条件语法也塞进这个字符串
- 终态契约可以保持 selector 语法的原子性，例如 `role=button`、`text=Submit`、`has-text=partial`
- 当需要“role=button 且文本包含 Submit”这类复合约束时，更清晰的终态路径是先 `snapshot` 或 `inspect` 缩小范围，再使用 ref 继续动作，而不是在 selector 中引入一套新的布尔语法

### 5. Invoke is not an extension feature, it is a core feature

对 QWidget 自动化来说，自定义控件方法调用不是附加能力，而是核心能力。

浏览器自动化的中心是 DOM 操作。

Qt 业务自动化的中心应当是：

- 观察 widget state
- 对标准控件执行通用动作
- 对业务控件执行显式 invoke

因此，终态 MCP 必须把 `invoke` 放在核心接口面中，而不是隐藏在边缘工具里。

### 6. Action tools should support optional post-action observation

动作工具默认返回精简结果是对的，但 Qt 应用中很多状态变化无法只凭动作返回值判断。

因此，终态设计应允许动作工具通过显式参数请求附带观察结果，而不是强制模型每次动作后都再调用一次 `snapshot`。

推荐形式：

- `include_snapshot: false` 为默认值
- 当为 `true` 时，服务端附带 post-action snapshot 和 refs

这样既保留高效路径，也保留单轮观察路径。

## End-State Tool Surface

终态工具面应尽量控制在一打左右，但不为追求数字而牺牲直接性。

如果 hover 和 scroll 在真实 Qt 场景里是刚需，它们就应保留为一等工具。

### 1. session

职责：管理当前会话生命周期。

建议能力：

- `attach`
- `launch`
- `close`
- `status`（可选）

建议示例：

```json
{
  "action": "attach",
  "port": 19876
}
```

为什么保留：

- 会话生命周期是一等概念
- 不应该分裂成 connect、launch、disconnect、list_live_connections 四个平级工具

设计说明：

- `session` 采用 `action` 分发是为了收敛工具数量
- 但 tool description 必须为每个 action 提供明确 one-liner，避免模型额外试探
- 如果 `snapshot` 已稳定返回当前 session 和 active window 头信息，`status` 可以不作为一等工具公开

### 2. window

职责：管理当前 session 下的顶层窗口。

建议能力：

- `list`
- `select`
- `close`
- `resize`

建议示例：

```json
{
  "action": "select",
  "index": 1
}
```

为什么保留：

- 窗口是独立资源
- 窗口选择应该显式完成，然后成为后续默认作用域

设计说明：

- 当服务端检测到 active window 变化时，应自动更新当前窗口作用域
- 对动作工具，返回值可包含 `window_changed` 和新的 `active_window` 摘要

### 3. snapshot

职责：返回当前窗口或某个目标的文本快照和稳定 refs。

建议参数：

- `target`
- `depth`
- `save_to`

建议返回：

- `session`
- `snapshot`
- `refs`
- `target`
- `window`

为什么保留：

- 这是 LLM 最重要的观察入口
- 它比 raw widget tree 更适合推理和下一步动作决策

补充说明：

- `snapshot` 可以返回当前 active window、focus widget、modal dialog 状态等头部信息
- `save_to` 表示把文本快照写入文件，不是保存图片
- 这样 `session.status` 的需求会被进一步压低

### 4. inspect

职责：精查单个目标的状态和能力。

建议参数：

- `target`（可选）
- `property`
- `include_methods`
- `include_properties`
- `depth`

建议返回：

- `exists`
- `count`
- `text`
- `value`
- `is_visible`
- `is_enabled`
- `is_checked`
- `bounding_box`
- `methods`
- `properties`

当 `target` 为空时，`inspect` 可退化为 debug-only 的全量树检查模式。

如果 `target` 匹配多个控件，终态可以返回第一个匹配项的标量字段，同时用 `count` 明确暴露总匹配数；这样模型不需要为“是否唯一匹配”先额外试探一次。

为什么保留：

- 它是统一的精查入口
- methods 应当并入 inspect，不再单独暴露 `get_widget_methods`
- 它也可以承接当前 `widget_tree` 的调试用途，而不必再保留独立主工具

### 5. click

职责：对目标执行点击。

建议参数：

- `target`
- `count`
- `include_snapshot`

说明：

- `count=1` 表示单击
- `count=2` 表示双击

为什么保留：

- 点击是独立且高频的交互意图
- 不需要保留 `browser_click` 这种平行命名

### 6. input

职责：向目标输入文本。

建议参数：

- `target`
- `text`
- `mode`: `replace` 或 `append`
- `delay`
- `submit`
- `include_snapshot`

为什么保留：

- 文本输入必须是一等接口
- 但不需要同时存在 `fill`、`type_text`、`browser_type`、`browser_fill_form`

终态语义：

- `mode=replace` 等价于当前 fill
- `mode=append` 等价于当前 type
- `submit=true` 表示输入完成后自动向当前 target 或其宿主窗口发送 Enter

### 7. choose

职责：为选择型控件选择值。

建议参数：

- `target`
- `value`
- `label`
- `index`
- `include_snapshot`

约束：

- 三者只能提供一个

为什么保留：

- 选择行为不是 click 的变体，而是稳定的状态设定
- 名称使用 `choose` 而不是 `select`，用于避免和 `window(action="select")` 混淆

### 8. set_checked

职责：显式设置目标的勾选状态。

建议参数：

- `target`
- `checked`
- `include_snapshot`

为什么保留：

- 对 checkable 控件，设定目标状态比“点一次试试看”更准确

扩展说明：

- 对外仍保留 `set_checked`
- 内部实现应为未来扩展到更广义的 `set_state` 预留空间

### 9. press_key

职责：向目标发送按键。

建议参数：

- `target`（可选）
- `key`
- `include_snapshot`

为什么保留：

- Enter、Escape、Tab、快捷键在 Qt 应用中是独立交互能力

缺省语义：

- 当 `target` 为空时，按键发送给当前 focus widget
- 如果当前没有 focus widget，则发送给当前 active window

### 10. hover

职责：将鼠标移动到目标上而不点击。

建议参数：

- `target`
- `include_snapshot`

为什么保留：

- tooltip、状态栏提示、hover 样式、延迟出现的附加信息在 Qt 应用中很常见
- 用 `click count=0` 表达 hover 不够直接，也不利于模型理解

### 11. scroll

职责：对可滚动目标发送滚动动作。

建议参数：

- `target`
- `delta_x`
- `delta_y`
- `include_snapshot`

为什么保留：

- QScrollArea、QTableView、QTreeView 等控件没有 scroll 就无法到达可视区域外的内容
- 这是实际任务完成率问题，不是附加体验问题

### 12. invoke

职责：调用目标暴露的业务方法。

建议参数：

- `target`
- `method`
- `args`
- `include_snapshot`

建议返回：

- `ok`
- `result`
- `errorCode`
- `errorMessage`

为什么保留：

- 这是 qplaywright 与浏览器自动化最大的有效差异点
- 终态设计中它是核心工具，而不是附属工具

补充说明：

- 外层 `ok` 表示 MCP 工具调用本身成功到达 agent
- 内层 `result.ok` 表示业务方法本身是否成功
- 因此“外层 `ok=true` 但内层 `result.ok=false`”是合法且重要的返回形态

### 13. wait

职责：等待目标进入某种状态。

建议参数：

- `target`
- `state`
- `timeout`
- `include_snapshot`

建议支持的状态：

- `visible`
- `hidden`
- `enabled`
- `disabled`
- `checked`
- `unchecked`

为什么保留：

- 等待必须由服务端执行
- 模型不应以轮询或睡眠替代状态等待

补充说明：

- `include_snapshot=true` 时，等待成功后返回 post-wait snapshot 和 refs
- 这样 `wait` 与其他动作工具保持一致，也减少“wait 之后立即再 snapshot 一次”的机械往返

### 14. screenshot

职责：对当前窗口或目标截图。

建议参数：

- `target`
- `path`
- `x`
- `y`
- `width`
- `height`

为什么保留：

- 截图是观察的补充手段

补充说明：

- 当提供 `path` 时，响应返回保存后的 `path`
- 当省略 `path` 时，响应直接返回内联图片数据，例如 base64 编码的 `data`
- `clip rectangle` 是实际有价值的能力，应该并入同一工具而不是额外派生新工具

## Canonical Target Model

终态设计中，大多数动作工具统一使用 `target` 参数。

`target` 可以是：

- qplaywright selector
- snapshot ref

示例：

- `#amount_editor`
- `role=button`
- `text=保存`
- `e12`

终态不鼓励把以下参数复制到所有工具里：

- `selector`
- `has_text`
- `nth`
- `window_wid`
- `window_title`
- `window_index`

这些要么由 target 表达，要么由 window 作用域表达。

## Recommended Return Style

终态工具的返回结构应统一遵循以下原则：

1. 成功时返回最小必要字段。
2. 不为不同命名风格维护两套返回形状。
3. 如果某个工具天然会改变界面状态，可以选择附带 snapshot，但不应强制所有动作都返回大块快照。

建议约束：

- `snapshot` 只由 `snapshot` 作为主入口提供
- 动作工具默认返回精简结构
- 动作工具统一支持 `include_snapshot`
- 当 `include_snapshot=true` 时，返回值附带 post-action snapshot 和 refs
- 对可能导致窗口切换的动作，返回值可附带 `window_changed` 和 `active_window`

推荐示例：

```json
{
  "ok": true,
  "target": "e12",
  "window_changed": true,
  "active_window": {
    "wid": 9,
    "title": "Confirm"
  },
  "snapshot": "...",
  "refs": []
}
```

## Tools To Remove

从终态目标看，以下接口不应继续保留为一等 MCP 工具：

### Compatibility Layer

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
- `browser_wait_for`
- `browser_verify_element_visible`
- `browser_verify_text_visible`
- `browser_verify_value`

删除原因：

- 它们不是第一性原理下的工具
- 它们只是外部命名习惯的镜像层
- 它们制造了两套平行接口面

### Thin Native Wrappers

- `get_widget_methods`

### Covered By Other Tools

- `focus`

删除原因：

- `get_widget_methods` 应并入 `inspect`

处理建议：

- `focus` 不进入终态工具面
- `click` 会隐式聚焦目标
- `press_key(target=null)` 已覆盖“向当前焦点对象发送按键”的主要场景

### Debug-Only Surface

- `widget_tree`

处理建议：

- 不再作为主 MCP 工具面的一部分
- 可保留为 debug-only 接口
- 或折叠进 `inspect(target=None, depth=N)` 的全量模式

### Split Text Input Surface

- `fill`
- `type_text`

### Split Selection Surface

- `select_option`

删除原因：

- 它们应统一为 `input`
- 差别只应体现在 `mode`
- 选择型控件应统一收敛到 `choose`

## Scope Management

终态默认交互流程应是：

1. `session(attach|launch)`
2. `window(select)`
3. `snapshot()`
4. 基于 `target` 执行动作
5. 必要时 `inspect(target)` 或 `invoke(target, ...)`

这意味着服务端内部需要持有：

- 当前 active session
- 当前 active window
- 当前 snapshot refs

并且应在每次动作后检查：

- active window 是否变化
- focus widget 是否变化
- refs 是否需要失效或重建

这样模型不需要在每个工具里重新组装上下文。

## Ref Lifecycle

snapshot refs 不是永久标识符，终态文档必须明确它们的失效规则。

推荐规则：

- 窗口切换时清空 refs
- 重新连接时清空 refs
- 目标控件被销毁时，ref 解析失败并由服务端返回显式错误
- 当一次动作触发新的 snapshot 生成时，以最新 snapshot 的 ref 集为准

## Example Flow

下面是一条终态交互链路：

1. `session {"action": "attach", "port": 19876}`
2. `window {"action": "list"}`
3. `window {"action": "select", "index": 0}`
4. `snapshot {"depth": 6}`
5. `click {"target": "e12", "include_snapshot": true}`
6. `input {"target": "#amount_editor", "text": "123.45", "mode": "replace", "submit": false}`
7. `invoke {"target": "#amount_editor", "method": "setCurrency", "args": {"code": "CNY"}}`
8. `scroll {"target": "#result_table", "delta_y": 480, "include_snapshot": true}`
9. `wait {"target": "#status_label", "state": "visible", "timeout": 5}`
10. `screenshot {"target": "#amount_editor", "x": 0, "y": 0, "width": 220, "height": 80, "path": "amount.png"}`

这条链路里没有：

- browser 兼容别名
- 多连接路由参数
- 每次重复窗口选择参数
- fill 和 type 的分裂命名

## Migration Direction

从当前实现走向终态，建议按下面顺序收口：

### Phase 1

- 引入统一 `target` 解析基础设施，例如 `_resolve_target(connection, target)`
- 新工具优先使用 `target`，老工具暂时保留 selector 形态
- 把 `get_widget_methods` 并入 `inspect`
- 把 `fill`、`type_text`、`browser_type` 收敛为 `input`
- 保留现有实现，但在文档上明确主推荐接口

### Phase 2

- 让工具默认作用于当前 active window
- 让 snapshot ref 成为标准定位方式
- 为动作工具加入 `include_snapshot` 和 `window_changed` 返回约定
- 收拢 `select_option` 到 `choose`

### Phase 3

- 删除所有 `browser_*` 工具
- 将 `widget_tree` 降级为 debug-only 或折叠进 `inspect`
- 将 session 和 window 收拢为资源型接口

## Final Decision Rule

在终态设计里，是否保留一个 MCP 工具，只问三个问题：

1. 它是否表达了独立且高频的用户意图。
2. 它是否比现有工具组合更直接、更准确。
3. 去掉它之后，模型是否会明显更难完成真实任务。

如果三个问题里有一个回答是否定的，这个工具就不应该进入终态接口面。
