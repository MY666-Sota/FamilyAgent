"""
Memory 节点：
  - load_memory : 从 Mem0 取回用户画像 / 错题 / 历史
  - save_memory : 将本次任务结果写回 Mem0
"""
import logging
from typing import Any

from orchestrator.mock_services import memory_get, memory_post
from orchestrator.state import FamilyAgentState

logger = logging.getLogger(__name__)


async def load_memory(state: FamilyAgentState) -> dict[str, Any]:
    user_id = state.get("user_id", "unknown")
    try:
        ctx = await memory_get(user_id)
        logger.debug("[memory] load user_id=%s profile=%s", user_id, ctx.get("profile"))
    except Exception as exc:
        logger.error("[memory] load 失败 user_id=%s err=%s", user_id, exc)
        ctx = {"profile": {}, "mistakes": [], "history": []}
    return {"memory_context": ctx}


async def save_memory(state: FamilyAgentState) -> dict[str, Any]:
    user_id = state.get("user_id", "unknown")
    intent = state.get("intent", "")
    results = state.get("agent_results") or []

    # 作业批改结果写入错题记录
    if intent == "homework":
        for r in results:
            mistakes = r.get("mistakes")
            if mistakes:
                try:
                    await memory_post(user_id, "mistake", {"items": mistakes})
                except Exception as exc:
                    logger.error("[memory] save mistake 失败: %s", exc)

    # 本次任务写入历史
    try:
        await memory_post(
            user_id,
            "history",
            {
                "intent": intent,
                "summary": state.get("final_output", {}).get("content", "")[:200],
            },
        )
    except Exception as exc:
        logger.error("[memory] save history 失败: %s", exc)

    return {}
