# C++ Top-Level Overlay 回归实施设计

## 目标

将 C++ agent 当前的 child overlay 实现回归为与 Python agent 一致的 top-level overlay 架构，同时保留已经修复的 lifecycle / binding 逻辑，避免重复踩到 `a2ad50e` 之前的不可见与错误绑定问题。

目标不是只让“看起来能显示”，而是实现以下终态：

1. overlay 不是业务 widget tree 的 child。
2. overlay 不拦截输入，不抢焦点。
3. overlay 随目标窗口 move / resize / hide / state change 同步。
4. overlay 生命周期按窗口管理，而不是挂在单一活动实例上。
5. screenshot、widget_tree、find、find_all、hit-test 继续稳定排除 overlay。

## 非目标

本轮不做以下事情：

1. 不调整 overlay 视觉参数风格。
2. 不改 Python 侧 overlay 架构。
3. 不扩展新的视觉效果类型。
4. 不顺带重构 protocol 或 sync_api。

## 当前代码锚点

当前 C++ overlay 实现的核心锚点位于 [qplaywright/cpp/qplaywright_agent.h](qplaywright/cpp/qplaywright_agent.h#L1040-L1335)。

当前关键事实：

1. `QPlaywrightHandler::setVisualFeedbackEnabled()` 通过 `m_overlaySyncTimer` 轮询 `syncAutomationOverlay()`。
2. `AutomationOverlay` 当前构造为 `QWidget(targetWindow)`，属于 child overlay。
3. `QPlaywrightHandler` 当前只维护一组 `m_activeOverlayWindow + m_overlay`。
4. `updateVisualFeedback()` 是当前统一视觉反馈入口。
5. `topLevelWidgets()`、widget tree 序列化、hit-test、screenshot 路径已经包含 overlay 排除逻辑。

Python 侧对照锚点位于 [qplaywright/agent/_server.py](qplaywright/agent/_server.py#L286-L352)。其核心是 per-window overlay manager，而不是单一活动 overlay 实例。

## 根因拆分

根据当前复盘，C++ 之前从 top-level 退回 child overlay 时，至少混杂了两类问题：

1. 已确认问题：lifecycle / target binding bug。
2. 高概率问题：top-level overlay 的 flags、输入穿透、焦点管理或首次 show / 几何同步实现不完整。

因此本次设计要避免两个错误：

1. 不能只把 `QWidget(targetWindow)` 改回 `QWidget(nullptr)` 就收工。
2. 不能继续保留当前单例 overlay 状态机，再去硬套 top-level 语义。

## 目标架构

### 1. Overlay 形态

`AutomationOverlay` 恢复为 top-level 窗口：

```cpp
class AutomationOverlay : public QWidget
{
public:
    explicit AutomationOverlay(QWidget *targetWindow)
        : QWidget(nullptr), m_targetWindow(targetWindow)
    {
        setWindowFlags(
            Qt::Tool
            | Qt::FramelessWindowHint
            | Qt::WindowStaysOnTopHint
            | Qt::WindowTransparentForInput
        );
        setAttribute(Qt::WA_TransparentForMouseEvents, true);
        setAttribute(Qt::WA_NoSystemBackground, true);
        setAttribute(Qt::WA_TranslucentBackground, true);
        setAttribute(Qt::WA_ShowWithoutActivating, true);
        setFocusPolicy(Qt::NoFocus);
    }
};
```

设计约束：

1. `Qt::WindowTransparentForInput` 作为输入穿透的主方案。
2. `WA_TransparentForMouseEvents` 保留为 Qt 层补充，而不是主方案替代品。
3. 首次 `show()` 前必须先设好几何，避免 `(0, 0)` 闪帧。

### 2. Manager 形态

当前 handler 内部的这组三元状态：

1. `m_overlaySyncTimer`
2. `m_activeOverlayWindow`
3. `m_overlay`

应收敛为一个 manager 对象，例如：

```cpp
class AutomationOverlayManager : public QObject
{
    Q_OBJECT
public:
    void setEnabled(bool enabled);
    void moveCursor(QWidget *widget, const QPoint &localPos, int pulseCount);
    void syncAll();
    void closeAll();

private:
    AutomationOverlay *ensureOverlay(QWidget *targetWindow);
    void dropOverlay(QWidget *targetWindow);
    bool eventFilter(QObject *watched, QEvent *event) override;

    QHash<QWidget *, QPointer<AutomationOverlay>> m_overlays;
    QPointer<QWidget> m_activeWindow;
    QTimer m_pulseRefreshTimer;
};
```

设计原则：

1. key 使用目标窗口指针，而不是 registry wid。
2. overlay 生命周期由窗口对象生命周期驱动。
3. handler 不再直接管理 overlay 实例，只通过 manager 调用。

### 3. 几何同步模型

优先使用 `eventFilter`，而不是继续以 16ms 轮询承担主同步职责。

建议监听的事件：

1. `QEvent::Move`
2. `QEvent::Resize`
3. `QEvent::Show`
4. `QEvent::Hide`
5. `QEvent::WindowStateChange`
6. `QEvent::Close`

推荐逻辑：

1. `Move` / `Resize` / `WindowStateChange` 时调用 `syncGeometry()`。
2. `Hide` / `Close` 时隐藏 overlay。
3. `Show` / 恢复可见时重新 `syncGeometry()` 并决定是否显示。
4. pulse 动画仍可保留 timer，但 timer 只负责 pulse 生命周期刷新，不负责窗口几何主同步。

### 4. 活动窗口语义

保留 active window 概念，但语义应从“单 overlay 实例绑定哪个窗口”改为“多 overlay 中哪个当前显示”。

策略：

1. `moveCursor()` 将对应目标窗口设为 active。
2. active overlay 显示并刷新。
3. 非 active overlay 默认隐藏，但保留实例与事件过滤绑定。
4. 这样可以保持与 Python 当前行为一致，避免多窗口同时飘多个 overlay。

## 需要替换的现有状态与方法

### 1. Handler 私有成员替换

当前私有成员位于 [qplaywright/cpp/qplaywright_agent.h](qplaywright/cpp/qplaywright_agent.h#L2068-L2076)。

需要替换：

1. 删除 `QTimer m_overlaySyncTimer;`
2. 删除 `QPointer<QWidget> m_activeOverlayWindow;`
3. 删除 `QPointer<AutomationOverlay> m_overlay;`
4. 新增 `QScopedPointer<AutomationOverlayManager> m_overlayManager;` 或等价持有方式。

### 2. Handler 方法替换

需要重写或收缩的现有方法：

1. `setVisualFeedbackEnabled()`
2. `closeAutomationOverlay()`
3. `syncAutomationOverlay()`
4. `updateVisualFeedback()`

重构目标：

1. `setVisualFeedbackEnabled()` 只控制 manager 的 enable/disable。
2. `closeAutomationOverlay()` 与 `syncAutomationOverlay()` 不再作为 handler 的直接职责存在，逻辑迁入 manager。
3. `updateVisualFeedback()` 只做 target 计算与 manager 转发。

### 3. AutomationOverlay 自身职责调整

`AutomationOverlay` 应只负责：

1. 维护 `m_targetWindow`。
2. 接收 `setCursorFromGlobal()`。
3. 维护 pulse 队列与本地绘制。
4. 处理 `syncGeometry()` / `showIfNeeded()` / `hideIfNeeded()`。

它不应该再承担全局活动窗口选择逻辑。

## 实现步骤

### 第 0 步：最小回归验证分支

先做最小实验性改动，不追求最终结构：

1. 保留当前 binding 修复逻辑。
2. 将 `AutomationOverlay` 暂时改回 `QWidget(nullptr)`。
3. 补齐完整 flags / attributes。
4. 首次 show 前先设几何。

验证点：

1. 是否还能复现“overlay 不可见”。
2. 是否出现点击被拦截。
3. 是否出现焦点丢失。
4. 是否出现 `(0, 0)` 闪帧。

如果第 0 步都不能稳定通过，再回头查 flags / 几何 / 焦点，而不是立刻放弃 top-level 模型。

### 第 1 步：引入 manager

在第 0 步通过后，新增 `AutomationOverlayManager`，把窗口映射、eventFilter、overlay 生命周期移入 manager。

预期改动：

1. 新增 manager 类。
2. handler 只保留 manager 持有和视觉反馈转发。
3. 每个目标窗口在首次使用时安装 eventFilter。
4. 通过 `destroyed` 信号回收 overlay 与 filter 关联状态。

### 第 2 步：迁移 screenshot 关联逻辑

当前 screenshot 路径依赖 `m_overlay` 与 `m_activeOverlayWindow`，见 [qplaywright/cpp/qplaywright_agent.h](qplaywright/cpp/qplaywright_agent.h#L1653-L1679)。

迁移后应改为：

1. 通过 manager 查询“该窗口对应的 overlay 是否可见”。
2. 抓图前隐藏该 overlay。
3. 抓图后恢复显示与层级。

### 第 3 步：保留现有动作入口

当前这些动作都已经走到统一视觉反馈入口，不应重新打散：

1. click / dblclick
2. hover / focus / scroll
3. fill / clear / type / press
4. select_option / check / uncheck

也就是说，这一轮改造主要变 overlay 管理层，不变动作入口层。

## 验证矩阵

### A. 基础显示

1. 单窗口 hover 可见。
2. 单窗口 click pulse 可见。
3. fill / type / press 只移动虚拟鼠标不丢失。

### B. 输入安全

1. click 不会打到 overlay。
2. 目标窗口不会因 overlay `show()` 丢焦点。
3. `QTest::mouseClick`、`QTest::mouseDClick`、`QTest::keyClick` 路径不受影响。

### C. 几何同步

1. 移动窗口时 overlay 无肉眼可见滞后。
2. resize 时 overlay 几何同步正确。
3. minimize / restore 后 overlay 正确隐藏与恢复。
4. 首次 show 不在 `(0, 0)` 闪现。

### D. 多窗口

1. 主窗口与对话框切换时 overlay 跟随 active window。
2. 关闭对话框后 overlay 正确回收。
3. 非 active 窗口 overlay 不残留在桌面上。

### E. 截图与排除

1. `widget_tree` 不包含 overlay。
2. `find` / `find_all` 不返回 overlay。
3. screenshot 不拍到 overlay。
4. hit-test 不会把 overlay 当成目标控件。

### F. 平台细节

1. 高 DPI 下位置不漂。
2. 透明背景无黑边。
3. Windows 10 下 `Qt::WindowTransparentForInput` 生效。

## 失败判据

以下任一情况出现，即本轮不能宣布 top-level 回归成功：

1. overlay 在正确动作后仍经常不可见。
2. click / dblclick 被 overlay 截获。
3. 目标窗口焦点被 overlay 夺走。
4. move / resize 时出现明显滞后或错位。
5. screenshot / widget_tree / find 路径重新泄漏 overlay。

## 推荐落地顺序

1. 先做第 0 步最小回归验证。
2. 通过后再引入 manager，而不是一步到位同时改宿主模型和状态机。
3. manager 稳定后再迁移 screenshot 逻辑。
4. 全部稳定后再考虑是否对 Python 端也做 event-driven 几何同步收敛。

## 一句话设计结论

C++ 回归 top-level overlay 的关键不在“重新启用 Qt::Tool”，而在于同时补齐四件事：

1. 正确 flags 组合。
2. 输入穿透。
3. 生命周期与窗口绑定。
4. event-driven 几何同步。

只要这四件事一起到位，top-level overlay 在 Qt5.14 + Windows 10 上应当能稳定工作。
