# -*- coding: utf-8 -*-
"""Qwen Audio Agent frontend MCP server for the Windows GSM phone service."""
from __future__ import annotations
import json
import os
import urllib.request
import urllib.error
from mcp.server.fastmcp import FastMCP

BASE_URL = os.getenv("PHONE_SERVICE_URL", "http://127.0.0.1:8787").rstrip("/")
TOKEN = os.getenv("PHONE_API_TOKEN", "")
mcp = FastMCP("phone")

def _request(method: str, path: str, payload=None):
    if not TOKEN:
        return {"ok": False, "error": "PHONE_API_TOKEN در محیط MCP تنظیم نشده است."}
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            raw = response.read().decode("utf-8")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"ok": False, "error": "پاسخ سرویس JSON معتبر نیست", "raw": raw[:2000]}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except Exception:
            detail = raw[:2000]
        return {"ok": False, "http_status": exc.code, "error": detail}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

def _json(data):
    return json.dumps(data, ensure_ascii=False)

@mcp.tool()
def ping() -> str:
    """تست اتصال MCP به سرویس مودم؛ هیچ تماسی برقرار نمی‌کند."""
    return _json(_request("GET", "/api/status"))

@mcp.tool()
def dial(phone_number: str) -> str:
    """با شماره‌ای که کاربر مشخص کرده تماس خروجی برقرار کن. شماره را عیناً ارسال کن."""
    return _json(_request("POST", "/api/dial", {"phone_number": phone_number}))

@mcp.tool()
def answer() -> str:
    """به تماس ورودی در حال زنگ خوردن پاسخ بده."""
    return _json(_request("POST", "/api/answer", {}))

@mcp.tool()
def hangup() -> str:
    """تماس فعلی را قطع کن."""
    return _json(_request("POST", "/api/hangup", {}))

@mcp.tool()
def get_call_status() -> str:
    """وضعیت فعلی تماس، شماره و جهت تماس را از مودم بخوان."""
    return _json(_request("GET", "/api/status"))

@mcp.tool()
def get_recent_call_events() -> str:
    """رویدادهای اخیر مودم مانند زنگ، اتصال و قطع تماس را بخوان."""
    return _json(_request("GET", "/api/events"))

if __name__ == "__main__":
    # MCP stdio protocol owns stdout. Do not print diagnostics to stdout.
    mcp.run(transport="stdio")
