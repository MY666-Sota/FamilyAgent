"""
filesystem-mcp — stdio 传输
封装 mark3labs/mcp-filesystem-server，限定根路径为 shared/outputs/。
此文件作为启动入口，同时也可独立作为 MCP server（stdio）。
"""
import os
import sys
import json
from pathlib import Path

# 根路径严格限定为 shared/outputs/
ALLOWED_ROOT = Path(__file__).parent.parent.parent / "shared" / "outputs"
ALLOWED_ROOT.mkdir(parents=True, exist_ok=True)

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("filesystem")


def _safe_path(relative_path: str) -> Path:
    """解析路径并验证在 ALLOWED_ROOT 内，防目录穿越。"""
    target = (ALLOWED_ROOT / relative_path).resolve()
    if not str(target).startswith(str(ALLOWED_ROOT.resolve())):
        raise PermissionError(f"路径越界，只允许访问 {ALLOWED_ROOT}")
    return target


@mcp.tool()
def list_files(directory: str = "") -> dict:
    """
    列出 shared/outputs/ 下指定子目录的文件。

    Args:
        directory: 相对路径，留空则列出根目录

    Returns:
        {"files": [{"name": str, "size": int, "is_dir": bool}]}
    """
    target = _safe_path(directory)
    if not target.exists():
        return {"files": []}
    entries = []
    for p in sorted(target.iterdir()):
        entries.append({
            "name": p.name,
            "size": p.stat().st_size if p.is_file() else 0,
            "is_dir": p.is_dir(),
        })
    return {"files": entries}


@mcp.tool()
def read_file(path: str) -> dict:
    """
    读取 shared/outputs/ 下的文本文件内容。

    Args:
        path: 相对于 shared/outputs/ 的文件路径

    Returns:
        {"content": str, "size": int}
    """
    target = _safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"content": content, "size": target.stat().st_size}


@mcp.tool()
def write_file(path: str, content: str, overwrite: bool = False) -> dict:
    """
    在 shared/outputs/ 下写入文本文件。

    Args:
        path:      相对于 shared/outputs/ 的文件路径
        content:   要写入的文本内容
        overwrite: 文件已存在时是否覆盖（默认 False，存在则报错）

    Returns:
        {"path": str, "size": int}
    """
    target = _safe_path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"文件已存在: {path}，设置 overwrite=True 以覆盖")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": path, "size": target.stat().st_size}


@mcp.tool()
def delete_file(path: str) -> dict:
    """
    删除 shared/outputs/ 下的文件。

    Args:
        path: 相对于 shared/outputs/ 的文件路径

    Returns:
        {"deleted": str}
    """
    target = _safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    if target.is_dir():
        raise IsADirectoryError(f"{path} 是目录，不能用 delete_file 删除")
    target.unlink()
    return {"deleted": path}


@mcp.tool()
def file_exists(path: str) -> dict:
    """
    检查 shared/outputs/ 下文件是否存在。

    Args:
        path: 相对于 shared/outputs/ 的文件路径

    Returns:
        {"exists": bool, "is_dir": bool}
    """
    try:
        target = _safe_path(path)
        return {"exists": target.exists(), "is_dir": target.is_dir()}
    except PermissionError:
        return {"exists": False, "is_dir": False}


if __name__ == "__main__":
    mcp.run(transport="stdio")
