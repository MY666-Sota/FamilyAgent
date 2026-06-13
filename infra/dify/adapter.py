"""
Dify 知识库接口适配器

把 INTERFACE_CONTRACT 约定的 POST /v1/rag/query 转换为 Dify 的
POST /v1/datasets/{dataset_id}/retrieve API，屏蔽两者签名差异。
"""
import os
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="dify-adapter", version="1.0.0")

DIFY_API_URL = os.environ["DIFY_API_URL"].rstrip("/")
DIFY_API_KEY = os.environ["DIFY_API_KEY"]
DIFY_DATASET_ID = os.environ["DIFY_DATASET_ID"]

_client = httpx.AsyncClient(timeout=30.0)


class QueryRequest(BaseModel):
    user_id: str
    query: str
    mode: str = "simple"   # "simple" | "agentic"
    top_k: int = 5


class Source(BaseModel):
    title: str
    score: float


class QueryResponse(BaseModel):
    context: str
    sources: list[Source]


@app.post("/v1/rag/query", response_model=QueryResponse)
async def rag_query(req: QueryRequest):
    payload = {
        "query": req.query,
        "retrieval_model": {
            "search_method": "hybrid_search",
            "reranking_enable": True,
            "reranking_model": {
                "reranking_provider_name": "xinference",
                "reranking_model_name": "qwen3-reranker",
            },
            "top_k": req.top_k,
            "score_threshold_enabled": False,
        },
    }

    url = f"{DIFY_API_URL}/v1/datasets/{DIFY_DATASET_ID}/retrieve"
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }

    resp = await _client.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Dify error: {resp.text}")

    data = resp.json()
    records = data.get("records", [])

    context_parts = []
    sources = []
    for r in records:
        segment = r.get("segment", {})
        content = segment.get("content", "")
        doc_name = segment.get("document", {}).get("name", "")
        score = r.get("score", 0.0)
        if content:
            context_parts.append(content)
        sources.append(Source(title=doc_name, score=score))

    return QueryResponse(
        context="\n\n".join(context_parts),
        sources=sources,
    )


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
