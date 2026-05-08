# 在 OpenCode 中测试 QPlaywright MCP

本文档说明如何在 OpenCode 中接入并测试本仓库提供的 QPlaywright MCP。

适用场景：

- 你希望在 OpenCode 里把 qplaywright 当作一个本地 MCP 服务器使用。
- 你希望让 OpenCode 连接一个正在运行的 Qt QWidget 应用，然后调用 `session`、`window`、`snapshot`、`click` 等终态工具。

## 前提

你需要准备好以下内容：

1. 一个可用的 Python 解释器。
2. 一个已经安装并可运行的 OpenCode。
3. 一个正在运行的、内嵌 qplaywright agent 的 Qt 应用。

本仓库自带两个现成对象：

- MCP 服务端入口：`python -m qplaywright.mcp_server`
- 示例 Qt 应用：`examples/demo_app.py`

## 安装 MCP 依赖

推荐先在仓库根目录安装 MCP 依赖：

```powershell
D:/Python/Python312/python.exe -m pip install -e ".[mcp]"
```

如果你使用虚拟环境，也可以使用虚拟环境里的 Python：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
```

### 当前仓库里的已知问题

如果你当前的 `.venv` 执行 `pip install` 时出现下面这类错误：

```text
SyntaxError: source code string cannot contain null bytes
```

这不是 `.[mcp]` 写法有问题，而是该虚拟环境里的 `pip` 已损坏。此时有两个可行处理方式：

1. 直接改用系统 Python，例如上面的 `D:/Python/Python312/python.exe`。
2. 删除并重建 `.venv`，再重新安装依赖。

在当前仓库里，系统 Python 的安装命令已经验证可用。

如果你不想重建整个 `.venv`，也可以只重装虚拟环境里的 `pip`。当前仓库已经验证过下面这组命令可用：

```powershell
Move-Item .\.venv\Lib\site-packages\pip .\.venv\Lib\site-packages\pip_corrupt_backup
Move-Item .\.venv\Lib\site-packages\pip-26.0.1.dist-info .\.venv\Lib\site-packages\pip-26.0.1.dist-info.backup
.\.venv\Scripts\python.exe -m ensurepip --upgrade --default-pip
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
```

修复完成后，虚拟环境里的 MCP 入口也已经验证可运行：

```powershell
.\.venv\Scripts\python.exe -m qplaywright.mcp_server --help
```

## 启动示例 Qt 应用

先在一个单独终端中启动示例应用：

```powershell
D:/Python/Python312/python.exe examples/demo_app.py
```

示例应用会启动内嵌的 qplaywright agent，并监听默认端口 `19876`。

## 配置 OpenCode

OpenCode 支持在项目根目录放置 `opencode.json` 或 `opencode.jsonc`。对于这个仓库，建议直接在项目根目录添加一个项目级配置。

当前仓库已经提供了一份项目级 [opencode.json](opencode.json)。它显式固定了工作区 `.venv` 里的 Python，并带上 `PYTHONPATH`，目的是减少本地 MCP 启动时对全局环境和 Python 解析路径的依赖。

下面是一份可直接使用的最小配置示例：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "qplaywright": {
      "type": "local",
      "enabled": true,
      "command": [
        "python.exe",
        "-m",
        "qplaywright.mcp_server"
      ],
      "environment": {
        "PYTHONPATH": "./xxx"
      },
      "timeout": 15000
    }
  }
}
```

说明：

- `type: local` 表示这是一个本地 stdio MCP 服务。
- `command` 是 OpenCode 用来启动 MCP 的命令数组。
- `PYTHONPATH` 在 editable install 不稳定或未执行时是一个额外保险，确保 `qplaywright` 包能被导入。
- `timeout` 可以适当放大，避免首次工具枚举或启动较慢时超时。
- 项目级 `opencode.json` 会在从该工作区根目录启动 OpenCode 时生效；这是隔离全局配置噪音的首选方式。

如果你已经成功执行过 editable install，也可以去掉 `environment.PYTHONPATH`。

## 启动 OpenCode

在仓库根目录中运行：

```powershell
opencode
```

如果你使用的是自定义配置文件路径，也可以通过 OpenCode 自己的配置机制加载；但对这个仓库来说，项目根目录里的 `opencode.json` 最直接。

## 在 OpenCode 中测试

进入 OpenCode 后，可以直接给出类似下面的提示词。

### 最小连通性测试

```text
use qplaywright
执行 session attach，端口 19876。
然后执行 window list 和 snapshot。
```

### Playwright 风格兼容层测试

```text
use qplaywright
连接到 127.0.0.1:19876。
调用 snapshot。
填写用户名 admin 和密码 secret123。
选择角色 Admin。
勾选 Remember me。
点击 Login。
最后验证 Logged in as admin 文本可见。
```

### 建议的工具调用顺序

对 OpenCode 来说，下面这条路径最稳定：

1. `session {"action": "attach", ...}`
2. `window {"action": "list"}` 或 `window {"action": "select", ...}`
3. `snapshot` 先拿结构概览
4. 必要时用 `find` 缩小候选范围
5. 使用 `snapshot` 或 `find` 返回的 stable handle 继续调用 `input`、`click`、`choose`、`set_checked`
6. 使用 `inspect` 或附带 `include_snapshot=true` 的动作结果做断言
7. `session {"action": "close"}`

补充说明：

- OpenCode 当前应面向终态工具面，不应再假设存在 `connect`、`browser_snapshot`、`browser_click` 这类旧兼容工具
- 如果提示词仍然强行引用旧工具名，表现出来通常不是“工具选错”而是“qplaywright MCP 不可用”

## 故障排查

### 1. OpenCode 没有加载到 qplaywright MCP

先检查 OpenCode 是否读到了项目配置，以及 MCP 是否成功注册：

```powershell
opencode mcp list
```

### 2. MCP 启动失败或工具列表拉取超时

执行：

```powershell
opencode mcp debug qplaywright
```

优先检查以下几项：

- `command` 中的 Python 路径是否真实存在。
- 当前仓库路径是否正确。
- `qplaywright.mcp_server` 是否可以被导入。
- 是否已经安装 `.[mcp]`；否则 `python -m qplaywright.mcp_server` 会在启动时直接退出。
- `timeout` 是否过小。

当前实现里，`qplaywright.mcp_server` 对启动依赖非常直接：

- 缺少 `mcp` 可选依赖时，进程会立即 `SystemExit`
- Python 找不到 `qplaywright` 包时，进程也会直接退出
- 因此 OpenCode 侧看到的通常只是“本地 MCP 启动失败”这一层表象

### 3. session attach 失败

如果 `session attach` 失败，通常不是 OpenCode 本身的问题，而是目标 Qt 应用没有运行，或者没有监听默认地址端口。

先确认示例应用是否已经单独启动：

```powershell
D:/Python/Python312/python.exe examples/demo_app.py
```

### 4. snapshot 有结果，但后续操作找不到控件

优先使用 `snapshot` 或 `find` 返回的 stable handle 继续做后续操作，而不是重新猜 selector。当前工具面已经支持稳定 handle，可以直接把 `w1`、`w2` 这类 handle 传回给动作工具。

### 5. OpenCode 看起来像“启动了 MCP”，但一调用就失败

这通常有三类原因：

1. OpenCode 或提示词还在调用旧工具名，例如 `connect`、`browser_snapshot`、`browser_click`
2. Qt demo 没有先启动，导致后续第一条 `session attach` 就失败
3. session 已建立，但远端 qplaywright agent 断开了；当前服务端会在下一次工具调用时把该 session 直接判定为 stale，并要求重新 attach

## 仓库内的现成参考

如果你想看已经验证通过的完整示例，直接参考以下文件：

- `examples/test_mcp_demo.py`
- `examples/test_dialog_mcp_demo.py`
- `examples/test_scroll_mcp_demo.py`
- `examples/test_playwright_mcp_compat.py`
- `docs/mcp.md`

其中：

- `examples/test_mcp_demo.py` 展示原生 qplaywright MCP 工具流。
- `examples/test_dialog_mcp_demo.py` 展示真实弹出 `QDialog` 的窗口发现、控件操作和关闭验证。
- `examples/test_scroll_mcp_demo.py` 展示原生 MCP `scroll` tool 驱动 Qt 滚轮事件并验证滚动状态变化。
- `examples/test_playwright_mcp_compat.py` 展示 playwright-mcp 风格兼容层的完整调用路径。

## 推荐测试路径

如果你只是想尽快验证 OpenCode 侧是否工作，建议按这个顺序进行：

1. 用系统 Python 执行 `pip install -e ".[mcp]"`
2. 启动 `examples/demo_app.py`
3. 在项目根目录加入 `opencode.json`
4. 启动 `opencode`
5. 在提示词里明确写上 `use qplaywright`
6. 先跑 `session attach + snapshot`
7. 再跑登录动作和断言
