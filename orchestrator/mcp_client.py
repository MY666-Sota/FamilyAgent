"""
MCP Client — 按 INTERFACE_CONTRACT.md §2 调用窗口3 暴露的 MCP Server。

A7 联调修正：窗口3 使用标准 MCP SSE transport（GET /sse 建连 → POST
/messages/?session_id=xxx），而非裸 JSON-RPC POST。改用官方 mcp SDK 的
sse_client + ClientSession 完成握手与工具调用。

服务未就绪 / 网关错误 / 连接超时时优雅降级到 mock，保证 mock 模式仍可独立测试。
"""
import json
import logging
from typing import Any

import httpx

from orchestrator import config as _cfg

logger = logging.getLogger(__name__)

# 官方 SDK 为可选依赖：未安装时真实调用直接降级 mock，不影响 mock 模式。
try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    _MCP_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - 环境缺 SDK 时的兜底
    ClientSession = None
    sse_client = None
    _MCP_SDK_AVAILABLE = False


# 视为「服务不可用」的连接级异常名（含官方 SDK / anyio / httpx 的各种形态）。
# 命中即降级 mock；其余异常透传 error 供上层排查。
_CONNECTION_ERROR_NAMES = {
    "ConnectError", "ConnectTimeout", "ReadTimeout", "PoolTimeout",
    "ConnectionRefusedError", "ConnectionResetError", "ReadError",
    "RemoteProtocolError", "TimeoutError",
}


def _flatten_exc(exc: BaseException) -> list[BaseException]:
    """展平 ExceptionGroup（anyio task group 抛出），便于逐个判别根因。"""
    if isinstance(exc, BaseExceptionGroup):
        out: list[BaseException] = []
        for sub in exc.exceptions:
            out.extend(_flatten_exc(sub))
        return out
    return [exc]


def _is_service_unavailable(exc: BaseException) -> bool:
    """判断异常是否属于「服务未就绪 / 网关错误」——这类应降级 mock。"""
    for e in _flatten_exc(exc):
        if type(e).__name__ in _CONNECTION_ERROR_NAMES:
            return True
        # SSE 握手阶段的网关错误（502/503/504）：上游 MCP 进程未就绪。
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code >= 500:
            return True
    return False


async def call_tool(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """
    调用指定 MCP Server 的工具。
    server_name 对应 config.MCP_SERVERS 的 key。
    USE_REAL_MCP=false 时始终 mock。
    USE_REAL_MCP=true 时尝试真实调用，连接/网关失败后自动降级 mock。
    """
    if not _cfg.USE_REAL_MCP:
        return await _mock_call(server_name, tool_name, arguments)

    server_url = _cfg.MCP_SERVERS.get(server_name)
    if not server_url:
        logger.warning("[MCP] 未知 server=%s，使用 mock", server_name)
        return await _mock_call(server_name, tool_name, arguments)

    if not _MCP_SDK_AVAILABLE:
        logger.warning("[MCP] 官方 mcp SDK 未安装，降级 mock（server=%s）", server_name)
        return await _mock_call(server_name, tool_name, arguments)

    try:
        return await _sse_call(server_url, tool_name, arguments)
    except BaseException as exc:  # noqa: BLE001 - 需捕获 ExceptionGroup
        if _is_service_unavailable(exc):
            logger.warning("[MCP] 服务不可用 server=%s url=%s（连接失败/网关错误/超时），降级 mock: %s",
                           server_name, server_url, exc)
            return await _mock_call(server_name, tool_name, arguments)
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
    真实 MCP 调用（标准 SSE transport，经官方 mcp SDK）。

    流程：GET {server_url} 建立 SSE 连接 → 服务端回 endpoint 事件 →
    SDK 自动 POST JSON-RPC 到 /messages/?session_id=xxx → 结果经 SSE 流回。

    注意：解析放在 async with 块外执行。若 _parse_tool_result 在块内抛异常，
    anyio task group 会在 teardown 时把它包成 ExceptionGroup 并扰乱 cancel scope，
    导致异常逃逸顶层。先在块内取回 result、干净退出上下文，再在块外解析/抛错。
    """
    async with sse_client(server_url, timeout=30) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
    return _parse_tool_result(tool_name, result)


def _parse_tool_result(tool_name: str, result: Any) -> dict[str, Any]:
    """
    将官方 SDK 的 CallToolResult 规整为编排核心内部统一结构。
    CallToolResult.content 是 TextContent/ImageContent 列表；
    文本内容通常是 JSON 字符串，尝试解析出 file_url 等字段。
    """
    if getattr(result, "isError", False):
        text = _extract_text(result)
        raise RuntimeError(f"MCP tool error: {text}")

    # 优先用 structuredContent（SDK 已结构化）
    structured = getattr(result, "structuredContent", None)
    text = _extract_text(result)
    payload: dict[str, Any] = {}

    if isinstance(structured, dict):
        payload = structured
    elif text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                payload = parsed
        except (json.JSONDecodeError, ValueError):
            payload = {}

    logger.info("[real MCP] tool=%s ok，content_len=%d", tool_name, len(text))
    return {
        "status": "ok",
        "result": text,
        "file_url": payload.get("file_url") or payload.get("url") or payload.get("path"),
        "raw": payload or {"text": text},
    }


def _extract_text(result: Any) -> str:
    """从 CallToolResult.content 中拼接所有文本内容。"""
    parts: list[str] = []
    for item in getattr(result, "content", []) or []:
        t = getattr(item, "text", None)
        if t:
            parts.append(t)
    return "\n".join(parts)
