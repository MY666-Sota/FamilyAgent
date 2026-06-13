"""
orchestrator_forwarder — chatgpt-on-wechat 插件

拦截所有进入的消息，转发到 LangGraph 编排核心（:8081/v1/message），
立即返回"处理中"占位回复。编排核心处理完后通过 POST :8080/v1/reply 推回结果。
"""
import os
import threading
import httpx
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage
from plugins import Plugin, Event, EventContext, EventAction, register

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://host.docker.internal:8081")


@register(
    name="orchestrator_forwarder",
    desc="Forward all messages to LangGraph orchestrator",
    version="1.0",
    author="FamilyAgent",
)
class OrchestratorForwarder(Plugin):
    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context

    def on_handle_context(self, e_context: EventContext):
        ctx = e_context["context"]

        if ctx.type not in (ContextType.TEXT, ContextType.IMAGE, ContextType.FILE):
            return

        msg: ChatMessage = ctx["msg"]
        user_id = f"family_{msg.from_user_id}"
        content = ctx.content or ""

        msg_type = "text"
        media_url = None
        if ctx.type == ContextType.IMAGE:
            msg_type = "image"
            media_url = content
            content = ""
        elif ctx.type == ContextType.FILE:
            msg_type = "file"
            media_url = content
            content = ""

        payload = {
            "channel": "wework",
            "user_id": user_id,
            "msg_type": msg_type,
            "content": content,
            "media_url": media_url,
        }

        # 异步发给编排层，不阻塞当前线程
        threading.Thread(
            target=_post_to_orchestrator,
            args=(payload,),
            daemon=True,
        ).start()

        # 立即返回占位回复，真实结果通过 /v1/reply 推回
        reply = Reply(ReplyType.TEXT, "⏳ 正在处理，请稍候…")
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS


def _post_to_orchestrator(payload: dict):
    url = f"{ORCHESTRATOR_URL}/v1/message"
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(url, json=payload)
    except Exception:
        pass  # 编排层重试/降级由编排层自己处理
