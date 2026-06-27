"""
server.py — FastAPI HTTP 入口，监听端口 8081

接口契约 §1.3：
  POST /v1/message       立即返回 {"status": "accepted"}，异步执行编排流程
  POST /v1/message/sync  同步执行并返回结果（调试/测试用，非生产接口）
  GET  /health           健康检查
"""
import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

import uvicorn
from pydantic import BaseModel, Field

from orchestrator import config
from orchestrator.graph import compiled_graph
from orchestrator.mock_services import channel_reply

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ── 请求 / 响应模型（按接口契约 §1.3）───────────────────────────────

class InboundMessage(BaseModel):
    channel: str
    user_id: str
    msg_type: str = Field(default="text", pattern="^(text|image|file)$")
    content: str = ""
    media_url: str | None = None
    timestamp: int = Field(default_factory=lambda: int(time.time()))


class AcceptedResponse(BaseModel):
    status: str = "accepted"
    thread_id: str = ""


class SyncResponse(BaseModel):
    thread_id: str
    intent: str
    route: str
    final_output: dict


# ── 编排核心 ──────────────────────────────────────────────────────

def _make_initial_state(msg: InboundMessage) -> dict:
    return {
        "channel": msg.channel,
        "user_id": msg.user_id,
        "raw_input": msg.content,
        "msg_type": msg.msg_type,
        "media_url": msg.media_url,
        "timestamp": msg.timestamp,
    }


async def _run_orchestration(msg: InboundMessage, thread_id: str) -> None:
    """后台异步编排 + 回调渠道。"""
    config_dict = {"configurable": {"thread_id": thread_id}}
    try:
        final_state = await compiled_graph.ainvoke(
            _make_initial_state(msg), config=config_dict
        )
        output = final_state.get("final_output") or {
            "content_type": "text",
            "content": "处理完成。",
            "file_url": None,
        }
        await channel_reply(
            user_id=msg.user_id,
            content_type=output.get("content_type", "text"),
            content=output.get("content", ""),
            file_url=output.get("file_url"),
        )
    except Exception as exc:
        logger.exception("[server] 编排异常 user_id=%s thread=%s err=%s", msg.user_id, thread_id, exc)
        await channel_reply(
            user_id=msg.user_id,
            content_type="text",
            content="抱歉，系统暂时遇到问题，请稍后重试。",
        )


# ── FastAPI 应用 ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    logger.info("FamilyAgent 编排服务启动，端口 %d", config.ORCHESTRATOR_PORT)
    yield
    logger.info("FamilyAgent 编排服务关闭")


from fastapi import FastAPI

app = FastAPI(
    title="FamilyAgent Orchestrator",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/message", response_model=AcceptedResponse)
async def receive_message(msg: InboundMessage):
    """异步接口：立即返回 accepted，后台处理后回调渠道（生产用）。"""
    thread_id = f"{msg.user_id}:{uuid.uuid4().hex[:8]}"
    asyncio.create_task(_run_orchestration(msg, thread_id))
    return AcceptedResponse(thread_id=thread_id)


@app.post("/v1/message/sync", response_model=SyncResponse)
async def receive_message_sync(msg: InboundMessage):
    """同步接口：等待编排完成后返回结果（调试/测试用，不回调渠道）。"""
    thread_id = f"{msg.user_id}:{uuid.uuid4().hex[:8]}"
    config_dict = {"configurable": {"thread_id": thread_id}}
    final_state = await compiled_graph.ainvoke(
        _make_initial_state(msg), config=config_dict
    )
    return SyncResponse(
        thread_id=thread_id,
        intent=final_state.get("intent", "unknown"),
        route=final_state.get("route", ""),
        final_output=final_state.get("final_output") or {},
    )


if __name__ == "__main__":
    uvicorn.run(
        "orchestrator.server:app",
        host="0.0.0.0",
        port=config.ORCHESTRATOR_PORT,
        reload=False,
    )
