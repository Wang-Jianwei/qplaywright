# Overlay 现状分析与统一改造思路

## 背景

当前 qplaywright 的可视化自动化反馈已经在 Python agent 和 C++ agent 两侧落地，但两边的 overlay 宿主模型并不一致，导致视觉表现、窗口切换行为和调试路径存在分叉。

本报告说明：

1. 当前实现的真实状态。
2. Python 与 C++ 为什么会演化成不同实现。
3. 当前分叉的技术风险。
4. 推荐的统一改造方向与实施顺序。

## 当前状态

## 经验判断与前提更新

基于当前 Qt5.14 + Windows 10 的目标环境，以及已有大量生产实践，可以先明确一个前提：

1. Qt5 做 top-level transparent overlay 是可行的。
2. 这不是 Qt5 能力边界问题。
3. 如果 top-level overlay 在当前仓库的 C++ 端不稳定，优先应归因于实现问题，而不是模式本身不可行。

这意味着报告后续的风险分析需要收紧：

1. `Qt5 顶层 overlay 本身可能不可行` 不再作为主要假设。
2. 主要怀疑对象应转为 flags 组合、输入穿透、生命周期绑定、几何同步时机和焦点管理。

## Qt5 Top-Level Overlay 可行性判断

在 Qt5.14 + Windows 10 上，top-level transparent overlay 是成熟模式。所需 API 在 Qt5 时代已经稳定存在，关键组合如下：

```cpp
setWindowFlags(
	Qt::Tool
	| Qt::FramelessWindowHint
	| Qt::WindowStaysOnTopHint
	| Qt::WindowTransparentForInput
);
setAttribute(Qt::WA_TranslucentBackground);
setAttribute(Qt::WA_ShowWithoutActivating);
```

这里最关键的是：

1. `Qt::WindowTransparentForInput` 应优先作为顶层输入穿透方案。它在操作系统窗口样式层面实现穿透，比仅依赖 `WA_TransparentForMouseEvents` 更彻底。
2. `WA_TranslucentBackground` 在 Windows 10 上依赖 DWM，而 DWM 在该平台下常态开启，不再是早期 Windows 版本那类脆弱前提。
3. `WA_ShowWithoutActivating` 是防止 overlay show / raise 时抢焦点的必要补充，而不是可有可无的装饰属性。

因此，从平台能力上看，当前 C++ 回到 top-level overlay 并不存在先天阻塞。

### 1. Python 侧 overlay 模型

Python 侧当前实现位于 [qplaywright/agent/_server.py](qplaywright/agent/_server.py#L154-L352)。

其核心特征是：

1. overlay 是独立 top-level 浮层，而不是业务窗口内的子控件。
2. overlay 使用无父窗口的 QWidget 创建，即 `super().__init__(None)`。
3. overlay 使用 `Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint` 作为窗口 flags。
4. overlay 通过目标窗口的全局坐标进行几何同步。
5. overlay manager 维护“每个目标窗口一个 overlay”的映射，并用 active window 概念决定当前显示哪个 overlay。

这套实现从语义上更接近“自动化专用 mask 显示层”。它不是 widget tree 的业务组成部分，而是附着在桌面窗口之上的一层专用可视反馈层。

额外收益是：作为 top-level overlay，它天然不属于业务窗口的 children。这样在 `widget_tree`、基于业务根节点的 `find` / `find_all`、snapshot 等路径里，不会因为 overlay 混入业务 widget tree 而额外增加 child 过滤负担。当然，它仍然会出现在 top-level window 枚举里，因此 `topLevelWidgets()` / `list_windows` 这类入口仍需要显式排除。

### 2. C++ 侧 overlay 模型

C++ 侧当前实现位于 [qplaywright/cpp/qplaywright_agent.h](qplaywright/cpp/qplaywright_agent.h#L1098-L1325)。

其核心特征是：

1. overlay 当前是目标窗口内部的 child widget。
2. overlay 使用 `QWidget(targetWindow)` 构造，而不是独立 top-level widget。
3. overlay 通过占满父窗口 rect 的方式同步几何，而不是使用全局坐标创建独立浮层。
4. 当前只维护一个活动 overlay，通过 `m_activeOverlayWindow` 和 `m_overlay` 进行绑定。
5. overlay 的刷新、隐藏、截图前后恢复等逻辑都与当前目标窗口强绑定。

这意味着 C++ 当前更像“窗口内部的透明蒙层”，而不是独立于业务窗口存在的专用可视层。

这也意味着 C++ 侧不得不在更多路径里显式排除 overlay：例如 widget tree 子节点遍历、命中测试、截图前隐藏恢复等。当前代码已经做了这些排除，但这是一类由宿主模型选择额外引入的维护成本，而不是业务功能本身需要的复杂度。

### 3. 绘制逻辑并不是主要差异来源

Python 的绘制逻辑位于 [qplaywright/agent/_server.py](qplaywright/agent/_server.py#L227-L284)，C++ 的绘制逻辑位于 [qplaywright/cpp/qplaywright_agent.h](qplaywright/cpp/qplaywright_agent.h#L1167-L1223)。

两边在以下方面已经基本一致：

1. 使用蓝色 core dot。
2. 使用白色鼠标箭头与阴影。
3. 使用多段 pulse 扩散环。
4. pulse 时间和扩散半径语义基本一致。

因此，当前观感不一致的主因不是 paintEvent 的画法不同，而是 overlay 所处的宿主层级不同。

## 历史演进

### 1. Python 先落地

持久 overlay manager 最早在提交 `d33a985` 中进入 Python 侧。

Python 从一开始就是独立 top-level overlay 的设计，这一点在当前代码的 [qplaywright/agent/_server.py](qplaywright/agent/_server.py#L154-L199) 中仍可直接看出。

### 2. C++ 首次移植最初其实也想保持一致

持久 overlay 的 C++ 首次移植在提交 `d931d24` 中完成。

从该提交的历史内容可见，C++ 首版最开始也是顶层浮层路线：

1. overlay 构造最初是 `QWidget(nullptr)`。
2. 也设置了 `Qt::Tool | Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint`。
3. 也按顶层 overlay 思路做几何同步。

这说明起步时目标并不是故意做出两套模型，而是希望 Python 和 C++ 走同一类 overlay 设计。

### 3. C++ 后来因为运行时问题偏离

后续提交 `a2ad50e` 对 C++ overlay 做了关键修复。该修复把 C++ overlay 从顶层浮层改成了当前的 child overlay：

1. 构造从 `QWidget(nullptr)` 改成 `QWidget(targetWindow)`。
2. 去掉了顶层窗口 flags。
3. 改为直接占满目标窗口 rect。
4. 增加了自己的 `QTimer` 和 `tick()` 自刷新路径。
5. 修复了 overlay 目标绑定在重建过程中的状态丢失问题。

这一步不是“设计升级”，而是“为了先把 C++ 端跑稳定而做的局部收敛”。

换句话说，当前的 C++ 形态是运行时问题驱动下形成的偏离结果，而不是从头就有意与 Python 保持不同。

### 4. 已确认的历史故障与仍未完全确认的问题

这里需要把“已经确认的事实”和“尚待验证的平台风险”分开。

已确认的事实：

1. `a2ad50e` 不是单纯的宿主模型切换，它同时修复了 overlay 生命周期与 target binding 逻辑。
2. 已确认的运行时问题之一是 overlay 重建时目标窗口绑定会丢失，导致 overlay 绑定到空目标或隐藏目标，从而表现为“虚拟鼠标不可见”。
3. 已确认的另一个问题是 visual feedback enable 后的 eager sync 时机会触发错误的 overlay 同步路径，放大 target binding 丢失问题。

尚未被独立验证的问题：

1. `a2ad50e` 中“改成 child overlay”与“修正绑定逻辑”是混合提交，因此不能仅凭这次修改就断言“问题根因就是 top-level overlay 不稳定”。
2. 当时的 top-level 实现是否遗漏了 `Qt::WindowTransparentForInput`，从而导致 overlay 拦截输入事件。
3. 是否存在独立于 binding bug 之外的焦点 / 激活 / 几何同步实现缺陷。

因此，在重新回到 top-level overlay 之前，必须把历史问题拆开验证：

1. target binding / 生命周期 bug 是否已经被当前逻辑完全修复。
2. 为 C++ top-level overlay 补齐正确 flags 后，是否仍会复现独立于 binding bug 之外的行为问题。
3. 如果仍有问题，应优先定位为焦点、输入穿透、几何同步或透明渲染实现问题，而不是直接否定 top-level 模型。

## 为什么会变成现在这样

### 1. 工作顺序是先跑通，再统一

当时的实际顺序是：

1. 先在 Python 侧把 overlay 体验做出来。
2. 再把同等能力移植到 C++。
3. C++ 在 Qt5/Windows 场景下出现顶层 overlay 的绑定与显示问题。
4. 当时大概率同时存在两类实现缺陷：生命周期 / binding bug，以及顶层 overlay 的 flags / 输入穿透 / 焦点处理不完整。
5. 后续没有再把“宿主模型变更”和“生命周期 bug 修复”两件事拆开重新验证。
6. 因此临时偏离最终固化成了当前实现。

这是一条典型的“增量追平功能”路径，而不是“先定义终态模型，再双端同时实现”的路径。

### 2. 当时的修复目标是稳定性，不是架构一致性

`a2ad50e` 的修复目标非常明确：让 C++ overlay 在实际运行时稳定显示出来，并解决 target binding 丢失的问题。

在这种上下文里，child overlay 比 top-level overlay 更容易受父窗口生命周期保护，也更容易快速收口问题。因此它是一个工程上可理解的临时选择，但不是一个设计上理想的终态。

### 3. 临时偏离没有被重新收敛

真正的问题不在于那次偏离本身，而在于偏离之后没有再回过头把两边重新统一。结果就是：

1. Python 继续保持 top-level overlay。
2. C++ 固化为 child overlay。
3. 同一功能的两端实现开始共享绘制语义，但不共享宿主模型。

## 当前分叉带来的问题

### 1. 表现层不一致

用户看到的不是同一套 overlay 体验：

1. Python 更像悬浮在应用之上的独立控制层。
2. C++ 更像窗口内部的透明子蒙层。

这会直接影响对“自动化痕迹”的感知。

### 2. 多窗口行为不一致

Python 的 manager 是 per-window overlay 模型；C++ 当前是单活动 overlay 模型。

在多窗口、窗口切换、弹窗切换等场景下，两边的行为难以严格对齐。

### 3. 排障路径分叉

任一 overlay 问题都需要分别考虑：

1. top-level 透明浮窗路径。
2. child overlay 路径。

这直接提高了维护与调试成本。

### 4. 后续功能扩展容易继续漂移

hover、focus、scroll、fill、type、press、select_option、check、uncheck 这些动作现在已经逐步接进反馈路径，但如果宿主模型不同，后续再加更复杂的视觉效果时，两边仍然会继续各自演化。

### 5. Qt5 Windows 顶层浮窗平台行为存在实现风险，而不是能力阻塞

如果 C++ 回到 top-level overlay，需要正视 Qt5.14 / Windows 组合下的几个实现风险点：

1. 激活与焦点问题：`Qt::Tool` 窗口 show / raise 时可能影响目标窗口激活状态。
2. DPI 缩放问题：高 DPI 环境下 `mapToGlobal()` 与实际像素坐标可能存在偏差，导致 overlay 位置漂移。
3. 透明背景渲染问题：`WA_TranslucentBackground` 与 frameless top-level 组合在某些 Windows 版本下可能出现黑边或不透明现象。
4. 输入穿透问题：如果缺少 `Qt::WindowTransparentForInput` 或替代方案不完整，overlay 可能截获输入，直接干扰 `QTest` 事件注入。

这些风险不构成否决 top-level overlay 的理由，但必须作为实施前验证项。

### 6. top-level overlay 的几何同步复杂度更高

child overlay 可以直接跟随父窗口 rect，而 top-level overlay 的同步需要明确策略。候选策略有两类：

1. 基于 `eventFilter` 监听目标窗口的 move、resize、show、hide、windowStateChange 等事件。
2. 基于 `QTimer` 定时轮询窗口几何与全局坐标。

Python 当前采用的是 timer 轮询方案，刷新周期约 16ms。C++ 重新实现时，优先建议采用 `eventFilter` 驱动几何同步，再辅以 pulse 动画自身的 timer 刷新；这样更即时，也能降低无意义轮询。

推荐监听的事件至少包括：

1. `QEvent::Move`
2. `QEvent::Resize`
3. `QEvent::Show`
4. `QEvent::Hide`
5. `QEvent::WindowStateChange`
6. `QEvent::Close`

### 7. 输入穿透需要被当成显式约束

对于 top-level overlay，不能只关注可见性，还必须确保它不会拦截输入：

1. 当前 Python / C++ 都设置了 `WA_TransparentForMouseEvents` 和 `WA_ShowWithoutActivating`。
2. 对于 top-level 窗口，应优先使用 `Qt::WindowTransparentForInput`。在 Qt5.14 / Windows 10 上，这应被视为默认方案，而不是备选优化。
3. `WA_TransparentForMouseEvents` 可以保留为 Qt 层补充，但不应被当作顶层 overlay 输入穿透的唯一保障。

这一点不能留到后面观察，必须作为 top-level 回归时的第一批验证项。

### 8. per-window overlay manager 的生命周期必须与窗口对象解耦

如果 C++ 改成 per-window overlay map，需要明确以下约束：

1. overlay map 的 key 应该是目标窗口对象指针或稳定窗口标识，而不是 agent registry 的 wid。
2. 窗口销毁时必须通过 `QObject::destroyed` 自动回收 overlay，避免悬空指针。
3. screenshot / screenshot_widget 的隐藏恢复逻辑应基于“overlay 属于哪个窗口”的映射，而不是 child/parent 关系。

## 推荐改造方向

### 结论

不应继续接受 Python 和 C++ 各自保持不同宿主模型。应选定一个终态，并让两边统一到同一架构。

### 推荐统一到 Python 当前模型

推荐方向是：让 C++ 回归并对齐 Python 当前的独立 top-level overlay 模型，而不是把 Python 降级成 child overlay。

理由如下：

1. 语义更清晰。独立 top-level overlay 更符合“自动化专用 mask 层”的定义。
2. 更符合最初目标。此前明确希望“专门做一个给 MCP 用的 mask 显示层，并且在控件捕获中排除掉”。
3. Python 端已经接近这一终态。既然 Python 先跑通并且模型更干净，应让 C++ 向它收敛。
4. child overlay 更像为了绕开平台细节而采取的局部折中，不适合作为最终架构标准。
5. top-level overlay 不属于业务窗口 children，天然减少业务 widget tree 污染。
6. 从 Qt5.14 + Windows 10 的平台能力看，top-level overlay 并不存在阻塞性的技术上限。

但这个方向有一个前提：必须先确认当初促使 C++ 退回 child overlay 的问题里，哪些已经被 lifecycle / binding 修复消除，哪些其实只是 flags / 输入穿透 / 几何同步实现不完整造成的假性平台问题。只有在这些实现问题被补齐之后仍无法稳定，才需要重新评估是否反向让 Python 收敛为 child overlay。

## 修改思路

### 0. 先做历史问题拆分验证

在真正改回 top-level 之前，应先做一次最小验证，把历史问题拆开：

1. 在当前 C++ 分支上保留已修复的 lifecycle / binding 逻辑，只恢复 top-level overlay 宿主模型。
2. 同时补齐顶层 overlay 所需的 flags / attributes，至少包括 `Qt::Tool | Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint | Qt::WindowTransparentForInput`、`WA_TranslucentBackground`、`WA_ShowWithoutActivating`。
3. 记录是否仍会出现 overlay 不可见、几何错位、焦点丢失、点击被拦截、透明异常等现象。
4. 对照 Python 侧当前 top-level 实现，确认哪些 flags / attributes / 同步策略是 Python 已经用来绕开问题的。

只有这一轮验证完成后，后续统一方向才是可执行而不是纸面正确。

### 1. 统一 overlay 宿主模型

将 C++ 当前 child overlay 改回独立 top-level overlay：

1. `AutomationOverlay` 从 `QWidget(targetWindow)` 改回 `QWidget(nullptr)`。
2. 恢复 `Qt::Tool | Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint | Qt::WindowTransparentForInput`。
3. 保留 `WA_TranslucentBackground` 与 `WA_ShowWithoutActivating`。
4. 保留 `WA_TransparentForMouseEvents` 作为 Qt 层补充，但不以它替代顶层输入穿透 flag。
5. 首次 `show()` 前必须先设好几何，避免在 `(0, 0)` 闪现一帧。
6. 几何同步改为使用目标窗口全局坐标，而不是直接占父窗口 rect。

这一步的目标是先把宿主层级统一到与 Python 相同。

### 2. 统一 overlay 管理方式

将 C++ 从“单活动 overlay”改为“每个 top-level window 一个 overlay”的 manager 语义。

建议引入一个与 Python `_OverlayManager` 对应的 C++ 管理结构：

1. 按窗口指针维护 overlay map，而不是依赖 registry wid。
2. 保留 active window 概念用于控制可见性。
3. 使用 `QObject::destroyed` 自动回收对应 overlay。
4. 将当前单例 `m_activeOverlayWindow + m_overlay` 收敛为 manager 内部状态，而不是直接散落在 handler 私有成员里。
5. 优先使用 `eventFilter` 同步几何，timer 仅用于 pulse 动画与必要兜底。

这会让多窗口行为与 Python 更接近，也能降低当前 `m_activeOverlayWindow + m_overlay` 单例状态带来的偶发耦合。

### 3. 保持统一的视觉反馈入口

当前动作路径已经逐步收口到统一的视觉反馈入口，这是正确方向，应继续保留。

在 C++ 中，相关入口主要包括：

1. [qplaywright/cpp/qplaywright_agent.h](qplaywright/cpp/qplaywright_agent.h#L1311-L1325)
2. [qplaywright/cpp/qplaywright_agent.h](qplaywright/cpp/qplaywright_agent.h#L1912-L1988)

改造时不应让 click、hover、focus、scroll、fill、type、press、select_option、check、uncheck 再次分散处理，而应继续让它们都经过统一 overlay 更新通路。

### 4. 保留并泛化截图排除逻辑

当前 C++ 的截图路径会在抓图前临时隐藏 overlay，抓完再恢复，见 [qplaywright/cpp/qplaywright_agent.h](qplaywright/cpp/qplaywright_agent.h#L1653-L1679)。

这一策略本身是合理的，改造时应该保留，但它不应依赖 child/parent 关系，而应依赖“overlay 归属于哪个目标窗口”的映射关系。

这可以确保统一宿主模型后，截图逻辑依然稳定。

### 5. 最后再做视觉参数微调

只有在宿主模型统一后，视觉参数微调才有意义。包括：

1. 箭头大小。
2. 阴影强度。
3. core dot 大小与透明度。
4. pulse 扩散半径与持续时间。

在宿主层级不同的前提下，先调参数只会造成表面接近，而无法真正统一体验。

## 推荐实施顺序

### 第一步

先做一次历史问题拆分验证：只恢复 top-level overlay 宿主模型，但保留当前已修复的 lifecycle / binding 逻辑，确认当初退回 child overlay 的问题里哪些已经消失，哪些仍然存在。

### 第二步

在第一步验证可行后，将 C++ overlay 生命周期从“单活动 overlay”改成“per-window overlay manager”。

### 第三步

验证以下行为：

1. 单窗口显示。
2. 多窗口切换。
3. 弹窗切换。
4. move / resize / minimize / restore 下的几何同步。
5. hover、focus、scroll。
6. fill、type、press。
7. select_option、check、uncheck。
8. screenshot 与 screenshot_widget 的 overlay 排除。
9. 焦点保持、输入穿透、高 DPI 对齐、透明背景渲染。
10. 首次 show 是否闪现到 `(0, 0)`。

### 第四步

在两边宿主模型统一后，再进行视觉细节对齐。

## 最终判断

当前的差异不是因为 Python 与 C++ 必须不同，而是因为 C++ 在一次运行时修复中偏离了最初的共同模型，并且之后没有被重新收口。

因此，真正的解决方案不是继续解释这种不一致，而是明确把 C++ 收回到与 Python 同一套 overlay 架构上。
