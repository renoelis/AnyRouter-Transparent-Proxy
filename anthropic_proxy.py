from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
import httpx
import json
from typing import Iterable
from urllib.parse import urlparse

# Shared HTTP client for connection pooling and proper lifecycle management
http_client: httpx.AsyncClient = None  # type: ignore


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Manage application lifespan events"""
    global http_client
    # Startup: Initialize HTTP client
    http_client = httpx.AsyncClient(follow_redirects=False, timeout=60.0)
    yield
    # Shutdown: Close HTTP client
    await http_client.aclose()


app = FastAPI(
    title="Anthropic Transparent Proxy",
    version="1.1",
    lifespan=lifespan
)

# ===== 基础配置 =====

TARGET_BASE = "https://q.quuvv.cn"
PRESERVE_HOST = False  # 是否保留原始 Host

# System prompt 替换配置
# 设置为字符串以替换请求体中 system 数组的第一个元素的 text 内容
# 设置为 None 则保持原样不修改
SYSTEM_PROMPT_REPLACEMENT = "You are Claude Code, Anthropic's official CLI for Claude."  # 例如: "你是一个有用的AI助手"
# SYSTEM_PROMPT_REPLACEMENT =  None

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

# 可选自定义 Header（覆盖原请求同名项）
CUSTOM_HEADERS = {
    # 例如：
    # "User-Agent": "Claude-Proxy/1.0",
    # "x-anthropic-system-prompt": "你是一个透明代理，请保持请求不变。",
}


# ===== 工具函数 =====

def filter_request_headers(headers: Iterable[tuple]) -> dict:
    out = {}
    for k, v in headers:
        lk = k.lower()
        if lk in HOP_BY_HOP_HEADERS:
            continue
        if lk == "host" and not PRESERVE_HOST:
            continue
        # 移除 Content-Length，让 httpx 根据实际内容自动计算
        # 因为我们可能会修改请求体，导致长度改变
        if lk == "content-length":
            continue
        out[k] = v
    return out


def filter_response_headers(headers: Iterable[tuple]) -> dict:
    out = {}
    for k, v in headers:
        if k.lower() in HOP_BY_HOP_HEADERS:
            continue
        out[k] = v
    return out


def process_request_body(body: bytes) -> bytes:
    """
    处理请求体，替换 system 数组中第一个元素的 text 内容

    Args:
        body: 原始请求体（bytes）

    Returns:
        处理后的请求体（bytes），如果无法处理则返回原始 body
    """
    # 如果未配置替换文本，直接返回原始 body
    if SYSTEM_PROMPT_REPLACEMENT is None:
        print("[System Replacement] Not configured, keeping original body")
        # try:
        #     print(f"[System Replacement None] Original system[0].text: {json.loads(body.decode('utf-8'))['system'][0]['text']}")
        # except (json.JSONDecodeError, UnicodeDecodeError, KeyError, IndexError, TypeError) as e:
        #     print(f"[System Replacement None] Failed to parse or access system prompt: {e}")
        return body

    # 尝试解析 JSON
    try:
        data = json.loads(body.decode('utf-8'))
        print("[System Replacement] Successfully parsed JSON body")
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"[System Replacement] Failed to parse JSON: {e}, keeping original body")
        return body

    # 检查 system 字段是否存在且为列表
    if "system" not in data:
        print("[System Replacement] No 'system' field found, keeping original body")
        return body

    if not isinstance(data["system"], list):
        print(f"[System Replacement] 'system' field is not a list (type: {type(data['system'])}), keeping original body")
        return body

    if len(data["system"]) == 0:
        print("[System Replacement] 'system' array is empty, keeping original body")
        return body

    # 获取第一个元素
    first_element = data["system"][0]

    # 检查第一个元素是否有 'text' 字段
    if not isinstance(first_element, dict) or "text" not in first_element:
        print(f"[System Replacement] First element doesn't have 'text' field, keeping original body")
        return body

    # 记录原始内容
    original_text = first_element["text"]
    print(f"[System Replacement] Original system[0].text: {original_text[:100]}..." if len(original_text) > 100 else f"[System Replacement] Original system[0].text: {original_text}")

    # 执行替换
    first_element["text"] = SYSTEM_PROMPT_REPLACEMENT
    print(f"[System Replacement] Replaced with: {SYSTEM_PROMPT_REPLACEMENT[:100]}..." if len(SYSTEM_PROMPT_REPLACEMENT) > 100 else f"[System Replacement] Replaced with: {SYSTEM_PROMPT_REPLACEMENT}")

    print(f"[System Replacement] original_text == SYSTEM_PROMPT_REPLACEMENT:{SYSTEM_PROMPT_REPLACEMENT == original_text}")

    # 转换回 JSON bytes
    try:
        # 这里必须加 separators 压缩空格，我也不知道为什么有空格不行。。。
        modified_body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        print(f"[System Replacement] Successfully modified body (original size: {len(body)} bytes, new size: {len(modified_body)} bytes)")
        return modified_body
    except Exception as e:
        print(f"[System Replacement] Failed to serialize modified JSON: {e}, keeping original body")
        return body


# ===== 主代理逻辑 =====

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy(path: str, request: Request):
    # 构造目标 URL
    query = request.url.query
    target_url = f"{TARGET_BASE}/{path}"
    if query:
        target_url += f"?{query}"

    # 读取 body
    body = await request.body()
    print(f"[Proxy] Original body ({len(body)} bytes): {body[:200]}..." if len(body) > 200 else f"[Proxy] Original body: {body}")

    # 处理请求体（替换 system prompt）
    body = process_request_body(body)

    # 复制并过滤请求头
    incoming_headers = list(request.headers.items())
    forward_headers = filter_request_headers(incoming_headers)

    # 设置 Host
    if not PRESERVE_HOST:
        parsed = urlparse(TARGET_BASE)
        forward_headers["Host"] = parsed.netloc

    # 注入自定义 Header
    for k, v in CUSTOM_HEADERS.items():
        forward_headers[k] = v

    # 添加 X-Forwarded-For
    client_host = request.client.host if request.client else None
    if client_host:
        existing = forward_headers.get("X-Forwarded-For")
        forward_headers["X-Forwarded-For"] = f"{existing}, {client_host}" if existing else client_host

    # 发起上游请求
    try:
        resp = await http_client.request(
            method=request.method,
            url=target_url,
            headers=forward_headers,
            content=body,
        )
    except httpx.RequestError as e:
        return Response(content=f"Upstream request failed: {e}", status_code=502)

    response_headers = filter_response_headers(resp.headers.items())

    async def iter_response():
        async for chunk in resp.aiter_bytes():
            yield chunk

    return StreamingResponse(
        iter_response(),
        status_code=resp.status_code,
        headers=response_headers,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("anthropic_proxy:app", host="0.0.0.0", port=8088, reload=True)