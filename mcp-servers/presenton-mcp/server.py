"""
presenton-mcp — 端口 9002，SSE 传输
自研封装：调用 Presenton HTTP API 生成 PPT，输出落 shared/outputs/。
"""
import os
import shutil
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

OUTPUTS_DIR = Path(__file__).parent.parent.parent / "shared" / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

FILE_SERVER_BASE = os.getenv("FILE_SERVER_BASE", "http://localhost:8090/files")
PRESENTON_BASE = os.getenv("PRESENTON_BASE", "http://localhost:7001")

mcp = FastMCP("presenton", port=9002)


def _file_url(filename: str) -> str:
    return f"{FILE_SERVER_BASE}/{filename}"


@mcp.tool()
async def generate_ppt(
    filename: str,
    topic: str,
    outline: list[str],
    style: str = "professional",
    language: str = "zh",
) -> dict:
    """
    根据主题和大纲生成 PPT 文件（.pptx）。

    Args:
        filename: 输出文件名，例如 math_review.pptx
        topic:    PPT 主题，例如 "小学数学分数专项复习"
        outline:  幻灯片大纲，每项对应一页标题+要点，例如
                  ["第一页: 分数概念\\n- 什么是分数\\n- 分子分母", ...]
        style:    风格，可选 professional / educational / minimal（默认 professional）
        language: 语言，zh 或 en（默认 zh）

    Returns:
        {"file_url": str, "filename": str, "slide_count": int}
    """
    if not filename.endswith(".pptx"):
        filename += ".pptx"

    payload = {
        "topic": topic,
        "outline": outline,
        "style": style,
        "language": language,
        "output_filename": filename,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{PRESENTON_BASE}/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()

    src = data.get("file_path")
    if src and os.path.exists(src):
        dest = OUTPUTS_DIR / filename
        shutil.copy2(src, dest)
    else:
        # Presenton 直接返回二进制时
        content_bytes = resp.content
        if content_bytes:
            (OUTPUTS_DIR / filename).write_bytes(content_bytes)

    return {
        "file_url": _file_url(filename),
        "filename": filename,
        "slide_count": data.get("slide_count", len(outline)),
    }


@mcp.tool()
async def generate_ppt_from_markdown(
    filename: str,
    markdown: str,
    style: str = "educational",
) -> dict:
    """
    把 Markdown 文档转换为 PPT（每个 ## 标题变一页）。

    Args:
        filename: 输出文件名，例如 lesson.pptx
        markdown: Markdown 文本，用 ## 分隔幻灯片
        style:    风格，professional / educational / minimal

    Returns:
        {"file_url": str, "filename": str, "slide_count": int}
    """
    if not filename.endswith(".pptx"):
        filename += ".pptx"

    payload = {"markdown": markdown, "style": style, "output_filename": filename}

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{PRESENTON_BASE}/api/generate/markdown", json=payload)
        resp.raise_for_status()
        data = resp.json()

    src = data.get("file_path")
    if src and os.path.exists(src):
        shutil.copy2(src, OUTPUTS_DIR / filename)
    else:
        content_bytes = resp.content
        if content_bytes:
            (OUTPUTS_DIR / filename).write_bytes(content_bytes)

    slide_count = markdown.count("\n## ") + (1 if markdown.startswith("## ") else 0)
    return {
        "file_url": _file_url(filename),
        "filename": filename,
        "slide_count": data.get("slide_count", slide_count),
    }


@mcp.tool()
async def list_ppts() -> dict:
    """
    列出 shared/outputs/ 中所有 .pptx 文件。

    Returns:
        {"files": [{"filename": str, "file_url": str}]}
    """
    files = [
        {"filename": f.name, "file_url": _file_url(f.name)}
        for f in OUTPUTS_DIR.glob("*.pptx")
    ]
    return {"files": files}


if __name__ == "__main__":
    mcp.run(transport="sse")
