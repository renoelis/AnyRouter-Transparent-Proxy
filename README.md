# AnyRouter Transparent Proxy

> 一个基于 FastAPI 的轻量级透明 HTTP 代理服务，专为解决 AnyRouter 的 Anthropic API 在 Claude Code for VS Code 插件报错 500 导致无法使用的问题而设计。

## ✨ 特性

- 🚀 **完全透明**：支持所有 HTTP 方法（GET、POST、PUT、PATCH、DELETE、OPTIONS、HEAD）
- 🌊 **流式响应**：使用 `httpx.AsyncClient` 异步处理，完美支持流式传输
- 🔒 **标准兼容**：严格按照 RFC 7230 规范过滤 hop-by-hop 头部
- 🎯 **灵活配置**：支持自定义目标 URL、请求头注入和 System Prompt 替换
- 📍 **链路追踪**：自动维护 X-Forwarded-For 链，便于追踪客户端 IP
- ⚡ **高性能**：基于异步架构，高效处理并发请求

## 🎯 核心功能

### System Prompt 替换

支持动态替换 Anthropic API 请求体中的 `system` 数组第一个元素的 `text` 内容，适用于：

- Claude Code CLI 场景自定义
- Claude Agent SDK 行为调整
- 统一注入系统级提示词

### 智能请求头处理

- **自动过滤**：移除 hop-by-hop 头部（Connection、Keep-Alive 等）
- **Host 重写**：自动将 Host 头改写为目标服务器域名
- **自定义注入**：支持覆盖或添加任意自定义请求头
- **IP 追踪**：智能维护 X-Forwarded-For 链

## 🚀 快速开始

### 环境要求

- Python 3.7+
- pip

### 安装依赖

```bash
# 创建虚拟环境（可选但推荐）
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# 或
.venv\Scripts\activate     # Windows

# 安装依赖
pip install fastapi uvicorn httpx
```

### 启动服务

```bash
# 开发模式（自动重载）
python anthropic_proxy.py

# 或使用 uvicorn 直接启动
uvicorn anthropic_proxy:app --host 0.0.0.0 --port 8088 --reload
```

服务将在 `http://0.0.0.0:8088` 启动。

## ⚙️ 配置说明

编辑 `anthropic_proxy.py` 文件中的配置项：

### 基础配置

```python
# 上游目标服务器地址
TARGET_BASE = "https://q.quuvv.cn"

# 是否保留原始 Host 头（通常设为 False）
PRESERVE_HOST = False
```

### System Prompt 替换

```python
# 设置为字符串以启用替换，设置为 None 则禁用
SYSTEM_PROMPT_REPLACEMENT = "You are Claude Code, Anthropic's official CLI for Claude."

# 常见场景示例：
# Claude Code CLI: "You are Claude Code, Anthropic's official CLI for Claude."
# Claude Agent: "You are a Claude agent, built on Anthropic's Claude Agent SDK."
# 自定义助手: "你是一个专业的Python编程助手"
```

### 自定义请求头

```python
CUSTOM_HEADERS = {
    "User-Agent": "Claude-Proxy/1.1",
    "X-Custom-Header": "Your-Value",
    # 添加更多自定义头...
}
```

## 📖 使用示例

### 作为 API 中转

```bash
# 原始请求
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "content-type: application/json" \
  -d '{"model": "claude-3-5-sonnet-20241022", ...}'

# 通过代理
curl http://localhost:8088/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "content-type: application/json" \
  -d '{"model": "claude-3-5-sonnet-20241022", ...}'
```

### Claude Code 配置

修改 Claude Code 配置使用此代理：

```bash
# 设置环境变量
export ANTHROPIC_BASE_URL=http://localhost:8088
```

## 🏗️ 架构设计

### 请求处理流程

```
客户端请求
    ↓
proxy() 捕获路由
    ↓
filter_request_headers() 过滤请求头
    ↓
process_request_body() 处理请求体（可选替换 system prompt）
    ↓
重写 Host 头 + 注入自定义头 + 添加 X-Forwarded-For
    ↓
httpx.AsyncClient 发起上游请求
    ↓
filter_response_headers() 过滤响应头
    ↓
StreamingResponse 流式返回给客户端
```

### 关键组件

- **路由处理**：`@app.api_route("/{path:path}")` 捕获所有路径
- **异步客户端**：`httpx.AsyncClient` 处理上游请求，60秒超时
- **流式传输**：`StreamingResponse` + `aiter_bytes()` 高效处理大载荷
- **头部过滤**：符合 RFC 7230 规范，双向过滤 hop-by-hop 头部

## 🔧 技术细节

### 请求头过滤规则

根据 RFC 7230 规范，自动移除以下 hop-by-hop 头部：

- Connection
- Keep-Alive
- Proxy-Authenticate
- Proxy-Authorization
- TE
- Trailers
- Transfer-Encoding
- Upgrade

### System Prompt 替换逻辑

1. 检查 `SYSTEM_PROMPT_REPLACEMENT` 是否配置
2. 尝试解析请求体为 JSON
3. 验证 `system` 字段存在且为非空数组
4. 检查第一个元素包含 `text` 字段
5. 替换 `system[0].text` 的内容
6. 重新序列化为 JSON 并返回

失败时自动回退到原始请求体，确保服务稳定性。

## 📝 日志输出

代理服务会输出详细的调试信息：

```
[Proxy] Original body (123 bytes): {...}
[System Replacement] Successfully parsed JSON body
[System Replacement] Original system[0].text: You are Claude Code...
[System Replacement] Replaced with: 你是一个有用的AI助手
[System Replacement] Successfully modified body (original size: 123 bytes, new size: 145 bytes)
```

## 🛡️ 安全性考虑

- ❌ **不跟随重定向**：`follow_redirects=False` 防止重定向攻击
- ⏱️ **请求超时**：60秒超时防止资源耗尽
- 🔍 **错误处理**：上游请求失败时返回 502 状态码
- 📋 **日志记录**：请求体内容被记录（注意不要泄露敏感信息）

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

**注意**：本项目仅供学习和开发测试使用，请确保遵守相关服务的使用条款。