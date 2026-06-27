"""
Agent 调度节点：execute_agents / merge_results

各 Agent 通过 MCP 工具 + LLM 完成具体任务。
工具名/参数以 shared/tool_schemas/ 真实 schema 为准（A8 改造）：
  - presenton  9002: generate_ppt(filename*, topic*, outline[]*)
  - office-word 9001: create_document(filename*, content*, title?)
  - paddleocr  9003: ocr_image_structured(image_url, subject?)
LLM_API_KEY 未配时用规则降级，保证 mock 模式可独立跑通。
"""
import json
import logging
import os
import re
import uuid
from typing import Any

from orchestrator.mcp_client import call_tool
from orchestrator.mock_services import rag_query
from orchestrator.state import FamilyAgentState

logger = logging.getLogger(__name__)


# ── LLM 工具函数 ──────────────────────────────────────────────────────

def _make_llm(max_tokens: int = 1024):
    """构造 ChatOpenAI 实例；调用方自行判断 LLM_API_KEY 是否可用。"""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        temperature=0.3,
        max_tokens=max_tokens,
    )


def _llm_available() -> bool:
    return bool(os.getenv("LLM_API_KEY", ""))


def _safe_filename(topic: str, ext: str) -> str:
    """从主题生成安全文件名（去非字母数字汉字字符）。"""
    clean = re.sub(r'[^\w一-鿿]+', '_', topic.strip())[:40]
    uid = uuid.uuid4().hex[:6]
    return f"{clean}_{uid}.{ext}"


# ── PPT Agent ─────────────────────────────────────────────────────────

_PPT_SYSTEM = """\
你是一位专业的 PPT 策划师。根据主题生成演示文稿大纲。
只返回 JSON，不要有任何其他内容：
{"filename": "<文件名.pptx>", "outline": ["第一章标题", "第二章标题", ...]}
要求：filename 只含中英文和下划线，outline 为 3-6 个章节标题的字符串数组。"""


async def _ppt_agent(task: dict, state: FamilyAgentState) -> dict[str, Any]:
    topic = task.get("params", {}).get("topic") or state.get("raw_input", "")

    if _llm_available():
        filename, outline = await _llm_ppt_outline(topic)
    else:
        filename = _safe_filename(topic, "pptx")
        outline = [f"{topic} 简介", "核心内容", "总结与展望"]

    result = await call_tool(
        "presenton",
        "generate_ppt",
        {"filename": filename, "topic": topic, "outline": outline},
    )
    return {
        "agent": "ppt_agent",
        "content_type": "file",
        "content": f"PPT 已生成：{topic}",
        "file_url": result.get("file_url"),
        "raw": result,
    }


async def _llm_ppt_outline(topic: str) -> tuple[str, list[str]]:
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = _make_llm(512)
        resp = await llm.ainvoke([
            SystemMessage(content=_PPT_SYSTEM),
            HumanMessage(content=f"主题：{topic}"),
        ])
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.content.strip(), flags=re.DOTALL).strip()
        parsed = json.loads(raw)
        filename = parsed.get("filename") or _safe_filename(topic, "pptx")
        outline = parsed.get("outline") or []
        if not isinstance(outline, list) or not outline:
            outline = [f"{topic} 简介", "核心内容", "总结与展望"]
        return filename, outline
    except Exception as exc:
        logger.warning("[ppt_agent] LLM 生成大纲失败，用规则降级: %s", exc)
        return _safe_filename(topic, "pptx"), [f"{topic} 简介", "核心内容", "总结与展望"]


# ── Document Agent ────────────────────────────────────────────────────

_DOC_SYSTEM = """\
你是一位专业文档写作助手。根据主题生成 Word 文档内容。
只返回 JSON，不要有任何其他内容：
{"filename": "<文件名.docx>", "title": "<文档标题>", "content": "<正文内容，500字左右>"}
要求：filename 只含中英文和下划线，content 为可直接放入文档的正文段落（纯文字，无 markdown）。"""


async def _document_agent(task: dict, state: FamilyAgentState) -> dict[str, Any]:
    topic = task.get("params", {}).get("topic") or state.get("raw_input", "")

    if _llm_available():
        filename, title, content = await _llm_doc_content(topic)
    else:
        filename = _safe_filename(topic, "docx")
        title = topic
        content = f"关于「{topic}」的文档内容（LLM_API_KEY 未配置，此为占位文本）。"

    result = await call_tool(
        "office-word",
        "create_document",
        {"filename": filename, "content": content, "title": title},
    )
    return {
        "agent": "document_agent",
        "content_type": "file",
        "content": f"文档已生成：{title}",
        "file_url": result.get("file_url"),
        "raw": result,
    }


async def _llm_doc_content(topic: str) -> tuple[str, str, str]:
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = _make_llm(1024)
        resp = await llm.ainvoke([
            SystemMessage(content=_DOC_SYSTEM),
            HumanMessage(content=f"主题：{topic}"),
        ])
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.content.strip(), flags=re.DOTALL).strip()
        parsed = json.loads(raw)
        filename = parsed.get("filename") or _safe_filename(topic, "docx")
        title = parsed.get("title") or topic
        content = parsed.get("content") or f"关于「{topic}」的文档内容。"
        return filename, title, content
    except Exception as exc:
        logger.warning("[document_agent] LLM 生成正文失败，用规则降级: %s", exc)
        return _safe_filename(topic, "docx"), topic, f"关于「{topic}」的文档内容。"


# ── Homework Agent ────────────────────────────────────────────────────

_GRADE_SYSTEM = """\
你是一位专业批改老师。根据 OCR 识别的作业文字，判断对错并给出批改意见。
只返回 JSON，不要有任何其他内容：
{
  "total": <题目总数>,
  "correct": <正确题数>,
  "mistakes": [{"question": "...", "wrong_answer": "...", "correct_answer": "...", "explanation": "..."}],
  "summary": "<整体评语>"
}"""


async def _homework_agent(task: dict, state: FamilyAgentState) -> dict[str, Any]:
    media_url = state.get("media_url")
    profile = state.get("memory_context", {}).get("profile", {})
    grade = profile.get("grade", "")

    # 科目映射：从 grade/raw_input 推断
    raw = state.get("raw_input", "")
    subject = _infer_subject(raw, grade)

    # Step 1: OCR 识别结构化文字
    ocr_args = {"image_url": media_url} if media_url else {}
    if subject:
        ocr_args["subject"] = subject

    ocr_result = await call_tool("paddleocr", "ocr_image_structured", ocr_args)
    ocr_text = ocr_result.get("result", "")

    # Step 2: LLM 批改
    if _llm_available() and ocr_text and ocr_result.get("status") not in ("mock_ok", "error"):
        grade_result = await _llm_grade(ocr_text, subject)
    else:
        # mock/LLM 不可用时返回占位结果（ocr_text 可能是 mock 文本）
        grade_result = {
            "total": 0,
            "correct": 0,
            "mistakes": [],
            "summary": f"[mock] 作业批改完成（OCR: {ocr_text[:60]}）",
        }

    mistakes = grade_result.get("mistakes", [])
    summary = grade_result.get("summary", "批改完成")
    return {
        "agent": "homework_agent",
        "content_type": "text",
        "content": summary,
        "file_url": None,
        "mistakes": mistakes,
        "raw": grade_result,
    }


def _infer_subject(raw: str, grade: str) -> str:
    """从用户输入推断学科，用于 ocr_image_structured subject 参数。"""
    mapping = [
        (r"(数学|算术|方程|几何|分数)", "math"),
        (r"(语文|作文|古诗|阅读|汉字)", "chinese"),
        (r"(英语|english|单词|语法)", "english"),
        (r"(物理|力学|电路)", "physics"),
        (r"(化学|元素|分子)", "chemistry"),
    ]
    text = (raw + grade).lower()
    for pattern, subj in mapping:
        if re.search(pattern, text):
            return subj
    return "math"  # 默认数学


async def _llm_grade(ocr_text: str, subject: str) -> dict[str, Any]:
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = _make_llm(1024)
        resp = await llm.ainvoke([
            SystemMessage(content=_GRADE_SYSTEM),
            HumanMessage(content=f"学科：{subject}\n作业内容（OCR）：\n{ocr_text[:2000]}"),
        ])
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.content.strip(), flags=re.DOTALL).strip()
        return json.loads(raw)
    except Exception as exc:
        logger.warning("[homework_agent] LLM 批改失败，用规则降级: %s", exc)
        return {"total": 0, "correct": 0, "mistakes": [], "summary": f"批改失败（{exc}），请重试。"}


# ── Study Plan Agent ──────────────────────────────────────────────────

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


# ── QA Agent ──────────────────────────────────────────────────────────

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


# ── 调度表 ────────────────────────────────────────────────────────────

_AGENT_HANDLERS = {
    "ppt_agent": _ppt_agent,
    "homework_agent": _homework_agent,
    "document_agent": _document_agent,
    "study_plan_agent": _study_plan_agent,
    "qa_agent": _qa_agent,
}


# ── 节点函数 ──────────────────────────────────────────────────────────

async def execute_agents(state: FamilyAgentState) -> dict[str, Any]:
    """按 subtasks 列表串行执行 Agent，前序结果可注入后序参数。"""
    subtasks = state.get("subtasks") or []
    results: list[dict[str, Any]] = []
    prev_result: dict[str, Any] | None = None

    for task in subtasks:
        agent_name = task.get("agent", "qa_agent")
        handler = _AGENT_HANDLERS.get(agent_name, _qa_agent)

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
    """合并多 Agent 结果：有文件输出优先返回文件，否则拼接文本。"""
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

    combined = "\n\n".join(r.get("content", "") for r in results if r.get("content"))
    return {
        "final_output": {
            "content_type": "text",
            "content": combined or "处理完成。",
            "file_url": None,
        },
        "need_approval": False,
    }
