from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import httpx
import json
import os
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
# 主站：https://anyrouter.top
# 备用：https://q.quuvv.cn
load_dotenv()
TARGET_BASE_URL = os.getenv("API_BASE_URL", "https://anyrouter.top")
print(f"Base Url: {TARGET_BASE_URL}")
PRESERVE_HOST = False  # 是否保留原始 Host

# System prompt 替换配置
# 设置为字符串以替换请求体中 system 数组的第一个元素的 text 内容
# 设置为 None 则保持原样不修改
# 通过环境变量 SYSTEM_PROMPT_REPLACEMENT 配置，默认为 None
SYSTEM_PROMPT_REPLACEMENT = os.getenv("SYSTEM_PROMPT_REPLACEMENT")  # 例如: "你是一个有用的AI助手"
print(f"System prompt replacement: {SYSTEM_PROMPT_REPLACEMENT}")


# 自定义 Header 配置
# 从 env/.env.headers.json 文件加载，如果文件不存在或解析失败，则使用空字典 {}
def load_custom_headers() -> dict:
    """
    从 env/.env.headers.json 文件加载自定义请求头配置

    Returns:
        dict: 自定义请求头字典，如果加载失败则返回空字典 {}
    """
    headers_file = "env/.env.headers.json"

    # 检查文件是否存在
    if not os.path.exists(headers_file):
        print(f"[Custom Headers] Config file '{headers_file}' not found, using default empty dict {{}}")
        return {}

    # 尝试读取和解析 JSON 文件
    try:
        with open(headers_file, 'r', encoding='utf-8') as f:
            headers = json.load(f)

        # 验证是否为字典类型
        if not isinstance(headers, dict):
            print(f"[Custom Headers] Config file content is not a dict (type: {type(headers)}), using default empty dict {{}}")
            return {}

        # 过滤掉以 __ 开头的注释字段
        filtered_headers = {k: v for k, v in headers.items() if not k.startswith("__")}

        print(f"[Custom Headers] Successfully loaded {len(filtered_headers)} custom headers from '{headers_file}'")
        if filtered_headers:
            print(f"[Custom Headers] Loaded headers: {list(filtered_headers.keys())}")

        return filtered_headers

    except json.JSONDecodeError as e:
        print(f"[Custom Headers] Failed to parse JSON from '{headers_file}': {e}, using default empty dict {{}}")
        return {}
    except Exception as e:
        print(f"[Custom Headers] Failed to load '{headers_file}': {e}, using default empty dict {{}}")
        return {}


CUSTOM_HEADERS = load_custom_headers()

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
    target_url = f"{TARGET_BASE_URL}/{path}"
    if query:
        target_url += f"?{query}"

    # 读取 body
    body = await request.body()
    # 注释掉详细日志,避免输出过长
    # try:
    #     data = json.loads(body.decode('utf-8'))
    #     print(f"[Proxy] Original body ({len(body)} bytes): {data}")
    # except (json.JSONDecodeError, UnicodeDecodeError) as e:
    #     print(f"[Proxy] Failed to parse JSON: {e}")
    print(f"[Proxy] Request: {request.method} {path} (body: {len(body)} bytes)")

    # 处理请求体（替换 system prompt）
    body = process_request_body(body)

    # 复制并过滤请求头
    incoming_headers = list(request.headers.items())
    forward_headers = filter_request_headers(incoming_headers)

    # 设置 Host
    if not PRESERVE_HOST:
        parsed = urlparse(TARGET_BASE_URL)
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
        print(f"[Proxy] Upstream response: {resp.status_code} from {target_url}")
        if resp.status_code >= 400:
            # 打印错误响应的前 500 字符
            body_preview = (await resp.aread())[:500]
            print(f"[Proxy] Error response preview: {body_preview}")
    except httpx.RequestError as e:
        print(f"[Proxy] Upstream request failed: {e}")
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