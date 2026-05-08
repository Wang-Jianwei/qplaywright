# QPlaywright Agent-Oriented UI Surface V2 Draft

本文档描述一个面向 agent 的 UI 观察与控制接口 V2 草案。

它不是当前实现说明，也不是兼容层设计。
它只回答一个问题：

对于 Qt QWidget 自动化，什么样的 MCP 接口最有利于 agent 低成本理解界面、稳定定位目标、并执行控制动作。

本草案是对现有 MCP 终态接口的全面升级设计。
它不追求与当前 `snapshot` refs、epoch、字段命名或工具返回形状兼容。
如果本草案落地，应直接替换 [docs/mcp_end_state.md](docs/mcp_end_state.md) 和 [docs/mcp_end_state_schema.md](docs/mcp_end_state_schema.md) 中与 target identity、snapshot refs、widget discovery 相关的契约，而不是作为并行兼容层存在。

## Status

本文档描述目标态 V2 草案，不要求当前代码已经实现。

这是 breaking design upgrade。
实现时不保留旧 `refs`/`epoch` 与新 handle 体系的双轨返回，不提供 legacy aliases，也不为旧 MCP host 行为做兼容妥协。

## Superseded Concepts

如果 V2 设计被采纳，以下 V1 概念应被替换：

1. `snapshot` 每次生成 `e1`、`e2` 这类 epoch-scoped refs。
2. 每次新 snapshot 清空旧 refs。
3. action `include_snapshot=true` 返回 V1 `refs`。
4. 以 `snapshot`/`inspect` 长树作为主要 discovery 路径。
5. 同一概念混用 `globalBoundingBox` 与其他命名风格。

V2 只保留一个目标态：session-stable widget handles + server-side `find` + targeted snapshot。

## Implementation Boundary

V2 不是只改 MCP presentation layer 的方案。

必须同时更新以下层次：

1. `protocol.py`：新增 V2 widget discovery method 和稳定 handle 返回契约。
2. Python agent：实现安全 handle 生命周期、root-scoped `find`、predicate matching 和可交互性判定。
3. C++ agent：实现同等安全 handle 生命周期和 `find` parity。
4. MCP layer：替换 V1 refs/epoch 形态，统一 target parser、snake_case 返回和 post-action observation。

如果 `find` 只是 MCP 层先拉完整 `widget_tree` 再过滤，它不满足本文目标。
那只是把模型扫描长树改成 MCP 扫描长树，没有降低目标应用侧的 discovery 成本。

## Naming Conventions

V2 JSON 字段统一使用 `snake_case`。

例如：

1. `object_name`，不是 `objectName`。
2. `global_bounding_box`，不是 `globalBoundingBox`。
3. `current_text`，不是 `currentText`。

Qt 原始属性名如果通过 `include_properties=true` 暴露，可保留 Qt 自身命名；MCP 顶层契约字段必须使用 `snake_case`。

## Design Goal

目标不是让模型“看到更多树节点”，而是让模型能够以更低的决策成本完成这三件事：

1. 快速找到相关 UI 区域。
2. 把观察范围稳定缩小到一个局部子树或一个精确目标。
3. 在不重复探索整窗结构的前提下持续执行动作。

一个有效的 agent-oriented UI surface 应优先满足以下目标：

1. 观察成本随界面复杂度增长得尽可能慢。
2. discovery 主要由服务端完成筛选，而不是把全量树 dump 给模型自己扫描。
3. target identity 在一次会话中尽可能稳定，不因再次 snapshot 而整体失效。
4. widget discovery 和 item-view discovery 保持分层，不混淆真实 QWidget 与非 QWidget 结构项。
5. 每个工具对应单一明确意图，不提供近义重复工具。
6. 控制工具复用统一 target 形式，不要求模型在 selector、临时 ref、wid 之间切换心智模型。

## Non-Goals

本文档不追求以下目标：

1. 不追求兼容当前 snapshot epoch ref 语义。
2. 不追求提供自然语言搜索工具。
3. 不追求把 table cell、tree node、list item 伪造成 widget 节点。
4. 不追求同时提供 search、find、locate、browse 四套近义发现工具。
5. 不追求为浏览器 DOM 查询语法做兼容性妥协。

## Problem Statement

当前以 `snapshot` 为主要发现入口的模式，对 agent 来说有几个根本问题：

1. `snapshot` 本质上是树形 dump，不是搜索接口。
2. 当控件层级很深或噪声节点很多时，模型需要在长文本中自行筛选，这会直接提高 token 成本和决策成本。
3. 当 discovery 依赖“先全局 snapshot，再取 ref，再次 snapshot”时，如果 ref 是按 snapshot epoch 失效的，多轮推理会变脆。
4. `inspect` 适合精查，不适合广义 discovery。
5. item views 本来就不应混入 widget tree，所以 `snapshot` 天生不可能承担全部 discovery 责任。

从第一性原理看，问题不在于 snapshot 不够深，而在于缺少服务端筛选后的候选发现面。

## Core Principles

### 1. Snapshot is a presentation tool, not the primary search engine

`snapshot` 适合让模型理解局部结构和空间关系。
但它不应该承担“在复杂树里搜索候选控件”的主要职责。

### 2. Search should be server-side and deterministic

如果模型想找“设置面板里包含 Submit 文本的按钮”，最优路径不应是：

1. 请求整棵树。
2. 读取长文本。
3. 手工推理筛选。

更优路径应是：

1. 指定搜索范围。
2. 指定结构化约束。
3. 由服务端返回少量候选和命中原因。

### 3. One widget identity should survive repeated observation

agent 不应因为再次调用 snapshot 就丢失上一轮已经建立的局部锚点。

因此，观察结果中的 widget identity 应在 session 内稳定存在，直到 widget 销毁，而不是依赖“本次 snapshot 才有效”的短生命周期编号。

### 4. Widget discovery and item discovery must stay separate

真实 QWidget 树与 table/tree/list/tab 的结构化后代不是一回事。

终态接口必须保持这条边界：

1. widget discovery 只面向真实 QWidget。
2. item discovery 只通过 owner widget + structured item contract 完成。

### 5. Local narrowing is more important than global completeness

对于 agent 来说，可持续缩小范围比一次看到整个世界更重要。

因此，接口应优先支持：

1. 以 active window 为根做初始观察。
2. 以任意已知 target 为根做局部 snapshot。
3. 以任意已知 target 为搜索根做局部 discovery。

### 6. Do not add near-duplicate tools

如果一个需求能通过稳定 handle + targeted snapshot 解决，就不要再额外引入 `browse`。
如果一个需求是“在范围内筛候选”，就定义一个明确的 `find`，不要并行出现 `search`、`locate`、`discover`。

## Core Model

### Active Session And Active Window

保留现有 MCP 终态的两个核心前提：

1. 一个 server instance 管一个 active session。
2. 一个 session 默认有一个 active window scope。

这是默认观察和 selector 解析的基础。

### Stable Widget Handle

面向 agent 的目标态里，widget 应暴露一种 session-stable handle。

本文使用字符串形式 `w123` 作为规范外部形态。
它是 MCP 层的 opaque handle，不要求等同于 agent 内部 `wid`。
实现可以用内部 `wid` 支撑它，但调用方不得依赖两者数值关系。

关键语义只有两条：

1. handle 在 widget 存活期间保持稳定。
2. handle 不因再次 snapshot、再次 inspect、再次 find 而失效。

这类 handle 应成为 MCP 层的一等 target，而不是只作为内部 `wid` 细节存在。

### Safe Handle Preconditions

stable widget handle 必须是安全 identity，不只是裸指针或裸整数包装。

实现必须满足：

1. Python agent registry 不得把已经 destroyed 的 Qt wrapper 继续解析为有效 widget。
2. C++ agent registry 不得保存裸 `QWidget*` 后在 widget 销毁后继续解引用。
3. C++ agent 应使用 `QPointer<QWidget>` 或等价 destroyed-signal cleanup 机制。
4. handle lookup 必须在 widget 已销毁时失败，并返回明确的 stale handle error。
5. stale handle error 与 selector not found error 应区分，方便 agent 判断是目标消失还是定位条件错误。

如果任一 agent 后端不能满足这些前提，就不能宣称支持 V2 stable handles。

### Unified Target

大多数面向 widget 的工具统一接受一个 `target` 字段。

`target` 可取：

1. 一个 selector，例如 `#amount_editor`、`role=button`、`text=Submit`。
2. 一个稳定 widget handle，例如 `w123`。

面向 item view descendants 的目标继续使用 structured target object：

```json
{
  "owner": "w77",
  "item": {
    "kind": "table_cell",
    "row": 3,
    "column": 1
  }
}
```

其中 `owner` 同样可以是 selector 或稳定 widget handle。

### Handle Lifetime Rules

稳定 widget handle 的生命周期建议如下：

1. session 关闭后全部失效。
2. widget 被销毁后对应 handle 失效。
3. window 切换不使 handle 失效。
4. snapshot、inspect、find 不使 handle 失效。

如果 handle 指向的 widget 仍存在但被模态窗口阻塞，动作工具应返回明确的 blocked/focus error，而不是把 handle 解析失败。

### Target Scope Rules

V2 中 selector 与 handle 的 scope 语义不同，必须固定：

1. selector 默认在 active window 内解析。
2. handle 是 session-global target，直接指向它所属的 widget。
3. structured item target 的 `owner` 如果是 selector，则在 active window 内解析；如果是 handle，则按 session-global handle 解析。
4. `find(root=null)` 默认以 active window 为 root。
5. `find(root="w12")` 以 handle 所属 widget 为 root，不要求它属于当前 active window。

动作工具处理 handle 时：

1. 不把 handle 重新解释为当前 active window 内的 selector。
2. 不因为当前 active window 不同而让 handle 失效。
3. 默认不自动激活 handle 所属窗口。
4. 如果 handle 所属窗口不是当前可交互窗口，动作失败并返回 `wrong_active_window` 或等价明确错误。
5. 如果 handle 所属 window 隐藏、最小化、关闭或被不可交互模态窗口阻塞，动作失败并返回明确错误。
6. 如果动作成功导致 Qt active window 改变，服务端更新 active window tracking，并在响应中返回新的 `active_window`。

这样可以同时保持 active window 的默认便利性和 handle 的跨多轮稳定性。

未来如需跨窗口动作，应新增显式参数或专门 window activation flow。
V2 初始契约不做隐式窗口激活。

## Proposed Tool Surface

本文不改写全部 MCP 工具面，只定义与 agent UI 理解和控制最相关的观察面。

推荐保留并强化以下观察工具：

1. `snapshot`
2. `find`
3. `inspect`
4. `inspect_items`

不建议额外引入 `browse`。
局部浏览应由 `snapshot(target=..., depth=...)` 解决。

## 1. snapshot

### Snapshot Responsibility

返回一个面向推理的人类可读文本快照，用于：

1. 建立局部空间与层级理解。
2. 获取稳定 widget handles。
3. 在已知 target 下观察局部子树。

### Why It Still Matters

`snapshot` 对 agent 仍然重要，因为它提供：

1. 结构概览。
2. 文本标签与可见层级。
3. 空间推理所需的 geometry。

但它不再承担“候选搜索主入口”。

### Snapshot Request

```json
{
  "target": null,
  "depth": 4,
  "topmost_only": false,
  "include_infrastructure": false,
  "save_to": null
}
```

字段语义：

1. `target=null` 时，以 active window 为根。
2. `target` 非空时，以目标 widget 为根返回局部子树。
3. `depth` 用于约束文本规模，而不是替代搜索。
4. `topmost_only` 仍是近似前景可见过滤，只用于降低观察噪声。

### Snapshot Response

```json
{
  "ok": true,
  "window": {
    "wid": 1,
    "title": "DemoWindow",
    "class": "DemoWindow",
    "geometry": {"x": 0, "y": 0, "width": 640, "height": 720}
  },
  "target": null,
  "snapshot": "...",
  "widgets": [
    {
      "target": "w12",
      "class": "QGroupBox",
      "object_name": "payment_panel",
      "label": "Payment",
      "geometry": {"x": 12, "y": 48, "width": 420, "height": 220}
    }
  ]
}
```

### Snapshot Contract Notes

1. `widgets` 是面向机器的稳定 widget target 列表，不再叫 `refs`。
2. `snapshot` 是面向模型快速阅读的文本视图。
3. `widgets` 中每个元素都应携带稳定 `target`。
4. `snapshot` 与 `widgets` 应描述同一棵树，不允许各自使用不同 identity 体系。

## 2. find

### Find Responsibility

在一个给定 scope 下做结构化候选发现。

这是 agent-oriented surface 的关键新增工具。

### Why Find Exists

`find` 的职责不是精查一个目标，也不是渲染树。
它的职责只有一个：

根据明确约束，返回少量候选 widget。

这与 `snapshot` 和 `inspect` 不同，因此值得成为一等工具。

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
  "limit": 5
}
```

字段约束：

1. `root` 可选；为空时默认使用 active window。
2. 所有非空谓词按 AND 关系求交。
3. 初始版本不提供任意布尔表达式语言。
4. `limit` 是强约束，服务端不应返回超额候选。
5. `find` 只搜索真实 widget，不扩展到 item-view descendants。

### Find Predicate Semantics

`find` 谓词必须可测试，不能依赖模糊匹配。

字段语义如下：

| Field | Semantics |
| --- | --- |
| `root` | selector 或 stable widget handle；缺省为 active window |
| `role` | 精确匹配 qplaywright `ROLE_MAP` 中的 role 名称，例如 `button`、`table`、`tree` |
| `text` | 精确匹配 widget 主文本，大小写敏感 |
| `has_text` | 子串匹配 widget 主文本，大小写不敏感 |
| `class` | 精确匹配 Qt class name 或其继承链中暴露的 class name |
| `object_name` | 精确匹配 `QObject::objectName()` |
| `accessible_name` | 精确匹配 `accessibleName`，大小写敏感 |
| `visible` | 当为 `true` 时只返回当前可见且几何非空的 widget；当为 `false` 时只返回当前不可见 widget；缺省不筛选 |
| `enabled` | 当为 `true` 时只返回 enabled widget；当为 `false` 时只返回 disabled widget；缺省不筛选 |
| `interactable` | 当为 `true` 时只返回当前可点击或可接收指针动作的 widget；缺省不筛选 |
| `limit` | 返回上限，必须为正整数，默认由服务端决定 |

主文本归一规则：

1. `text` 只匹配 widget 的真实文本通道，例如 button text、label text、line edit text、plain text、group box title。
2. `text` 不匹配 `current_text`。
3. `text` 不匹配 `value`。
4. `text` 不匹配 `accessible_name`。
5. `current_text`、`value`、`accessible_name` 如需搜索，应作为独立谓词加入 V2 schema，而不是混进 `text`。

空字符串不是有效谓词值。
如果调用方传入空字符串，服务端应拒绝请求，而不是把它解释成“匹配所有”。

可见性与可交互性语义必须分开：

1. `visible=true` 是轻量过滤：Qt visible state + non-empty geometry。
2. `interactable=true` 是动作前置过滤：visible + enabled + not blocked by modal + hit-test/topmost check + not masked out at action point。
3. `find` 返回 `interactable=false` 的可见 widget 是合法的；agent 可用 `inspect` 判断为什么不可交互。

### Find Protocol Requirements

`find` 必须是 agent protocol 能力，而不是 MCP 层后处理。

建议新增协议方法：

```python
METHOD_FIND_WIDGETS = "find_widgets"
```

agent 侧职责：

1. 在 Qt 主线程解析 root。
2. 从 root 开始遍历真实 QWidget 子树。
3. 在遍历时应用所有 predicates。
4. 支持 `limit` 早停。
5. 为每个结果注册或返回 stable handle。
6. 返回 `match_reason` 和必要的 `ancestor_summary`。

MCP 层职责：

1. 校验请求形状。
2. 调用 protocol method。
3. 将 agent payload 转成 V2 snake_case MCP response。
4. 不重新执行大规模 widget tree discovery。

### Find Response

```json
{
  "ok": true,
  "root": "w12",
  "count": 2,
  "results": [
    {
      "target": "w48",
      "class": "QPushButton",
      "object_name": "submit_btn",
      "label": "Submit",
      "geometry": {"x": 310, "y": 412, "width": 96, "height": 28},
      "match_reason": ["role=button", "has_text~=Submit", "visible=true", "enabled=true", "interactable=true"],
      "ancestor_summary": [
        {"target": "w12", "class": "QGroupBox", "label": "Payment"}
      ]
    }
  ]
}
```

### Find Ranking Rules

`find` 不应返回 opaque score。
更清晰的做法是：

1. 返回 deterministic ordering。
2. 返回 `match_reason` 解释候选为何入选。

推荐排序优先级：

1. 匹配谓词越具体的候选优先；服务端只比较本次请求实际提供的谓词。
2. 更接近 `root` 的节点优先。
3. `interactable=true` 的节点优先。
4. 有 non-empty geometry 的节点优先。
5. 同级节点按 widget tree preorder 排序。
6. 最后按 stable widget handle 排序，确保完全 deterministic。

不要使用未传入谓词参与排序。
例如请求未提供 `object_name` 时，不应出现 “object_name 精确命中优先” 这类隐式排序规则。

## 3. inspect

### Inspect Responsibility

对单个 target 做精查。

`inspect` 的职责不是大范围 discovery，而是确认：

1. 这个目标到底是什么。
2. 当前能不能交互。
3. 当前有哪些状态和方法。

### Inspect Request

```json
{
  "target": "w48",
  "property": null,
  "include_methods": true,
  "include_properties": false
}
```

### Inspect Response

```json
{
  "ok": true,
  "target": "w48",
  "exists": true,
  "class": "QPushButton",
  "object_name": "submit_btn",
  "text": "Submit",
  "is_visible": true,
  "is_enabled": true,
  "geometry": {"x": 310, "y": 412, "width": 96, "height": 28},
  "global_bounding_box": {"x": 920, "y": 620, "width": 96, "height": 28},
  "methods": []
}
```

### Inspect Contract Notes

1. `inspect(target=null)` 可以继续保留 debug tree 模式，但不应作为 agent 主 discovery 入口。
2. 正常 agent workflow 中，`inspect` 应主要服务于单目标确认。
3. `inspect` 返回的 target identity 必须与 `snapshot` 和 `find` 一致。

## 4. inspect_items

### Inspect Items Responsibility

对 table/tree/list/tab owner widget 做结构化后代发现。

### Why Inspect Items Remains Separate

这是为了保持真实 widget tree 与 item-view logical structure 的边界。

`find` 不承担 item search。
`snapshot` 也不承担 item materialization。
对 structured descendants 的 discovery 统一走 `inspect_items`。

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
  "owner": "w77",
  "kind": "table",
  "items": [
    {
      "target": {
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

## Why There Is No browse Tool

单独再定义 `browse` 会与 `snapshot(target=..., depth=...)` 形成强重叠。

如果已经具备：

1. 稳定 widget handle。
2. targeted snapshot。
3. `find(root=...)`。

那么局部浏览已经有了清晰路径：

1. `snapshot(depth=3)` 获取主要区域 target。
2. `snapshot(target="w12", depth=2)` 查看局部子树。
3. `find(root="w12", has_text="Submit")` 获取少量候选。

因此不再引入新的 browse 工具，避免工具面冗余。

## Control Contract

动作工具不需要新的大改动，但应统一遵守以下规则：

1. 所有 widget-oriented actions 接受 selector 或稳定 widget handle。
2. item-oriented actions 接受 structured item target。
3. `include_state` 和 `include_snapshot` 保持正交。
4. `include_snapshot=true` 返回的后置快照也必须使用稳定 widget handles，而不是新的一轮临时 refs。

动作工具默认不做跨窗口激活。
如果 target handle 属于非当前可交互窗口，动作失败。
agent 应先调用 `window(select)` 或未来显式 activation flow，再重试动作。

这意味着一条多步链路可以稳定成立：

1. `find(...)` 得到 `w48`
2. `inspect(target="w48")`
3. `click(target="w48", include_state=true)`
4. `snapshot(target="w12", depth=2)`

整个流程不应因为再次观察而导致 `w48` 整体失效。

## Recommended Agent Workflow

### Normal Widget Flow

1. `session(attach|launch)`
2. `window(select)`
3. `snapshot(depth=3)` 获取当前窗口主要区域
4. `find(root=<region>, ...)` 做候选缩小
5. `inspect(target=<candidate>)` 确认目标
6. `click|input|invoke|choose|wait`

### Deeply Nested UI Flow

对于深层容器，不推荐直接增大全局 snapshot depth。

推荐流程：

1. `snapshot(depth=2 or 3)` 获取一级区域
2. `snapshot(target=<region>, depth=2)` 缩到局部子树
3. `find(root=<region>, class=..., has_text=..., limit=...)`
4. `inspect(target=<candidate>)`

### Item View Flow

1. `snapshot` 或 `find` 先找到 owner widget
2. `inspect_items(owner=...)` 获取 structured descendants
3. `inspect|click|hover|set_expanded` 使用返回的 structured item targets

## Rejected Alternatives

### 1. Make snapshot deeper by default

这只会让大窗口更长、更吵。
它没有解决服务端筛选缺失的问题。

### 2. Keep epoch-scoped refs as the main interaction identity

这会让多轮观察和局部缩焦变脆。
对于 agent 来说，identity 稳定性比“每次重新编号”更重要。

### 3. Add natural-language search

自然语言搜索对 demo 看起来方便，但会带来：

1. 匹配语义不稳定。
2. 排序解释性弱。
3. 测试契约模糊。

初始版本更适合结构化谓词搜索。

### 4. Merge item discovery into widget search

这会重新引入 fake hierarchy 问题，也会让 target model 变得混乱。

## Delivery Direction

这是 breaking V2 升级，不设计兼容迁移层。
所谓 delivery direction 只描述实现顺序，不描述 V1/V2 双轨运行。

### Phase 1

1. 引入 MCP 层 stable widget handle registry。
2. 修复 C++ agent registry，确保 destroyed widgets 不会留下悬空 handle。
3. 加强 Python agent registry，确保 destroyed Qt object wrapper 不会被误判为有效 widget。
4. 引入统一 target parser：selector 按 active window scope 解析，handle 按 session-global scope 解析。
5. 让所有 widget-oriented action 接受 stable widget handle。
6. 增加 handle lifetime、stale handle、cross-window target scope tests。

### Phase 2

1. 让 `snapshot` 返回 `widgets`，每个 widget entry 使用 stable handle。
2. 让 `inspect` 返回 stable handle 体系和 V2 snake_case 字段。
3. 让 action `include_snapshot=true` 返回 V2 snapshot shape。
4. 删除 V1 `refs`/`epoch` 返回形状。

### Phase 3

1. 新增 protocol-level `find_widgets` method。
2. 在 Python/C++ agent 中实现同等 root-scoped predicate search。
3. 在 MCP 层新增 `find` 工具。
4. 先支持 widget discovery 的核心谓词：`role`、`text`、`has_text`、`class`、`object_name`、`accessible_name`、`visible`、`enabled`、`interactable`。
5. 为 `find` 增加 focused tests，覆盖 root-scoped 搜索、limit 早停、deterministic ordering、interactable filtering 和 Python/C++ parity。

### Phase 4

1. 更新 [docs/mcp_end_state.md](docs/mcp_end_state.md) 与 [docs/mcp_end_state_schema.md](docs/mcp_end_state_schema.md)，用 V2 契约替换 V1 ref 契约。
2. 更新 agent usage guidance，把“snapshot first, then refs”升级为“snapshot for overview, find for narrowing, inspect for confirmation”。

## Summary

从第一性原理看，agent UI 理解面的核心不是“看到更多节点”，而是：

1. 有一个面向阅读的局部结构视图。
2. 有一个面向筛选的服务端 discovery 工具。
3. 有一个跨多轮观察稳定存在的 target identity。

因此，最小且不冗余的优化方向不是继续扩写 `snapshot`，而是建立这样一组清晰分工：

1. `snapshot` 负责结构概览。
2. `find` 负责候选发现。
3. `inspect` 负责精查确认。
4. `inspect_items` 负责 structured item discovery。

这是比“整窗 snapshot + 临时 refs + 模型自己扫树”更适合 agent 的接口面。
