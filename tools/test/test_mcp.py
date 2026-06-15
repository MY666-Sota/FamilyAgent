#!/usr/bin/env python3
"""
MCP 工具层自测脚本 — 用 MCP Python SDK 逐个连接并验证工具列表。
运行前须确保各 MCP server 和 file-server 已启动：
  python mcp-servers/office-word-mcp/server.py   (port 9001)
  python mcp-servers/presenton-mcp/server.py     (port 9002)
  python mcp-servers/paddleocr-mcp/server.py     (port 9003)
  python tools/file-server/server.py             (port 8090)

用法：
  python tools/test/test_mcp.py
  python tools/test/test_mcp.py --quick        # 只验证工具列表，不调用工具
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# Windows 控制台默认 GBK，强制 stdout/stderr 用 UTF-8，避免 ✓/✗ 等字符报错
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client

ROOT = Path(__file__).parent.parent.parent
REGISTRY_PATH = ROOT / "shared" / "mcp_registry.json"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def ok(msg):   print(f"  {GREEN}✓{RESET} {msg}")
def fail(msg): print(f"  {RED}✗{RESET} {msg}")
def warn(msg): print(f"  {YELLOW}!{RESET} {msg}")


async def test_sse_server(entry: dict, quick: bool) -> bool:
    name = entry["name"]
    url = entry["url"]
    expected_tools: list[str] = entry.get("tools", [])
    print(f"\n[{name}] SSE → {url}")

    try:
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                tool_names = [t.name for t in result.tools]
                ok(f"连接成功，工具数: {len(tool_names)}")

                # 验证期望的工具都在列表里
                missing = [t for t in expected_tools if t not in tool_names]
                extra = [t for t in tool_names if t not in expected_tools]
                if missing:
                    fail(f"缺少工具: {missing}")
                    return False
                if extra:
                    warn(f"额外工具（契约未定义）: {extra}")
                for t in tool_names:
                    ok(f"  tool: {t}")

                if quick:
                    return True

                # 对每个 server 做一次无副作用的 smoke call
                passed = await _smoke_call(session, name, tool_names)
                return passed

    except Exception as exc:
        fail(f"连接失败: {exc}")
        return False


async def _smoke_call(session: ClientSession, server_name: str, tool_names: list[str]) -> bool:
    """对各 server 做一次只读 / 无副作用的工具调用验证。"""
    smoke_map = {
        "office-word": ("list_documents", {}),
        "presenton":   ("list_ppts", {}),
        "paddleocr":   None,        # 需要图片，跳过
        "filesystem":  ("list_files", {"directory": ""}),
    }
    spec = smoke_map.get(server_name)
    if spec is None:
        warn("跳过 smoke call（需要外部资源）")
        return True
    tool, args = spec
    if tool not in tool_names:
        warn(f"smoke tool '{tool}' 不在工具列表中，跳过")
        return True
    try:
        result = await session.call_tool(tool, args)
        ok(f"smoke call '{tool}' 成功: {str(result.content)[:120]}")
        return True
    except Exception as exc:
        fail(f"smoke call '{tool}' 失败: {exc}")
        return False


async def test_stdio_server(entry: dict) -> bool:
    """filesystem-mcp 用 stdio 传输，验证启动后工具列表正确。"""
    from mcp.client.stdio import StdioServerParameters, stdio_client
    name = entry["name"]
    command = entry["command"].split()
    # 转成绝对路径
    cmd = command[0]
    args = command[1:]
    if args:
        args = [str(ROOT / a) for a in args]
    print(f"\n[{name}] stdio → {' '.join([cmd] + args)}")
    expected_tools: list[str] = entry.get("tools", [])

    try:
        params = StdioServerParameters(command=cmd, args=args, cwd=str(ROOT))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                tool_names = [t.name for t in result.tools]
                ok(f"启动成功，工具数: {len(tool_names)}")
                missing = [t for t in expected_tools if t not in tool_names]
                if missing:
                    fail(f"缺少工具: {missing}")
                    return False
                for t in tool_names:
                    ok(f"  tool: {t}")
                # smoke: file_exists 是只读无副作用的
                if "file_exists" in tool_names:
                    res = await session.call_tool("file_exists", {"path": "__probe__"})
                    ok(f"smoke call 'file_exists' 成功: {str(res.content)[:80]}")
                return True
    except Exception as exc:
        fail(f"stdio 启动失败: {exc}")
        return False


async def test_file_server() -> bool:
    """验证 file-server (8090) 的 /health 接口。"""
    print("\n[file-server] HTTP → http://localhost:8090")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:8090/health")
            resp.raise_for_status()
            data = resp.json()
            ok(f"/health 响应: {data}")
            resp2 = await client.get("http://localhost:8090/list")
            resp2.raise_for_status()
            ok(f"/list 响应: 文件数 {len(resp2.json().get('files', []))}")
        return True
    except Exception as exc:
        fail(f"file-server 不可达: {exc}")
        return False


async def main(quick: bool):
    print("=" * 60)
    print("FamilyAgent MCP 工具层自测")
    print("=" * 60)

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    results = {}

    # file-server 先验证（其他工具依赖它提供文件 URL）
    results["file-server"] = await test_file_server()

    for entry in registry:
        transport = entry.get("transport")
        name = entry["name"]
        if transport == "sse":
            results[name] = await test_sse_server(entry, quick)
        elif transport == "stdio":
            results[name] = await test_stdio_server(entry)
        else:
            warn(f"[{name}] 未知传输类型: {transport}，跳过")

    print("\n" + "=" * 60)
    print("自测结果汇总")
    print("=" * 60)
    all_passed = True
    for name, passed in results.items():
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print(f"{GREEN}全部通过 ✓{RESET}")
        sys.exit(0)
    else:
        print(f"{RED}存在失败项，请检查对应服务是否启动{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MCP 工具层自测")
    parser.add_argument("--quick", action="store_true", help="只验证工具列表，不做 smoke call")
    args = parser.parse_args()
    asyncio.run(main(quick=args.quick))
