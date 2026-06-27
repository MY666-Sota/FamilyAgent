"""
graph.py — LangGraph StateGraph 组装

节点流转（按架构设计文档 §3.3）：
START → input_guardrail
  ├─(不通过)→ friendly_reject → END
  └─(通过)→ load_memory → classify_intent → router
              ├─(single)→ execute_agents → merge_results
              └─(multi) → execute_agents → merge_results
                                              ↓
                                       output_guardrail → save_memory → END

Checkpointer：MemorySaver（内存持久化）。
生产环境替换为 AsyncPostgresSaver（infra/ 就绪后切换）。
每个请求用独立 thread_id 隔离，支持并发。
"""
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver

from orchestrator.state import FamilyAgentState
from orchestrator.nodes.guardrails import input_guardrail, friendly_reject, output_guardrail
from orchestrator.nodes.memory import load_memory, save_memory
from orchestrator.nodes.intent import classify_intent
from orchestrator.nodes.router import route_to_agent, plan_subtasks
from orchestrator.nodes.agents import execute_agents, merge_results


def _after_guardrail(state: FamilyAgentState) -> str:
    return "load_memory" if state.get("guardrail_passed") else "friendly_reject"


def _after_classify(state: FamilyAgentState) -> str:
    return "plan_subtasks" if state.get("intent") == "multi" else "route_to_agent"


def build_graph() -> StateGraph:
    g = StateGraph(FamilyAgentState)

    # ── 注册节点 ──────────────────────────────────────────────────
    g.add_node("input_guardrail", input_guardrail)
    g.add_node("friendly_reject", friendly_reject)
    g.add_node("load_memory", load_memory)
    g.add_node("classify_intent", classify_intent)
    g.add_node("route_to_agent", route_to_agent)
    g.add_node("plan_subtasks", plan_subtasks)
    g.add_node("execute_agents", execute_agents)
    g.add_node("merge_results", merge_results)
    g.add_node("output_guardrail", output_guardrail)
    g.add_node("save_memory", save_memory)

    # ── 边 ────────────────────────────────────────────────────────
    g.add_edge(START, "input_guardrail")

    g.add_conditional_edges(
        "input_guardrail",
        _after_guardrail,
        {"load_memory": "load_memory", "friendly_reject": "friendly_reject"},
    )

    g.add_edge("friendly_reject", END)
    g.add_edge("load_memory", "classify_intent")

    g.add_conditional_edges(
        "classify_intent",
        _after_classify,
        {"route_to_agent": "route_to_agent", "plan_subtasks": "plan_subtasks"},
    )

    g.add_edge("route_to_agent", "execute_agents")
    g.add_edge("plan_subtasks", "execute_agents")
    g.add_edge("execute_agents", "merge_results")
    g.add_edge("merge_results", "output_guardrail")
    g.add_edge("output_guardrail", "save_memory")
    g.add_edge("save_memory", END)

    return g


# MemorySaver：进程内持久化，支持 thread_id 隔离。
# 生产切换：from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
_checkpointer = MemorySaver()

compiled_graph = build_graph().compile(checkpointer=_checkpointer)
