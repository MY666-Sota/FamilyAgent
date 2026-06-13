"""
FamilyAgentState — 贯穿整个 LangGraph 流程的状态定义。
字段对齐 架构设计文档.md §3.2 与 INTERFACE_CONTRACT.md §3.1。
"""
from typing import Any, Optional
from typing_extensions import TypedDict


class FamilyAgentState(TypedDict, total=False):
    # ── 入口字段（由 /v1/message 注入）──────────────────────────────
    channel: str           # wecom / mp / web / miniapp
    user_id: str           # family_{姓名拼音}
    raw_input: str         # 原始文本内容
    msg_type: str          # text / image / file
    media_url: Optional[str]
    timestamp: int

    # ── 安全护栏 ─────────────────────────────────────────────────────
    guardrail_passed: bool
    reject_reason: Optional[str]

    # ── 记忆上下文（load_memory 填充）────────────────────────────────
    memory_context: dict[str, Any]   # {profile, mistakes, history}

    # ── 意图分类（classify_intent 填充）─────────────────────────────
    intent: str            # ppt / homework / document / study_plan / qa / multi / unknown
    params: dict[str, Any] # 从 raw_input 提取的任务参数

    # ── 路由与子任务（router / plan_subtasks 填充）───────────────────
    route: str             # single / multi
    subtasks: list[dict[str, Any]]

    # ── RAG 上下文（rag_fetch 填充，可选）────────────────────────────
    rag_context: str

    # ── Agent 执行结果 ───────────────────────────────────────────────
    agent_results: list[dict[str, Any]]

    # ── 人工审批 ─────────────────────────────────────────────────────
    need_approval: bool
    approval_granted: Optional[bool]

    # ── 输出护栏与最终输出 ──────────────────────────────────────────
    output_passed: bool
    final_output: dict[str, Any]   # {content_type, content, file_url}

    # ── 错误追踪 ─────────────────────────────────────────────────────
    error: Optional[str]
