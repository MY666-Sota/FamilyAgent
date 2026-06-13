"""
server.py — FastAPI HTTP 入口，监听端口 8081

接口契约 §1.3：
  POST /v1/message  立即返回 {"status": "accepted"}，异步执行编排流程
  GET  /health      健康检查
"""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from orchestrator.graph import compiled_graph
from orchestrator.mock_services import channel_reply

load_dotenv()

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


# ── 编排任务（后台异步）──────────────────────────────────────────────

async def _run_orchestration(msg: InboundMessage) -> None:
    initial_state = {
        "channel": msg.channel,
        "user_id": msg.user_id,
        "raw_input": msg.content,
        "msg_type": msg.msg_type,
        "media_url": msg.media_url,
        "timestamp": msg.timestamp,
    }
    try:
        final_state = await compiled_graph.ainvoke(initial_state)
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
        logger.exception("[server] 编排异常 user_id=%s err=%s", msg.user_id, exc)
        await channel_reply(
            user_id=msg.user_id,
            content_type="text",
            content="抱歉，系统暂时遇到问题，请稍后重试。",
        )


# ── FastAPI 应用 ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FamilyAgent 编排服务启动，端口 8081")
    yield
    logger.info("FamilyAgent 编排服务关闭")


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
    # 立即返回，异步处理（接口契约要求）
    asyncio.create_task(_run_orchestration(msg))
    return AcceptedResponse()


if __name__ == "__main__":
    port = int(os.getenv("ORCHESTRATOR_PORT", "8081"))
    uvicorn.run("orchestrator.server:app", host="0.0.0.0", port=port, reload=False)
