# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a FastAPI-based transparent HTTP proxy for Anthropic API requests. It forwards all incoming requests to a configured target base URL while properly handling headers, streaming responses, and maintaining transparency.

**Key Architecture:**
- Single-file application (`anthropic_proxy.py`) using FastAPI
- Catch-all route handler proxies all HTTP methods (GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD)
- Uses `httpx.AsyncClient` for upstream requests with streaming support
- Headers are filtered to remove hop-by-hop headers per RFC 7230
- Supports custom header injection and X-Forwarded-For tracking

## Development Commands

### Setup
```bash
# Create virtual environment (if not exists)
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate  # macOS/Linux
# or
.venv/Scripts/activate  # Windows

# Install dependencies
pip install fastapi uvicorn httpx
```

### Running the Proxy
```bash
# Development mode with auto-reload
python anthropic_proxy.py

# Or using uvicorn directly
uvicorn anthropic_proxy:app --host 0.0.0.0 --port 8080 --reload
```

The proxy will start on `http://0.0.0.0:8080` by default.

## Configuration

**Important configuration variables in `anthropic_proxy.py`:**

- `TARGET_BASE` (line 11): The upstream target URL to proxy requests to
- `PRESERVE_HOST` (line 12): Whether to preserve the original Host header (default: False)
- `CUSTOM_HEADERS` (line 26): Dictionary to inject/override headers in proxied requests
- `HOP_BY_HOP_HEADERS` (line 14): Set of headers to strip per HTTP spec

## Code Structure

**Request Flow:**
1. `proxy()` function (line 58) catches all routes via `/{path:path}`
2. Constructs target URL by combining `TARGET_BASE` with incoming path and query
3. `filter_request_headers()` (line 35) strips hop-by-hop headers
4. Host header is set to target domain unless `PRESERVE_HOST=True`
5. Custom headers are injected, X-Forwarded-For is appended
6. Upstream request sent via `httpx.AsyncClient` with 60s timeout
7. `filter_response_headers()` (line 47) strips hop-by-hop headers from response
8. Response streamed back to client via `StreamingResponse` with `aiter_bytes()`

**Header Handling:**
- Hop-by-hop headers are filtered in both directions per RFC 7230
- Host header rewritten to target domain by default
- X-Forwarded-For chain maintained for client IP tracking
- Custom headers override any incoming headers with same name

## Notes

- The proxy does not follow redirects (`follow_redirects=False`)
- Request timeout is set to 60 seconds
- All responses are streamed to handle large payloads efficiently
- Body content is logged to console (line 68) for debugging
