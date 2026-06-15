"""
office-word-mcp — 端口 9001，SSE 传输
代理 GongRzhe/Office-Word-MCP-Server，暴露 Word 文档操作工具。
文件输出落 shared/outputs/，URL 通过 file-server (8090) 访问。
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

OUTPUTS_DIR = Path(__file__).parent.parent.parent / "shared" / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

FILE_SERVER_BASE = os.getenv("FILE_SERVER_BASE", "http://localhost:8090/files")
# Office-Word-MCP-Server 自身地址（由 infra 启动，此处转发）
WORD_MCP_BASE = os.getenv("OFFICE_WORD_MCP_BASE", "http://localhost:9011")

mcp = FastMCP("office-word", port=9001)


def _file_url(filename: str) -> str:
    return f"{FILE_SERVER_BASE}/{filename}"


@mcp.tool()
async def create_document(
    filename: str,
    content: str,
    title: str = "",
    author: str = "FamilyAgent",
) -> dict:
    """
    创建 Word 文档（.docx）并保存到 shared/outputs/。

    Args:
        filename: 输出文件名，例如 report.docx
        content:  Markdown 或纯文本正文
        title:    文档标题（可选）
        author:   作者名（可选）

    Returns:
        {"file_url": str, "filename": str}
    """
    if not filename.endswith(".docx"):
        filename += ".docx"

    # trust_env=False：本地服务间调用不走系统代理，避免 localhost 被代理拦截
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        resp = await client.post(
            f"{WORD_MCP_BASE}/create",
            json={"filename": filename, "content": content, "title": title, "author": author},
        )
        resp.raise_for_status()
        data = resp.json()

    # 上游服务把文件写到它自己的输出目录，需要复制到 shared/outputs/
    src = data.get("file_path")
    if src and os.path.exists(src):
        dest = OUTPUTS_DIR / filename
        shutil.copy2(src, dest)

    return {"file_url": _file_url(filename), "filename": filename}


@mcp.tool()
async def read_document(filename: str) -> dict:
    """
    读取 shared/outputs/ 中的 Word 文档，返回纯文本内容。

    Args:
        filename: 文件名，例如 report.docx

    Returns:
        {"content": str, "filename": str}
    """
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        resp = await client.post(
            f"{WORD_MCP_BASE}/read",
            json={"filename": filename},
        )
        resp.raise_for_status()
        data = resp.json()
    return {"content": data.get("content", ""), "filename": filename}


@mcp.tool()
async def list_documents() -> dict:
    """
    列出 shared/outputs/ 中所有 .docx 文件。

    Returns:
        {"files": [{"filename": str, "file_url": str}]}
    """
    files = [
        {"filename": f.name, "file_url": _file_url(f.name)}
        for f in OUTPUTS_DIR.glob("*.docx")
    ]
    return {"files": files}


@mcp.tool()
async def append_to_document(filename: str, content: str) -> dict:
    """
    向已有 Word 文档追加内容。

    Args:
        filename: 目标文件名
        content:  要追加的 Markdown 或纯文本

    Returns:
        {"file_url": str, "filename": str}
    """
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        resp = await client.post(
            f"{WORD_MCP_BASE}/append",
            json={"filename": filename, "content": content},
        )
        resp.raise_for_status()

    return {"file_url": _file_url(filename), "filename": filename}


if __name__ == "__main__":
    mcp.run(transport="sse")
