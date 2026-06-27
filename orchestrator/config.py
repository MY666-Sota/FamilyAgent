"""
config.py — 集中读取环境变量，供所有模块使用。
优先读取 .env 文件（python-dotenv），未设置时使用合理默认值。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 显式指向 orchestrator/.env，避免受当前工作目录影响（从仓库根或子目录运行均可）
load_dotenv(Path(__file__).resolve().parent / ".env")


def _bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


# ── LLM ──────────────────────────────────────────────────────────────
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-chat")

# ── 服务端口 / 地址 ──────────────────────────────────────────────────
ORCHESTRATOR_PORT: int = int(os.getenv("ORCHESTRATOR_PORT", "8081"))

MEM0_BASE_URL: str = os.getenv("MEM0_BASE_URL", "http://localhost:8082")
RAG_BASE_URL: str = os.getenv("RAG_BASE_URL", "http://localhost:5001")
CHANNEL_BASE_URL: str = os.getenv("CHANNEL_BASE_URL", "http://localhost:8080")

# ── MCP Servers（窗口3 提供）──────────────────────────────────────────
# 格式：MCP_SERVER_<NAME>_URL=http://localhost:PORT/sse
MCP_SERVERS = {
    "office-word": os.getenv("MCP_SERVER_OFFICE_WORD_URL", "http://localhost:9001/sse"),
    "presenton":   os.getenv("MCP_SERVER_PRESENTON_URL", "http://localhost:9002/sse"),
    "paddleocr":   os.getenv("MCP_SERVER_PADDLEOCR_URL", "http://localhost:9003/sse"),
    "filesystem":  os.getenv("MCP_SERVER_FILESYSTEM_URL", None),
}

# ── Mock 开关（设为 "true" 使用真实服务）────────────────────────────
USE_REAL_MEM0: bool = _bool("USE_REAL_MEM0")
USE_REAL_RAG: bool = _bool("USE_REAL_RAG")
USE_REAL_CHANNEL: bool = _bool("USE_REAL_CHANNEL")
USE_REAL_MCP: bool = _bool("USE_REAL_MCP")