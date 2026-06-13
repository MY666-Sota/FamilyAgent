"""
Agent 调度节点：execute_agents / merge_results

每个 Agent 通过 MCP 工具 + LLM 完成具体任务。
当前阶段：mock 实现，真实 MCP 调用通过 mcp_client.call_tool 触发。
"""
import logging
import os
from typing import Any

from orchestrator.mcp_client import call_tool
from orchestrator.mock_services import rag_query
from orchestrator.state import FamilyAgentState

logger = logging.getLogger(__name__)


# ── 各 Agent 处理函数 ──────────────────────────────────────────────

async def _ppt_agent(task: dict, state: FamilyAgentState) -> dict[str, Any]:
    topic = task.get("params", {}).get("topic") or state.get("raw_input", "")
    result = await call_tool(
        "presenton",
        "generate_ppt",
        {"topic": topic, "user_id": state.get("user_id", "")},
    )
    return {
        "agent": "ppt_agent",
        "content_type": "file",
        "content": f"PPT 已生成：{topic}",
        "file_url": result.get("file_url"),
        "raw": result,
    }


async def _homework_agent(task: dict, state: FamilyAgentState) -> dict[str, Any]:
    media_url = state.get("media_url")
    result = await call_tool(
        "paddleocr",
        "ocr_and_grade",
        {
            "media_url": media_url or "",
            "user_id": state.get("user_id", ""),
            "grade": state.get("memory_context", {}).get("profile", {}).get("grade", ""),
        },
    )
    mistakes = result.get("mistakes", [])
    return {
        "agent": "homework_agent",
        "content_type": "text",
        "content": result.get("result", "[mock] 作业批改完成"),
        "file_url": None,
        "mistakes": mistakes,
        "raw": result,
    }


async def _document_agent(task: dict, state: FamilyAgentState) -> dict[str, Any]:
    topic = task.get("params", {}).get("topic") or state.get("raw_input", "")
    result = await call_tool(
        "office-word",
        "generate_document",
        {"topic": topic, "user_id": state.get("user_id", "")},
    )
    return {
        "agent": "document_agent",
        "content_type": "file",
        "content": f"文档已生成：{topic}",
        "file_url": result.get("file_url"),
        "raw": result,
    }


async def _study_plan_agent(task: dict, state: FamilyAgentState) -> dict[str, Any]:
    memory = state.get("memory_context", {})
    mistakes = memory.get("mistakes", [])
    rag = await rag_query(
        user_id=state.get("user_id", ""),
        query=state.get("raw_input", ""),
        mode="simple",
    )
    plan_text = (
        f"[mock] 根据历史 {len(mistakes)} 条错题和知识库，生成个性化学习计划。\n"
        f"知识库参考：{rag['context'][:100]}"
    )
    return {
        "agent": "study_plan_agent",
        "content_type": "text",
        "content": plan_text,
        "file_url": None,
        "raw": {},
    }


async def _qa_agent(task: dict, state: FamilyAgentState) -> dict[str, Any]:
    query = state.get("raw_input", "")
    rag = await rag_query(
        user_id=state.get("user_id", ""),
        query=query,
        mode="simple",
    )
    answer = f"[mock] 问答回复：{rag['context']}"
    return {
        "agent": "qa_agent",
        "content_type": "text",
        "content": answer,
        "file_url": None,
        "raw": rag,
    }


_AGENT_HANDLERS = {
    "ppt_agent": _ppt_agent,
    "homework_agent": _homework_agent,
    "document_agent": _document_agent,
    "study_plan_agent": _study_plan_agent,
    "qa_agent": _qa_agent,
}


# ── 节点函数 ──────────────────────────────────────────────────────

async def execute_agents(state: FamilyAgentState) -> dict[str, Any]:
    """
    按 subtasks 列表依序（串行）执行 Agent。
    depends_on 非 None 时等待前序结果注入 params（简单传递）。
    """
    subtasks = state.get("subtasks") or []
    results: list[dict[str, Any]] = []
    prev_result: dict[str, Any] | None = None

    for task in subtasks:
        agent_name = task.get("agent", "qa_agent")
        handler = _AGENT_HANDLERS.get(agent_name, _qa_agent)

        # 将前序结果注入当前任务参数
        if task.get("depends_on") and prev_result:
            task = {**task, "params": {**task.get("params", {}), "prev": prev_result}}

        try:
            logger.info("[agents] 执行 %s", agent_name)
            result = await handler(task, state)
        except Exception as exc:
            logger.error("[agents] %s 执行失败: %s", agent_name, exc)
            result = {
                "agent": agent_name,
                "content_type": "text",
                "content": f"[错误] {agent_name} 执行失败，请稍后重试。",
                "file_url": None,
                "error": str(exc),
            }

        results.append(result)
        prev_result = result

    return {"agent_results": results}


def merge_results(state: FamilyAgentState) -> dict[str, Any]:
    """
    合并多 Agent 结果为单一输出。
    有文件输出优先返回文件；纯文本则拼接。
    """
    results = state.get("agent_results") or []
    if not results:
        return {
            "final_output": {
                "content_type": "text",
                "content": "任务已完成，但没有产生输出。",
                "file_url": None,
            },
            "need_approval": False,
        }

    # 有文件输出优先
    file_result = next((r for r in results if r.get("file_url")), None)
    if file_result:
        return {
            "final_output": {
                "content_type": "file",
                "content": file_result.get("content", ""),
                "file_url": file_result["file_url"],
            },
            "need_approval": False,
        }

    # 纯文本合并
    combined = "\n\n".join(r.get("content", "") for r in results if r.get("content"))
    return {
        "final_output": {
            "content_type": "text",
            "content": combined or "处理完成。",
            "file_url": None,
        },
        "need_approval": False,
    }
