# Browser-Use 开源库分析报告

## 1. 项目概述

**Browser-Use** 是一个开源的 AI 浏览器自动化库，通过将 LLMs（大语言模型）与 Chrome DevTools Protocol (CDP) 结合，使 AI 代理能够自主浏览网页并完成复杂任务。

- **GitHub**: https://github.com/browser-use/browser-use
- **许可证**: MIT
- **Python 版本**: >= 3.11
- **定位**: "让网站对 AI 代理可访问" (Make websites accessible for AI agents)

## 2. 核心架构

### 2.1 组件架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Agent                                    │
│  (browser_use/agent/service.py)                                  │
│  - 任务编排，LLM 决策循环                                        │
│  - 最多 N 步循环执行                                             │
└───────────────────────┬─────────────────────────────────────────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼
┌──────────────┐  ┌───────────┐  ┌──────────┐
│   Browser    │  │   Tools   │  │    LLM   │
│   Session    │  │  Service  │  │ (多模型)  │
│              │  │           │  │          │
│ - CDP 连接   │  │ - Actions │  │ - OpenAI │
│ - 页面管理   │  │ - 浏览器  │  │ - Google │
│ - Watchdogs │  │   操作    │  │ - Claude │
│              │  │ - 文件   │  │ - 等等   │
└──────────────┘  └───────────┘  └──────────┘
       │
       ▼
┌──────────────┐
│  DOM Service │
│              │
│ - DOM 树构建 │
│ - 元素序列化 │
│ - 可访问性   │
│   树处理     │
└──────────────┘
```

### 2.2 事件驱动架构

BrowserSession 使用 `bubus` 事件总线协调多个 watchdog 服务：

| Watchdog | 职责 |
|----------|------|
| `DownloadsWatchdog` | PDF 自动下载和文件管理 |
| `PopupsWatchdog` | JavaScript 对话框和弹窗管理 |
| `SecurityWatchdog` | 域名限制和安全策略执行 |
| `DOMWatchdog` | DOM 快照、截图、元素高亮 |
| `AboutBlankWatchdog` | 空白页重定向处理 |
| `CrashWatchdog` | 浏览器崩溃检测 |
| `CaptchaWatchdog` | CAPTCHA 解决状态等待 |

### 2.3 核心文件结构

```
browser_use/
├── agent/
│   ├── service.py          # Agent 主类，任务编排
│   ├── views.py            # Pydantic 数据模型
│   ├── prompts.py          # 系统提示词
│   ├── message_manager/    # 消息管理
│   └── system_prompts/     # Markdown 格式的系统提示
├── browser/
│   ├── session.py          # BrowserSession 核心类
│   ├── profile.py          # 浏览器配置
│   ├── events.py           # 事件定义
│   └── watchdogs/          # 各种 watchdog 服务
├── dom/
│   ├── service.py          # DOM 服务，DOM 树构建
│   ├── views.py            # DOM 相关数据模型
│   └── serializer/         # DOM 序列化器
├── tools/
│   ├── service.py          # Tools 工具注册
│   ├── registry/           # 动作注册表
│   └── views.py            # 工具相关模型
├── llm/
│   ├── base.py             # LLM 抽象基类
│   ├── openai/             # OpenAI 适配器
│   ├── anthropic/          # Anthropic 适配器
│   ├── google/             # Google 适配器
│   └── ...
└── ...
```

## 3. 核心功能

### 3.1 Agent (代理)

Agent 是核心编排器，执行以下循环：

```python
async def run(task: str, max_steps: int = 100):
    while n_steps < max_steps:
        1. 获取浏览器状态 (DOM + 截图)
        2. 构建消息发给 LLM
        3. LLM 决定下一步动作
        4. 执行动作 (click, input, navigate 等)
        5. 检查是否完成 (done action)
```

**关键参数**：
- `use_vision`: 是否使用视觉 (截图)
- `max_actions_per_step`: 每步最大动作数
- `use_thinking`: 是否启用内部推理
- `page_extraction_llm`: 页面内容提取用的独立 LLM
- `output_model_schema`: 结构化输出 Pydantic 模型

### 3.2 BrowserSession (浏览器会话)

- 使用 CDP (Chrome DevTools Protocol) 与 Chrome 通信
- 支持本地浏览器和云浏览器 (`use_cloud=True`)
- 支持多标签页管理
- 事件驱动架构

**关键能力**：
- 导航: `navigate`, `go_back`
- 元素交互: `click`, `input`, `scroll`
- 标签管理: `switch`, `close`
- 内容提取: `extract` (使用 LLM 从页面提取数据)

### 3.3 Tools (工具系统)

通过装饰器注册动作：

```python
@self.registry.action('Click element by index')
async def click(params: ClickAction, browser_session: BrowserSession):
    ...
```

**默认工具**：

| 类别 | 工具 |
|------|------|
| 导航 | `search`, `navigate`, `go_back`, `wait` |
| 交互 | `click`, `input`, `upload_file`, `scroll`, `find_text`, `send_keys` |
| Tab 管理 | `switch`, `close` |
| 内容提取 | `extract` (LLM 驱动) |
| 表单 | `dropdown_options`, `select_dropdown` |
| 文件 | `write_file`, `read_file`, `replace_file` |
| JavaScript | `evaluate` (执行自定义 JS) |

### 3.4 DOM Service

- 通过 CDP 获取 DOM 快照
- 构建增强型 DOM 树 (包含可访问性信息)
- 元素可见性检测
- iframe 处理
- 点击元素检测 (基于可访问性树 + 样式)

### 3.5 LLM 集成

支持多种 LLM 提供者：

| 提供者 | 模型 |
|--------|------|
| OpenAI | GPT-4, GPT-4o, GPT-4.1-mini 等 |
| Anthropic | Claude 3.5, Claude Sonnet 等 |
| Google | Gemini 1.5, Gemini 2.0 等 |
| Groq | Llama, Mixtral 等 |
| Ollama | 本地模型 |
| **ChatBrowserUse** | 官方优化模型 (推荐) |

## 4. 使用示例

### 4.1 基本用法

```python
from browser_use import Agent, Browser, ChatBrowserUse
import asyncio

async def main():
    browser = Browser(headless=False)
    agent = Agent(
        task="Find the number of stars of the browser-use repo",
        llm=ChatBrowserUse(),
        browser=browser,
    )
    await agent.run()

asyncio.run(main())
```

### 4.2 带自定义工具

```python
from browser_use import Agent, Tools, ActionResult

tools = Tools()

@tools.action(description='Get weather for a city')
async def get_weather(city: str) -> ActionResult:
    weather = fetch_weather(city)
    return ActionResult(extracted_content=f"Weather in {city}: {weather}")

agent = Agent(task="Check weather in Tokyo", llm=llm, tools=tools)
```

### 4.3 云浏览器

```python
browser = Browser(
    use_cloud=True,  # 使用 Browser Use 云服务
    cloud_proxy_country_code='us',  # 代理位置
)
```

## 5. 技术特点

### 5.1 优势

1. **事件驱动架构**: 通过事件总线解耦，watchdog 模式处理边界情况
2. **结构化输出**: 使用 Pydantic 模型确保 LLM 输出类型安全
3. **多模型支持**: 灵活切换不同 LLM 提供者
4. **云原生**: 支持云浏览器，方便部署和扩展
5. **DOM 增强**: 结合可访问性树提供更准确的元素识别
6. **自定义工具**: 通过装饰器轻松扩展功能

### 5.2 限制

1. **仅支持 Chromium**: 基于 CDP 协议
2. **复杂页面性能**: SPA 页面需要等待 JavaScript 渲染
3. **Anti-bot 检测**: 网站的反爬措施可能导致失败
4. **截图成本**: 视觉模式会增加 token 消耗

## 6. 依赖关系

```
主要依赖:
- aiohttp==3.13.4          # 异步 HTTP
- cdp-use==1.4.5           # CDP 协议封装
- bubus==1.5.6             # 事件总线
- pydantic==2.12.5         # 数据验证
- openai/ anthropic/ google # LLM SDK
- python-dotenv==1.2.1    # 环境变量
```

## 7. 适用场景

- **网页数据抓取**: 结构化数据提取
- **自动化测试**: 端到端测试
- **表单自动填写**: 批量处理
- **网页操作自动化**: 重复性网页任务
- **AI 代理**: 作为 AI Agent 的浏览器工具

## 8. 与本项目的关联

本项目 `qt-use` 可以参考 browser-use 的以下设计：

1. **事件驱动架构**: 使用事件总线解耦组件
2. **CDP 协议集成**: 通过 CDP 控制浏览器
3. **工具注册模式**: 装饰器风格的工具扩展
4. **Agent 模式**: LLM 驱动的决策循环

## 9. 参考链接

- GitHub: https://github.com/browser-use/browser-use
- 文档: https://docs.browser-use.com
- 云服务: https://cloud.browser-use.com
