"""
paddleocr-mcp — 端口 9003，SSE 传输
桥接本地 PaddleOCR-VL 服务（localhost:8868），暴露图片 OCR 工具。
支持从本地路径或 URL 读取图片。
"""
import os
import base64
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

OUTPUTS_DIR = Path(__file__).parent.parent.parent / "shared" / "outputs"
PADDLEOCR_BASE = os.getenv("PADDLEOCR_BASE", "http://localhost:8868")

mcp = FastMCP("paddleocr", port=9003)


@mcp.tool()
async def ocr_image(
    image_path: str | None = None,
    image_url: str | None = None,
    language: str = "ch",
    return_layout: bool = False,
) -> dict:
    """
    对图片进行 OCR 识别（支持手写体、印刷体、作业图片）。
    image_path 和 image_url 提供其中一个即可。

    Args:
        image_path:    本地文件路径，优先于 image_url
        image_url:     图片 HTTP URL
        language:      识别语言，ch（中文）/ en（英文）/ ch_en（中英混合）
        return_layout: 是否返回布局框（坐标+置信度）

    Returns:
        {
          "text": str,                        # 全文拼接
          "lines": [str],                     # 按行分割的文本
          "layout": [{"text": str, "box": [...], "score": float}]  # 仅 return_layout=True 时有值
        }
    """
    if image_path:
        path = Path(image_path)
        if not path.exists():
            # 在 shared/outputs/ 下查找
            path = OUTPUTS_DIR / image_path
        if not path.exists():
            raise FileNotFoundError(f"图片文件不存在: {image_path}")
        image_b64 = base64.b64encode(path.read_bytes()).decode()
        payload = {"image": image_b64, "language": language}
    elif image_url:
        payload = {"url": image_url, "language": language}
    else:
        raise ValueError("必须提供 image_path 或 image_url 之一")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{PADDLEOCR_BASE}/ocr", json=payload)
        resp.raise_for_status()
        data = resp.json()

    # PaddleOCR-VL 返回格式：{"result": [[box, (text, score)], ...]}
    raw = data.get("result", [])
    layout = []
    lines = []
    for item in raw:
        if isinstance(item, list) and len(item) == 2:
            box, (text, score) = item[0], item[1]
            lines.append(text)
            if return_layout:
                layout.append({"text": text, "box": box, "score": round(score, 4)})
        elif isinstance(item, str):
            lines.append(item)

    result = {"text": "\n".join(lines), "lines": lines}
    if return_layout:
        result["layout"] = layout
    return result


@mcp.tool()
async def ocr_image_structured(
    image_path: str | None = None,
    image_url: str | None = None,
    subject: str = "math",
) -> dict:
    """
    针对作业图片做结构化 OCR，识别题目、解答过程和答案。

    Args:
        image_path: 本地文件路径
        image_url:  图片 HTTP URL
        subject:    科目 math / chinese / english（影响后处理逻辑）

    Returns:
        {
          "raw_text": str,
          "questions": [{"number": str, "content": str, "answer": str}]
        }
    """
    ocr_result = await ocr_image(
        image_path=image_path,
        image_url=image_url,
        language="ch_en" if subject == "english" else "ch",
        return_layout=False,
    )
    raw_text = ocr_result["text"]

    # 简单后处理：按题号切分（1. 2. 一、二、等常见格式）
    import re
    question_pattern = re.compile(
        r"(?:^|\n)(\d+[\.、。]|[一二三四五六七八九十]+[\.、。])\s*(.+?)(?=\n\d+[\.、。]|\n[一二三四五六七八九十]+[\.、。]|$)",
        re.DOTALL,
    )
    questions = []
    for m in question_pattern.finditer(raw_text):
        num = m.group(1).strip()
        body = m.group(2).strip()
        # 粗略把最后一行当作答案
        body_lines = [l.strip() for l in body.splitlines() if l.strip()]
        answer = body_lines[-1] if len(body_lines) > 1 else ""
        content = "\n".join(body_lines[:-1]) if len(body_lines) > 1 else body
        questions.append({"number": num, "content": content, "answer": answer})

    return {"raw_text": raw_text, "questions": questions}


if __name__ == "__main__":
    mcp.run(transport="sse")
