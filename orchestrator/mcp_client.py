"""
MCP Client — 按 INTERFACE_CONTRACT.md §2 调用窗口3 暴露的 MCP Server。

当前阶段：mock 实现。
读取 shared/mcp_registry.json 获取 server 列表；
真实 MCP 调用（SSE/stdio transport）在窗口3 就绪后切换 _USE_REAL_MCP = True 即可。
"""
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# shared/mcp_registry.json 相对于本文件的位置：
# orchestrator/mcp_client.py → ../shared/mcp_registry.json
_REGISTRY_PATH = Path(__file__).parent.parent / "shared" / "mcp_registry.json"

_USE_REAL_MCP = False


def _load_registry() -> list[dict[str, Any]]:
    try:
        return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("无法读取 mcp_registry.json: %s，返回空列表", exc)
        return []


# 缓存注册表，避免每次调用都重新读文件
_registry: list[dict[str, Any]] | None = None


def get_registry() -> list[dict[str, Any]]:
    global _registry
    if _registry is None:
        _registry = _load_registry()
    return _registry


def reload_registry() -> list[dict[str, Any]]:
    """强制重新读取注册表（窗口3 更新后可调用）。"""
    global _registry
    _registry = _load_registry()
    return _registry


async def call_tool(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """
    调用指定 MCP Server 的工具。
    server_name 对应 mcp_registry.json 中的 name 字段。
    """
    registry = get_registry()
    server = next((s for s in registry if s["name"] == server_name), None)

    if _USE_REAL_MCP and server:
        return await _real_call(server, tool_name, arguments)

    # mock：记录调用，返回占位结果
    logger.info(
        "[mock MCP] server=%s tool=%s args=%s",
        server_name, tool_name, arguments,
    )
    return {
        "status": "mock_ok",
        "server": server_name,
        "tool": tool_name,
        "result": f"[mock] {tool_name} 执行成功（真实服务未就绪）",
        "file_url": None,
    }


async def _real_call(
    server: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """真实 MCP 调用占位（SSE transport）。窗口3 就绪后实现。"""
    transport = server.get("transport", "sse")
    if transport == "sse":
        # TODO: 使用 mcp Python SDK 的 SSE client
        # from mcp import ClientSession
        # from mcp.client.sse import sse_client
        raise NotImplementedError("SSE MCP client 待窗口3 就绪后实现")
    raise NotImplementedError(f"transport={transport} 暂不支持")
