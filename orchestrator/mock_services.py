"""
Mock 客户端：在真实服务（Mem0 / RAG / 回调）就绪前，
按 INTERFACE_CONTRACT.md 的接口签名返回合理的假数据。
切换到真实服务：在 .env 中设置对应 USE_REAL_*=true，无需改代码。
"""
import logging
from typing import Any

import httpx

from orchestrator import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Mem0 记忆服务（接口契约 §1.2）
# GET  {MEM0_BASE_URL}/v1/memory/{user_id}
# POST {MEM0_BASE_URL}/v1/memory/{user_id}
# ─────────────────────────────────────────────────────────────

async def memory_get(user_id: str) -> dict[str, Any]:
    if config.USE_REAL_MEM0:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{config.MEM0_BASE_URL}/v1/memory/{user_id}")
            resp.raise_for_status()
            return resp.json()
    logger.debug("[mock] memory_get user_id=%s", user_id)
    return {
        "profile": {"name": user_id, "grade": "未知", "preferences": []},
        "mistakes": [],
        "history": [],
    }


async def memory_post(user_id: str, memory_type: str, data: dict[str, Any]) -> bool:
    if config.USE_REAL_MEM0:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{config.MEM0_BASE_URL}/v1/memory/{user_id}",
                json={"type": memory_type, "data": data},
            )
            resp.raise_for_status()
            return True
    logger.debug("[mock] memory_post user_id=%s type=%s", user_id, memory_type)
    return True


# ─────────────────────────────────────────────────────────────
# RAG 知识库（接口契约 §1.1）
# POST {RAG_BASE_URL}/v1/rag/query
# ─────────────────────────────────────────────────────────────

async def rag_query(
    user_id: str,
    query: str,
    mode: str = "simple",
    top_k: int = 5,
) -> dict[str, Any]:
    if config.USE_REAL_RAG:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{config.RAG_BASE_URL}/v1/rag/query",
                json={"user_id": user_id, "query": query, "mode": mode, "top_k": top_k},
            )
            resp.raise_for_status()
            return resp.json()
    logger.debug("[mock] rag_query user_id=%s query=%r", user_id, query[:40])
    return {
        "context": f"[mock RAG] 关于「{query[:30]}」的相关知识暂无真实数据。",
        "sources": [],
    }


# ─────────────────────────────────────────────────────────────
# 渠道回调（接口契约 §1.3）
# POST {CHANNEL_BASE_URL}/v1/reply
# ─────────────────────────────────────────────────────────────

async def channel_reply(
    user_id: str,
    content_type: str,
    content: str,
    file_url: str | None = None,
) -> bool:
    payload = {
        "user_id": user_id,
        "content_type": content_type,
        "content": content,
        "file_url": file_url,
    }
    if config.USE_REAL_CHANNEL:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{config.CHANNEL_BASE_URL}/v1/reply", json=payload)
            resp.raise_for_status()
            return True
    logger.info("[mock] channel_reply → %s", payload)
    return True
