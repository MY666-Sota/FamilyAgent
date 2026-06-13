"""
Mock 客户端：在真实服务（Mem0 / RAG / 回调）就绪前，
按 INTERFACE_CONTRACT.md 的接口签名返回合理的假数据。
切换到真实服务只需替换这里的实现，调用方不变。
"""
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Mem0 记忆服务（接口契约 §1.2）
# GET  http://localhost:8082/v1/memory/{user_id}
# POST http://localhost:8082/v1/memory/{user_id}
# ─────────────────────────────────────────────────────────────
MEM0_BASE = "http://localhost:8082"
_USE_REAL_MEM0 = False   # 切换为 True 即对接真实 Mem0


async def memory_get(user_id: str) -> dict[str, Any]:
    if _USE_REAL_MEM0:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{MEM0_BASE}/v1/memory/{user_id}")
            resp.raise_for_status()
            return resp.json()
    logger.debug("[mock] memory_get user_id=%s", user_id)
    return {
        "profile": {"name": user_id, "grade": "未知", "preferences": []},
        "mistakes": [],
        "history": [],
    }


async def memory_post(user_id: str, memory_type: str, data: dict[str, Any]) -> bool:
    if _USE_REAL_MEM0:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{MEM0_BASE}/v1/memory/{user_id}",
                json={"type": memory_type, "data": data},
            )
            resp.raise_for_status()
            return True
    logger.debug("[mock] memory_post user_id=%s type=%s", user_id, memory_type)
    return True


# ─────────────────────────────────────────────────────────────
# RAG 知识库（接口契约 §1.1）
# POST http://localhost:5001/v1/rag/query
# ─────────────────────────────────────────────────────────────
RAG_BASE = "http://localhost:5001"
_USE_REAL_RAG = False


async def rag_query(
    user_id: str,
    query: str,
    mode: str = "simple",
    top_k: int = 5,
) -> dict[str, Any]:
    if _USE_REAL_RAG:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{RAG_BASE}/v1/rag/query",
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
# POST http://localhost:8080/v1/reply
# ─────────────────────────────────────────────────────────────
CHANNEL_BASE = "http://localhost:8080"
_USE_REAL_CHANNEL = False


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
    if _USE_REAL_CHANNEL:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{CHANNEL_BASE}/v1/reply", json=payload)
            resp.raise_for_status()
            return True
    logger.info("[mock] channel_reply → %s", payload)
    return True
