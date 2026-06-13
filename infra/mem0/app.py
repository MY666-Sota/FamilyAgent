"""
Mem0 记忆层包装服务

实现 INTERFACE_CONTRACT 接口一.2 约定的两个端点：
  GET  /v1/memory/{user_id}
  POST /v1/memory/{user_id}
"""
import os
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from mem0 import Memory

app = FastAPI(title="mem0-service", version="1.0.0")


def _pg_host() -> str:
    url = os.environ.get("POSTGRES_URL", "")
    # 从 postgresql://user:pass@host:port/db 提取 host
    if "@" in url:
        return url.split("@")[1].split(":")[0]
    return "postgres"


def _build_mem0_config() -> dict:
    return {
        "llm": {
            "provider": "openai",
            "config": {
                "model": os.environ.get("LLM_MODEL", "deepseek-chat"),
                "openai_base_url": os.environ.get("OPENAI_API_BASE", "https://api.deepseek.com/v1"),
                "api_key": os.environ["OPENAI_API_KEY"],
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": os.environ.get("EMBEDDING_MODEL", "qwen3-embedding"),
                "openai_base_url": os.environ.get("EMBEDDING_BASE_URL", "http://xinference:9997/v1"),
                "api_key": "xinference",  # xinference 不校验 key
            },
        },
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "dbname": os.environ.get("POSTGRES_DB", "familyagent"),
                "collection_name": "mem0_vectors",
                "embedding_model_dims": 1536,
                "host": _pg_host(),
                "port": 5432,
                "user": os.environ.get("POSTGRES_USER", "familyagent"),
                "password": os.environ.get("POSTGRES_PASSWORD", ""),
            },
        },
    }


# 延迟初始化，等 postgres 就绪
_memory: Memory | None = None


def get_memory() -> Memory:
    global _memory
    if _memory is None:
        _memory = Memory.from_config(_build_mem0_config())
    return _memory


# ── 请求 / 响应模型 ────────────────────────────────────────────────

class MemoryWriteRequest(BaseModel):
    type: str   # "mistake" | "profile" | "history"
    data: dict[str, Any]


class MemoryReadResponse(BaseModel):
    profile: dict[str, Any]
    mistakes: list[dict[str, Any]]
    history: list[dict[str, Any]]


# ── 端点 ───────────────────────────────────────────────────────────

@app.get("/v1/memory/{user_id}", response_model=MemoryReadResponse)
async def read_memory(user_id: str):
    mem = get_memory()
    try:
        results = mem.get_all(user_id=user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    profile: dict[str, Any] = {}
    mistakes: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []

    for item in results:
        meta = item.get("metadata", {})
        mem_type = meta.get("type", "history")
        payload = item.get("memory", item)
        if mem_type == "profile":
            profile.update(payload if isinstance(payload, dict) else {"raw": payload})
        elif mem_type == "mistake":
            mistakes.append(payload if isinstance(payload, dict) else {"raw": payload})
        else:
            history.append(payload if isinstance(payload, dict) else {"raw": payload})

    return MemoryReadResponse(profile=profile, mistakes=mistakes, history=history)


@app.post("/v1/memory/{user_id}", status_code=201)
async def write_memory(user_id: str, req: MemoryWriteRequest):
    if req.type not in ("mistake", "profile", "history"):
        raise HTTPException(status_code=400, detail="type must be mistake|profile|history")

    mem = get_memory()
    text = _dict_to_text(req.type, req.data)
    try:
        mem.add(text, user_id=user_id, metadata={"type": req.type, **req.data})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok"}


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


def _dict_to_text(mem_type: str, data: dict[str, Any]) -> str:
    """把结构化数据序列化成 Mem0 可提取摘要的自然语言文本。"""
    if mem_type == "profile":
        parts = [f"{k}: {v}" for k, v in data.items()]
        return "用户画像 — " + "，".join(parts)
    if mem_type == "mistake":
        subject = data.get("subject", "未知科目")
        point = data.get("knowledge_point", "")
        desc = data.get("description", "")
        return f"错题记录 — 科目：{subject}，知识点：{point}，描述：{desc}"
    # history
    action = data.get("action", "")
    detail = data.get("detail", "")
    return f"历史任务 — {action}：{detail}"
