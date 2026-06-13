"""
Intent 节点：classify_intent
用 LLM（DeepSeek / Claude）对用户输入做意图分类。
环境变量未设置时降级为关键词规则，保证骨架可跑通。
"""
import json
import logging
import os
import re
from typing import Any

from orchestrator.state import FamilyAgentState

logger = logging.getLogger(__name__)

# 支持的意图标签
INTENTS = ("ppt", "homework", "document", "study_plan", "qa", "multi", "unknown")

# ── 关键词降级规则（LLM 不可用时兜底）────────────────────────────────
_KEYWORD_RULES: list[tuple[str, str]] = [
    (r"(ppt|幻灯片|演示文稿|slides)", "ppt"),
    (r"(作业|批改|错题|解题|题目)", "homework"),
    (r"(文档|word|报告|写作|撰写)", "document"),
    (r"(学习计划|复习计划|课程安排|时间表)", "study_plan"),
    (r"(问|查|知识|什么是|怎么|为什么|百科)", "qa"),
]


def _keyword_classify(text: str) -> str:
    t = text.lower()
    matches = [intent for pattern, intent in _KEYWORD_RULES if re.search(pattern, t)]
    if len(matches) > 1:
        return "multi"
    return matches[0] if matches else "unknown"


_SYSTEM_PROMPT = """\
你是家庭AI助手的意图分类器。
根据用户消息，从以下标签中选择一个最合适的意图，并提取关键参数。

意图标签：
- ppt        : 制作或修改 PPT / 演示文稿
- homework   : 作业批改、错题分析、解题辅导
- document   : 文档写作、报告生成、Word 文件
- study_plan : 制定学习计划、复习安排
- qa         : 知识问答、百科查询
- multi      : 包含多个不同类型的复杂任务（如"分析错题并做PPT"）
- unknown    : 无法归类

只返回 JSON，格式：
{"intent": "<标签>", "params": {"topic": "...", "subject": "...", ...}}
不要输出任何其他内容。"""


async def classify_intent(state: FamilyAgentState) -> dict[str, Any]:
    text = state.get("raw_input", "")
    memory = state.get("memory_context", {})

    llm_api_key = os.getenv("LLM_API_KEY", "")
    if llm_api_key:
        result = await _llm_classify(text, memory, llm_api_key)
    else:
        logger.warning("[intent] LLM_API_KEY 未设置，使用关键词降级分类")
        result = {"intent": _keyword_classify(text), "params": {}}

    logger.info("[intent] user_id=%s intent=%s", state.get("user_id"), result["intent"])
    return result


async def _llm_classify(
    text: str, memory: dict, api_key: str
) -> dict[str, Any]:
    try:
        # 按架构文档：对话模型首选 DeepSeek V3
        base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        model = os.getenv("LLM_MODEL", "deepseek-chat")

        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        profile = memory.get("profile", {})
        user_context = f"用户画像：{json.dumps(profile, ensure_ascii=False)}" if profile else ""

        llm = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0,
            max_tokens=256,
        )
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=f"{user_context}\n用户消息：{text}"),
        ]
        resp = await llm.ainvoke(messages)
        raw = resp.content.strip()
        # 去掉可能的 markdown 代码块
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
        parsed = json.loads(raw)
        intent = parsed.get("intent", "unknown")
        if intent not in INTENTS:
            intent = "unknown"
        return {"intent": intent, "params": parsed.get("params", {})}
    except Exception as exc:
        logger.error("[intent] LLM 分类失败，降级关键词: %s", exc)
        return {"intent": _keyword_classify(text), "params": {}}
