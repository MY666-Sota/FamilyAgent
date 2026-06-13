"""
Router 节点：
  - route_to_agent  : 单任务直达，决定走哪个 Agent
  - plan_subtasks   : 复杂任务拆解为有序子任务列表
"""
import logging
from typing import Any

from orchestrator.state import FamilyAgentState

logger = logging.getLogger(__name__)

# intent → agent 名称的静态映射
_INTENT_AGENT_MAP: dict[str, str] = {
    "ppt": "ppt_agent",
    "homework": "homework_agent",
    "document": "document_agent",
    "study_plan": "study_plan_agent",
    "qa": "qa_agent",
    "unknown": "qa_agent",  # 降级到问答
}


def route_to_agent(state: FamilyAgentState) -> dict[str, Any]:
    intent = state.get("intent", "unknown")
    agent_name = _INTENT_AGENT_MAP.get(intent, "qa_agent")
    logger.info("[router] single route → %s (intent=%s)", agent_name, intent)
    return {
        "route": "single",
        "subtasks": [
            {
                "agent": agent_name,
                "action": intent,
                "params": state.get("params", {}),
                "depends_on": None,
            }
        ],
    }


def plan_subtasks(state: FamilyAgentState) -> dict[str, Any]:
    """
    复杂任务拆解。
    当前实现：基于 intent=multi 时，尝试从 params 解析子意图；
    真实场景可替换为 LLM 规划节点。
    """
    params = state.get("params", {})
    raw = state.get("raw_input", "")

    # 简单示例：若同时包含"错题"和"PPT"，拆成两步
    subtasks: list[dict[str, Any]] = []

    if "homework" in raw or "错题" in raw or "作业" in raw:
        subtasks.append({
            "agent": "homework_agent",
            "action": "homework",
            "params": params,
            "depends_on": None,
        })

    if "ppt" in raw.lower() or "演示" in raw or "幻灯片" in raw:
        subtasks.append({
            "agent": "ppt_agent",
            "action": "ppt",
            "params": params,
            "depends_on": "homework_agent" if subtasks else None,
        })

    # 兜底：无法拆解则单步 qa
    if not subtasks:
        subtasks = [
            {
                "agent": "qa_agent",
                "action": "qa",
                "params": params,
                "depends_on": None,
            }
        ]

    logger.info("[router] multi plan → %d subtasks", len(subtasks))
    return {"route": "multi", "subtasks": subtasks}
