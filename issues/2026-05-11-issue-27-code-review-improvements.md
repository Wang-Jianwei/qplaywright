# Issue #27: 代码审查与质量改进

## Summary

基于对 QPlaywright 代码库的全面审查，发现了一些需要改进的问题，主要集中在错误处理、并发安全、资源管理、类型注解和性能优化方面。

本文档定义了具体的改进计划和实施优先级。

## 当前状态

### 代码质量现状

- **关键回归**: 已覆盖 protocol consistency、connect backoff、MCP server correctness 路径
- **协议一致性**: ✅ C++ `roleMap` 与 Python `ROLE_MAP` 的 QWidget parity 已有守护测试
- **MCP 正确性缺口**: ✅ `input` 已支持 `replace` / `append` / `type` / `clear`，`focus` 已暴露
- **文档覆盖率**: 高
- **代码复杂度**: 中等（C++ 代理文件较大，约 4000+ 行）

### 已识别的问题

#### 1. 错误处理和日志不足

**位置**: `qplaywright/agent/_server.py` 和 `qplaywright/cpp/qplaywright_agent.h`

**问题**:
- 部分错误处理不够详细，缺少结构化错误码
- 日志记录分散，缺少统一的日志配置
- 错误消息不够友好，缺乏上下文信息

**示例**:
```python
# 当前实现
if widget is None:
    raise RuntimeError("Widget not found")

# 期望改进
if widget is None:
    raise WidgetNotFoundError(
        f"Widget not found: selector={selector}, "
        f"window={window_title}, agent={agent_name}"
    )
```

#### 2. 并发安全问题

**位置**: `qplaywright/agent/_server.py` 中的全局变量

**问题**:
- `_SESSION_AGENT_NAMES`、`_ACTIVE_SESSION_ID` 等全局状态缺少线程安全文档
- 虽然当前实现在主线程处理命令，但缺少明确的并发模型说明
- 缺少并发访问的 guard 机制

**当前代码**:
```python
_SESSION_AGENT_NAMES: dict[str, str] = {}
_ACTIVE_SESSION_ID: str | None = None
```

**风险**: 如果未来扩展为多线程处理，可能导致竞态条件

#### 3. 资源管理与恢复语义待收窄

**位置**: `qplaywright/sync_api/_api.py` 和 `qplaywright/sync_api/_connection.py`

**问题**:
- 初始连接阶段已经具备指数退避，因此“缺少连接重试”不是当前事实
- `Connection.send()` 仍然是单次请求/响应模型，不做隐式请求重放
- 超时策略目前只有连接默认超时和单次请求超时，尚未暴露更细的恢复策略
- 连接池不是当前同步 API 的设计目标

**当前实现**:
```python
# QPlaywright.connect(): 初始连接退避
while time.monotonic() < deadline:
    try:
        conn.connect()
        _perform_handshake(conn)
        return Application(conn, timeout=timeout)
    except (ConnectionRefusedError, ConnectionError, OSError):
        conn.close()
        time.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)

# Connection.send(): 单次请求/响应，不做自动重放
if self._sock is None:
    raise ConnectionError("Not connected to agent")
```

#### 4. 类型注解不完整

**位置**: 多个模块

**问题**:
- 部分函数参数使用 `Any` 类型，缺少具体类型提示
- 返回值类型注解不够精确
- 缺少泛型类型使用

**示例**:
```python
# 当前
def convert(value: Any) -> Any:
    pass

# 期望
@overload
def convert(value: Any, target: Literal["int"]) -> int: ...
@overload
def convert(value: Any, target: Literal["str"]) -> str: ...
@overload
def convert(value: Any, target: Literal["bool"]) -> bool: ...
def convert(value: Any, target: str) -> Any:
    pass
```

#### 5. C++ 头文件依赖过多

**位置**: `qplaywright/cpp/qplaywright_agent.h`

**问题**:
- 包含大量 Qt 头文件（约 60+ 个）
- 导致编译时间增加
- 增加了不必要的依赖

**当前代码**:
```cpp
#include <QObject>
#include <QTcpServer>
#include <QTcpSocket>
#include <QThread>
#include <QJsonDocument>
// ... 约 60 个头文件
```

#### 6. 性能优化机会

**位置**: `qplaywright/agent/_selector.py`

**问题**:
- 重复的字符串匹配操作未缓存
- 大 widget 树的序列化效率可优化
- 缺少批量操作支持

#### 7. 协议与架构不一致问题

**位置**: `qplaywright/protocol.py`, `qplaywright/cpp/qplaywright_agent.h`

**问题 7.1: C++ Role Map 不完整**

**2026-05-12 状态**:

- `splitter`、`stackedwidget`、`dockwidget` 已补入 C++ `roleMap`
- 已新增协议一致性测试，守护 Python `ROLE_MAP` 中的 QWidget 角色与 C++ header 同步
- `menuitem` 不纳入这条 QWidget parity，因为它映射到 `QAction`，不是 QWidget 层级匹配问题

**影响**: 这一 correctness 缺口已修复；后续风险主要是再次发生双端漂移

**修复建议**: 保留现有 parity 测试，后续新增 QWidget role 时同步更新两端定义

**验收标准**:
- [x] C++ `roleMap` 覆盖 Python `ROLE_MAP` 中的 QWidget 映射
- [x] `role=splitter`, `role=stackedwidget`, `role=dockwidget` 在两端均可工作

---

**问题 7.2: Overlay/视觉反馈系统重复实现**

视觉反馈系统（automation overlay）在 Python 和 C++ 中高度重复:

| 组件 | Python (`_server.py`) | C++ (`qplaywright_agent.h`) |
|------|----------------------|---------------------------|
| Overlay Widget | `_AutomationOverlay` (~200行) | `AutomationOverlay` (~300行) |
| Overlay Manager | `_OverlayManager` (~150行) | `AutomationOverlayManager` (~200行) |
| Badge 文本 | `f"正在与 Agent {name} 共享"` | `QStringLiteral("正在与 Agent %1 共享")` |
| 定时器间隔 | `16ms` | `16ms` |

**影响**:
- 约 600+ 行重复代码
- 维护成本增加（修改一处需同步另一处）
- Badge 文本硬编码中文，无国际化支持

**当前代码对比**:
```python
# Python _server.py
def _badge_text(self) -> str:
    if not self._session_agent_name:
        return ""
    return f"正在与 Agent {self._session_agent_name} 共享"
```

```cpp
// C++ qplaywright_agent.h
QString badgeText() const {
    if (m_sharedAgentName.isEmpty())
        return QString();
    return QStringLiteral("正在与 Agent %1 共享").arg(m_sharedAgentName);
}
```

**修复建议**:
- 短期: 抽取共享常量（badge 文本格式、定时器间隔、几何参数）到 `protocol.py`
- 中期: 考虑将 overlay 系统提取为共享模块或文档规范
- Badge 文本改为可配置或使用 Qt 翻译机制

**验收标准**:
- [ ] Overlay 系统在两端行为一致
- [ ] 共享常量提取到统一位置
- [ ] Badge 文本可通过配置修改

---

**问题 7.3: Widget Registry 生命周期问题需按事实收窄**

**位置**: Python `_WidgetRegistry`、C++ `QPlaywrightRegistry`、`docs/mcp.md`

**2026-05-12 状态**:

- C++ `QPlaywrightRegistry::registerWidget()` 已在指针键存在但 `QPointer` 失效时移除旧映射，再分配新 `wid`
- C++ registry 也已在 `destroyed` 回调中删除 `m_w2id` / `m_id2w`
- `docs/mcp.md` 已明确 stable handle 只在 widget 存活且 session 未替换时有效

**结论**: 原文把这一点写成“已确认 stale wid bug”过于武断。当前更合理的表述是：生命周期限制已经有文档约束，现有 C++ registry 也并非完全缺少清理逻辑；只有在拿到可复现案例后，才值得继续改 registry 结构或补专门回归测试。

**修复建议**: 暂不改 registry 实现；若后续出现可复现地址复用案例，再以最小测试驱动修复

**验收标准**:
- [x] 文档已明确 wid / handle 的生命周期限制
- [ ] 若后续出现可复现地址复用案例，再补最小回归测试

---

**问题 7.4: MCP Server 暴露方法不完整**

**位置**: `qplaywright/mcp_server.py`

**问题描述**:

原文按 `protocol.py` 的底层 METHOD 数量要求 MCP 做 1:1 镜像，这和当前 MCP 设计不一致。MCP 暴露的是意图级工具，不是 transport method 的逐个透传。

**2026-05-12 状态**:

- `input` 已覆盖 `replace` / `append` / `type` / `clear`
- `focus` 已作为独立 action tool 暴露
- `inspect` / `snapshot` 已覆盖 `count`、`bounding_box` 等观察能力
- `window` 工具已承载 `window_title` / `window_size` / `window_resize` / `window_close`

**影响**: MCP 当前的剩余工作应按“是否缺失高价值工作流”来判断，而不是按 METHOD 数量机械补齐

**修复建议**: 继续沿现有意图级工具扩展；只有在确实存在独立用户意图时，才新增新的 MCP tool

**验收标准**:
- [x] MCP 覆盖高价值交互意图，而不是机械镜像所有协议方法
- [x] MCP 客户端可完成常见观察、窗口管理、输入清空/键入和聚焦流程

---

## 设计目标

1. **保持设计清晰**: 不为了兼容性牺牲架构清晰度或保留不合理接口
2. **渐进式改进**: 优先实施高影响、低风险的改进
3. **文档优先**: 每个改进都应有明确的文档说明
4. **测试覆盖**: 所有改动必须有相应的测试验证
5. **性能不降级**: 优化不应引入性能回退

## 非目标

- 不重构整个代码架构
- 不引入新的外部依赖
- 不改变现有的协议设计
- 不支持过时的 Qt 版本（保持当前 Qt 5.14.2+/Qt 6.x 支持）

## 改进计划

### 第一阶段：高优先级改进（1-2 周）

#### 1.1 增强错误处理

**任务**:
- [x] 在 sync client 连接/握手路径引入公开异常类型
- [x] 在 sync client window/widget lookup 路径引入公开异常类型
- [x] 在 sync client locator/item action 路径引入公开异常类型
- [x] 在 MCP session stale-connection 和 click hidden-target 路径对齐公开异常类型
- [x] 在 MCP 常见 widget/item tool 路径将 action 异常收口为 user-facing ValueError
- [x] 创建结构化错误类层次（`qplaywright/errors.py`）
- [x] 添加错误码和上下文信息
- [x] 改进日志记录（统一日志配置）
- [x] 更新所有错误抛出点

**错误类设计**:
```python
class QPlaywrightError(RuntimeError):
    """Base class for all QPlaywright errors."""
    def __init__(self, message: str, code: str, context: dict | None = None):
        self.code = code
        self.context = context or {}
        super().__init__(message)

class WidgetNotFoundError(QPlaywrightError):
    """Raised when a widget cannot be found."""
    pass

class ConnectionError(QPlaywrightError):
    """Raised when connection to agent fails."""
    pass

class ProtocolError(QPlaywrightError):
    """Raised when protocol handshake or message fails."""
    pass
```

**验收标准**:
- 所有公共 API 抛出明确的错误类型
- 错误消息包含足够的调试信息
- 日志记录覆盖所有关键路径

#### 1.2 完善并发安全文档

**任务**:
- [x] 添加并发模型文档（`docs/concurrency.md`）
- [x] 为全局变量添加线程安全注释
- [ ] 添加并发访问 guard
- [ ] 编写并发测试

**文档示例**:
```python
"""
Thread Safety Guidelines
========================

All widget operations must run on the Qt main thread. The agent uses
QMetaObject::invokeMethod with Qt::BlockingQueuedConnection to ensure
thread affinity.

Global State:
- _SESSION_AGENT_NAMES: Protected by GIL (dict operations are thread-safe)
- _ACTIVE_SESSION_ID: Modified only on main thread via customEvent
- _executing_command: Reentrancy guard, only accessed on main thread
"""
```

**验收标准**:
- 文档清晰说明并发模型
- 所有全局状态有明确的访问规则
- 添加必要的并发 guard

#### 1.3 连接建立退避已落地，后续恢复策略待单独设计

**任务**:
- [x] 在 `QPlaywright.connect()` 中实现指数退避重试
- [x] 为连接建立阶段补充测试覆盖
- [x] 对协议/握手失败采用快速失败，而不是盲目重试
- [ ] 若确有需求，再单独设计可配置 retry policy
- [ ] 若确有需求，再单独设计 health check / reconnect 语义

**当前范围**:

- 当前只对“建立 TCP 连接并完成 handshake”做有限重试
- 不对任意 action 请求做隐式自动重放，避免把非幂等操作重试成错误行为

**验收标准**:
- 连接失败时自动退避重试
- 协议或握手失败立即停止重试
- 行为有明确测试覆盖

### 第二阶段：中优先级改进（2-4 周）

#### 2.1 完善类型注解

**任务**:
- [ ] 为所有公共 API 添加完整类型注解
- [ ] 使用泛型替代 `Any`
- [ ] 添加类型测试
- [ ] 配置 mypy 严格模式

**示例**:
```python
from typing import TypeVar, Generic, overload

T = TypeVar('T')

class Result(Generic[T]):
    def __init__(self, value: T | None = None, error: str | None = None):
        self.value = value
        self.error = error
    
    @property
    def ok(self) -> bool:
        return self.error is None
```

**验收标准**:
- mypy 严格模式下无错误
- 所有公共 API 有完整类型提示
- 类型测试覆盖边界情况

#### 2.2 优化 C++ 头文件依赖

**任务**:
- [ ] 使用前置声明减少头文件包含
- [ ] 分离接口和实现
- [ ] 添加编译时间基准测试
- [ ] 文档说明最佳实践

**优化示例**:
```cpp
// 前置声明减少依赖
class QApplication;
class QTcpServer;
class QTcpSocket;

// 只在实现文件中包含完整头文件
#include <QApplication>
#include <QTcpServer>
```

**验收标准**:
- 编译时间减少 20%+
- 保持功能完整性
- 文档说明依赖关系

#### 2.3 添加性能测试

**任务**:
- [ ] 建立性能测试基准
- [ ] 添加关键路径性能测试
- [ ] 集成到 CI/CD
- [ ] 性能监控仪表板

**测试示例**:
```python
def test_widget_serialization_performance(benchmark):
    widget = create_large_widget_tree()
    result = benchmark(widget_to_dict, widget)
    assert len(result) > 0
```

**验收标准**:
- 关键操作性能有基准测试
- 性能退化自动告警
- 性能数据可视化

### 第三阶段：低优先级改进（4-8 周）

#### 3.1 代码重构和模块化

**任务**:
- [ ] 拆分大型文件（`_server.py`、`qplaywright_agent.h`）
- [ ] 提取通用工具模块
- [ ] 改善模块间依赖关系
- [ ] 代码复杂度分析

#### 3.2 添加更多示例代码

**任务**:
- [ ] 添加高级用法示例
- [ ] 创建教程文档
- [ ] 添加最佳实践指南
- [ ] 视频教程

#### 3.3 性能优化

**任务**:
- [ ] 优化字符串匹配算法
- [ ] 实现结果缓存
- [ ] 批量操作支持
- [ ] 内存使用优化

## 验收标准

### 整体标准

1. **测试覆盖**: 所有改动必须有测试验证
2. **设计清晰**: 不为了兼容性引入额外旧路径或模糊语义
3. **文档完整**: 每个改进都有文档说明
4. **性能不降级**: 关键操作性能不低于当前水平
5. **代码质量**: 符合项目代码规范

### 阶段性验收

**第一阶段验收**:
- [ ] 错误处理改进完成，所有测试通过
- [ ] 并发安全文档完善，无竞态条件
- [x] 连接建立退避机制工作正常

**第二阶段验收**:
- [ ] mypy 严格模式通过
- [ ] C++ 编译时间减少 20%+
- [ ] 性能测试框架建立

**第三阶段验收**:
- [ ] 代码模块化完成
- [ ] 示例代码覆盖主要用例
- [ ] 关键路径性能优化 10%+

## 风险评估

### 高风险

1. **错误处理改动可能破坏现有错误处理逻辑**
    - 缓解：优先修正根因，避免引入额外兼容层，必要时提供明确迁移说明

2. **并发安全改进可能引入新的竞态条件**
   - 缓解：充分的并发测试，代码审查

### 中风险

1. **类型注解可能影响运行时性能**
   - 缓解：类型注解不影响运行时，仅用于静态检查

2. **C++ 重构可能引入编译错误**
   - 缓解：渐进式重构，充分测试

### 低风险

1. **性能优化可能效果不明显**
   - 缓解：基于性能数据驱动优化

## 时间线

- **第 1-2 周**: 第一阶段（高优先级改进）
- **第 3-4 周**: 第二阶段（中优先级改进）
- **第 5-8 周**: 第三阶段（低优先级改进）
- **第 9 周**: 最终验收和文档完善

## 成功指标

1. **代码质量**:
   - mypy 严格模式通过
   - 代码复杂度降低 15%+
   - 测试覆盖率保持 100%

2. **性能**:
   - C++ 编译时间减少 20%+
   - 关键操作性能优化 10%+
   - 内存使用减少 10%+

3. **开发者体验**:
   - 错误消息清晰度提升
   - 文档完整性提升
   - 示例代码覆盖主要用例

## 相关资源

- [docs/accessibility_semantics.md](../docs/accessibility_semantics.md)
- [CLAUDE.md](../CLAUDE.md)
- [AGENTS.md](../AGENTS.md)
- [qplaywright/protocol.py](../qplaywright/protocol.py)
- [qplaywright/agent/_server.py](../qplaywright/agent/_server.py)
- [qplaywright/cpp/qplaywright_agent.h](../qplaywright/cpp/qplaywright_agent.h)

## 维护者备注

- 此 issue 应分阶段实施，每个阶段完成后提交
- 优先实施高影响、低风险改进
- 所有改动需经过代码审查
- 性能改进需基于实际数据
