"""
MCP Client — 按 INTERFACE_CONTRACT.md §2 调用窗口3 暴露的 MCP Server。

当前阶段：支持真实 SSE transport（需窗口3 MCP Servers 启动），
同时在 server 未就绪时优雅降级到 mock，保证 mock 模式仍可独立测试。
"""
import json
import logging
from typing import Any

import httpx

from orchestrator import config as _cfg

logger = logging.getLogger(__name__)


async def call_tool(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """
    调用指定 MCP Server 的工具。
    server_name 对应 config.MCP_SERVERS 的 key。
    USE_REAL_MCP=false 时始终 mock。
    USE_REAL_MCP=true 时尝试真实调用，失败后自动降级 mock。
    """
    if not _cfg.USE_REAL_MCP:
        return await _mock_call(server_name, tool_name, arguments)

    server_url = _cfg.MCP_SERVERS.get(server_name)
    if not server_url:
        logger.warning("[MCP] 未知 server=%s，使用 mock", server_name)
        return await _mock_call(server_name, tool_name, arguments)

    try:
        return await _sse_call(server_url, tool_name, arguments)
    except httpx.ConnectError as exc:
        logger.warning("[MCP] SSE 连接失败 server=%s url=%s，降级 mock: %s",
                       server_name, server_url, exc)
        return await _mock_call(server_name, tool_name, arguments)
    except Exception as exc:
        logger.error("[MCP] 调用异常 server=%s tool=%s: %s", server_name, tool_name, exc)
        return {
            "status": "error",
            "server": server_name,
            "tool": tool_name,
            "error": str(exc),
            "file_url": None,
        }


async def _mock_call(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Mock 调用：记录参数，返回占位结果。"""
    logger.info("[mock MCP] server=%s tool=%s args=%s", server_name, tool_name, arguments)
    return {
        "status": "mock_ok",
        "server": server_name,
        "tool": tool_name,
        "result": f"[mock] {tool_name} 执行成功（真实服务未就绪或 USE_REAL_MCP=false）",
        "file_url": None,
    }


async def _sse_call(
    server_url: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """
    真实 SSE MCP 调用。
    窗口3 的 MCP Servers 需实现 SSE endpoint，接收 JSON-RPC 2.0 请求：
    {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}, "id": 1}
    """
    async with httpx.AsyncClient(timeout=30) as client:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": 1,
        }
        r = await client.post(server_url, json=payload)
        r.raise_for_status()
        resp = r.json()
        if resp.get("error"):
            raise RuntimeError(f"MCP error: {resp['error']}")
        result = resp.get("result", {})
        logger.info("[real MCP] tool=%s status=%s", tool_name, result.get("status", "ok"))
        return {
            "status": "ok",
            "result": result.get("content", ""),
            "file_url": result.get("file_url"),
            "raw": result,
        }