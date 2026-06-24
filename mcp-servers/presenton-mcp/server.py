"""
presenton-mcp — 端口 9002，SSE 传输
自研封装：调用 Presenton HTTP API 生成 PPT，输出落 shared/outputs/。

上游真实 API（2026-06-19 实测 ghcr.nju.edu.cn/presenton/presenton:latest）：
  POST {PRESENTON_BASE}/api/v1/ppt/presentation/generate
    请求体（GeneratePresentationRequest）关键字段：
      content: str        必填，PPT 内容/主题描述
      n_slides: int?      幻灯片数（省略则模型自动判断）
      language: str?      语言名，如 "Chinese" / "English"
      template: str       模板，默认 "general"
      export_as: "pptx"   导出格式
      instructions: str?  额外生成指令
    响应（PresentationPathAndEditPath）：
      {"presentation_id": "...", "path": "/app_data/.../xxx.pptx", "edit_path": "..."}
    生成的文件通过 {PRESENTON_BASE}{path} 静态下载（需容器 DISABLE_AUTH=true）。

注意：工具签名（filename/topic/outline/style/language）保持不变，是 shared/tool_schemas/
      presenton.json 的契约，窗口1 据此调用。真实 API 的字段映射在本文件内部完成。
"""
import os
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

OUTPUTS_DIR = Path(__file__).parent.parent.parent / "shared" / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

FILE_SERVER_BASE = os.getenv("FILE_SERVER_BASE", "http://localhost:8090/files")
# Presenton 容器地址（docker run -p 7860:80，容器内端口 80）
PRESENTON_BASE = os.getenv("PRESENTON_BASE", "http://localhost:7860")
# 真实生成端点（同步）。可用环境变量覆盖以适配版本变化。
PRESENTON_GENERATE_PATH = os.getenv(
    "PRESENTON_GENERATE_PATH", "/api/v1/ppt/presentation/generate"
)
PRESENTON_TEMPLATE = os.getenv("PRESENTON_TEMPLATE", "general")

mcp = FastMCP("presenton", port=9002)

# 语言代码 → Presenton 语言名
_LANG_MAP = {"zh": "Chinese", "en": "English"}


def _file_url(filename: str) -> str:
    return f"{FILE_SERVER_BASE}/{filename}"


async def _generate_and_save(
    *,
    filename: str,
    content: str,
    n_slides: int | None,
    language: str,
    instructions: str | None,
) -> int:
    """
    调真实 Presenton API 生成 PPT，从响应 path 下载并落 shared/outputs/{filename}。
    返回生成的幻灯片数（取响应或回退到 n_slides）。失败时抛异常，由 FastMCP 包装为 isError。
    """
    payload: dict = {
        "content": content,
        "language": _LANG_MAP.get(language, language or "Chinese"),
        "template": PRESENTON_TEMPLATE,
        "export_as": "pptx",
    }
    if n_slides:
        payload["n_slides"] = n_slides
    if instructions:
        payload["instructions"] = instructions

    # trust_env=False：本地容器调用不走系统代理
    async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
        resp = await client.post(f"{PRESENTON_BASE}{PRESENTON_GENERATE_PATH}", json=payload)
        resp.raise_for_status()
        data = resp.json()

        # 真实响应：{"presentation_id", "path": "/app_data/.../xxx.pptx", "edit_path"}
        path = data.get("path")
        if not path:
            raise RuntimeError(f"Presenton 响应缺少 path 字段: {data}")

        # 从静态服务下载生成的 pptx
        dl_url = path if path.startswith("http") else f"{PRESENTON_BASE}{path}"
        dl = await client.get(dl_url)
        dl.raise_for_status()
        (OUTPUTS_DIR / filename).write_bytes(dl.content)

    return data.get("n_slides") or n_slides or 0


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

    # 把 topic + outline 合成 content（真实 API 用单一 content 字段驱动生成）
    content = topic
    if outline:
        content += "\n\n" + "\n".join(outline)

    slide_count = await _generate_and_save(
        filename=filename,
        content=content,
        n_slides=len(outline) if outline else None,
        language=language,
        instructions=f"风格: {style}" if style else None,
    )

    return {
        "file_url": _file_url(filename),
        "filename": filename,
        "slide_count": slide_count or len(outline),
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

    md_slides = markdown.count("\n## ") + (1 if markdown.startswith("## ") else 0)

    slide_count = await _generate_and_save(
        filename=filename,
        content=markdown,
        n_slides=md_slides or None,
        language="zh",
        instructions=f"按 Markdown 的 ## 标题分页。风格: {style}" if style else None,
    )

    return {
        "file_url": _file_url(filename),
        "filename": filename,
        "slide_count": slide_count or md_slides,
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