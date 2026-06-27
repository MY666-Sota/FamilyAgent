"""
mcp_client 降级回归测试 — 覆盖 A7 联调发现的网关错误降级 bug。

核心场景（无需真实 MCP Server，用 monkeypatch 模拟 httpx 行为）：
- 502/503/504 网关错误（上游 MCP 进程未就绪）→ 优雅降级 mock
- 连接失败 / 超时 → 优雅降级 mock
- 4xx 客户端错误（工具参数非法）→ 透传 error 状态，不降级
- USE_REAL_MCP=false → 始终 mock
"""
import sys
import os

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from orchestrator import config
from orchestrator import mcp_client


def _make_status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://localhost:9001/sse")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


@pytest.fixture
def real_mcp(monkeypatch):
    """强制 USE_REAL_MCP=true，测试结束自动还原。"""
    monkeypatch.setattr(config, "USE_REAL_MCP", True)
    monkeypatch.setattr(mcp_client._cfg, "USE_REAL_MCP", True)


async def test_mock_when_disabled(monkeypatch):
    """USE_REAL_MCP=false 时始终走 mock。"""
    monkeypatch.setattr(mcp_client._cfg, "USE_REAL_MCP", False)
    r = await mcp_client.call_tool("presenton", "generate_ppt", {"topic": "x"})
    assert r["status"] == "mock_ok"


async def test_gateway_502_degrades_to_mock(real_mcp, monkeypatch):
    """502 网关错误（上游未就绪）应降级 mock，而非透传 error。"""
    async def fake_sse(url, tool, args):
        raise _make_status_error(502)
    monkeypatch.setattr(mcp_client, "_sse_call", fake_sse)

    r = await mcp_client.call_tool("presenton", "generate_ppt", {"topic": "x"})
    assert r["status"] == "mock_ok"


async def test_gateway_503_504_degrade_to_mock(real_mcp, monkeypatch):
    for status in (503, 504, 500):
        async def fake_sse(url, tool, args, _s=status):
            raise _make_status_error(_s)
        monkeypatch.setattr(mcp_client, "_sse_call", fake_sse)
        r = await mcp_client.call_tool("office-word", "generate_document", {"topic": "x"})
        assert r["status"] == "mock_ok", f"HTTP {status} 应降级 mock"


async def test_connect_error_degrades_to_mock(real_mcp, monkeypatch):
    async def fake_sse(url, tool, args):
        raise httpx.ConnectError("connection refused")
    monkeypatch.setattr(mcp_client, "_sse_call", fake_sse)

    r = await mcp_client.call_tool("paddleocr", "ocr_and_grade", {"media_url": "x"})
    assert r["status"] == "mock_ok"


async def test_timeout_degrades_to_mock(real_mcp, monkeypatch):
    async def fake_sse(url, tool, args):
        raise httpx.ReadTimeout("timed out")
    monkeypatch.setattr(mcp_client, "_sse_call", fake_sse)

    r = await mcp_client.call_tool("presenton", "generate_ppt", {"topic": "x"})
    assert r["status"] == "mock_ok"


async def test_4xx_passes_through_as_error(real_mcp, monkeypatch):
    """4xx 客户端错误（参数非法）是真实 bug，应透传 error，不降级 mock。"""
    async def fake_sse(url, tool, args):
        raise _make_status_error(400)
    monkeypatch.setattr(mcp_client, "_sse_call", fake_sse)

    r = await mcp_client.call_tool("presenton", "generate_ppt", {"topic": "x"})
    assert r["status"] == "error"
    assert "400" in r["error"]


async def test_unknown_server_degrades_to_mock(real_mcp):
    """未知 server_name 应降级 mock。"""
    r = await mcp_client.call_tool("nonexistent", "some_tool", {})
    assert r["status"] == "mock_ok"
