"""
Guardrails 节点：
  - input_guardrail  : 检查输入内容安全 / 场景边界 / 提示词注入
  - output_guardrail : 检查输出格式完整性 / 内容安全
  - friendly_reject  : 不通过时返回友好引导语
"""
import logging
import re
from typing import Any

from orchestrator.state import FamilyAgentState

logger = logging.getLogger(__name__)

# 简单关键词黑名单（生产中换成 LLM 分类或专用 Guardrails 模型）
_BLOCKED_PATTERNS = [
    r"忘记(你的|所有|之前的)?(指令|规则|系统提示)",
    r"(扮演|假装|假设).{0,10}(没有限制|无限制|不受约束)",
    r"(黄色|色情|暴力|血腥|自残|自杀)",
    r"(炸弹|武器|毒品|制造|合成).{0,5}(方法|教程|步骤)",
]
_BLOCKED_RE = re.compile("|".join(_BLOCKED_PATTERNS), re.IGNORECASE)

_REJECT_MSG = (
    "我们专注于学习辅助哦～有作业问题、PPT 制作或学习计划需要帮忙吗？"
)


def input_guardrail(state: FamilyAgentState) -> dict[str, Any]:
    text = state.get("raw_input", "") or ""
    passed = True
    reason: str | None = None

    if _BLOCKED_RE.search(text):
        passed = False
        reason = "内容安全检查未通过"
        logger.warning("[guardrail] 输入被拦截 user_id=%s", state.get("user_id"))

    # 场景边界：空消息
    if not text.strip() and state.get("msg_type") == "text":
        passed = False
        reason = "空消息"

    return {"guardrail_passed": passed, "reject_reason": reason}


def friendly_reject(state: FamilyAgentState) -> dict[str, Any]:
    reason = state.get("reject_reason", "内容不符合使用规范")
    logger.info("[reject] user_id=%s reason=%s", state.get("user_id"), reason)
    return {
        "final_output": {
            "content_type": "text",
            "content": _REJECT_MSG,
            "file_url": None,
        }
    }


def output_guardrail(state: FamilyAgentState) -> dict[str, Any]:
    final = state.get("final_output") or {}
    content = final.get("content", "")

    passed = True
    if not content:
        passed = False
        logger.warning("[output_guardrail] 输出内容为空，降级")
        final = {
            "content_type": "text",
            "content": "抱歉，处理结果暂时无法生成，请稍后重试。",
            "file_url": None,
        }

    return {"output_passed": passed, "final_output": final}
