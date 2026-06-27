#!/usr/bin/env python3
"""
presenton 端到端测试
=====================
分两层运行：

  层 A — presenton-mcp SSE 层（9002）：无论上游是否在线都可跑
    - /sse 握手
    - 工具列表（generate_ppt / generate_ppt_from_markdown / list_ppts）
    - list_ppts smoke call（不依赖上游）

  层 B — 真实功能端到端（依赖 presenton:7860）：
    - MCP 调 generate_ppt → presenton HTTP → 生成 .pptx
    - 生成 .pptx 落 shared/outputs/
    - file-server 能 HTTP 下载
    - 通过 generate_ppt_from_markdown 做 Markdown→PPT

用法：
  # 运行全部（层 B 依赖 presenton:7860 已启动）
  python tools/test/test_presenton_e2e.py

  # 只跑层 A（上游未就绪时）
  python tools/test/test_presenton_e2e.py --layer a

  # 只跑层 B
  python tools/test/test_presenton_e2e.py --layer b

注意：运行前须确保 presenton-mcp(9002) 和 file-server(8090) 已启动。
层 B 还需要 presenton(7860) 已启动（docker-compose up -d presenton）。
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Windows GBK 控制台适配
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 本地服务绕系统代理
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client

ROOT = Path(__file__).parent.parent.parent
OUTPUTS_DIR = ROOT / "shared" / "outputs"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

_results: list[tuple[str, bool, str]] = []


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")
    _results.append((msg, True, ""))


def fail(msg: str, detail: str = "") -> None:
    print(f"  {RED}✗{RESET} {msg}")
    if detail:
        print(f"    {RED}→ {detail}{RESET}")
    _results.append((msg, False, detail))


def warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET} {msg}")


def section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ─────────────────────────────────────────────
# 层 A：presenton-mcp SSE 层（无需上游）
# ─────────────────────────────────────────────

async def test_layer_a() -> bool:
    section("层 A：presenton-mcp SSE 层（9002）— 无需上游")
    passed = True

    # A1: file-server 健康检查
    print("\n[A1] file-server 健康检查")
    try:
        c = httpx.Client(timeout=5, trust_env=False)
        r = c.get("http://localhost:8090/health")
        r.raise_for_status()
        ok(f"/health → {r.json()['status']}")
    except Exception as e:
        fail("file-server 不可达", str(e))
        passed = False

    # A2: SSE 握手 + 工具列表
    print("\n[A2] SSE 握手 + 工具列表")
    expected_tools = {"generate_ppt", "generate_ppt_from_markdown", "list_ppts"}
    try:
        async with sse_client("http://localhost:9002/sse") as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = await s.list_tools()
                tool_names = {t.name for t in tools.tools}
                ok(f"SSE 握手成功，工具数: {len(tool_names)}")

                missing = expected_tools - tool_names
                extra = tool_names - expected_tools
                if missing:
                    fail(f"缺少工具: {missing}")
                    passed = False
                else:
                    ok(f"工具列表完整: {sorted(tool_names)}")
                if extra:
                    warn(f"多余工具（非预期）: {extra}")

                # A3: list_ppts smoke call（不依赖上游）
                print("\n[A3] list_ppts smoke call（不依赖上游）")
                result = await s.call_tool("list_ppts", {})
                if result.isError:
                    fail("list_ppts 调用失败", result.content[0].text if result.content else "")
                    passed = False
                else:
                    data = json.loads(result.content[0].text)
                    ok(f"list_ppts 成功，当前 .pptx 文件数: {len(data.get('files', []))}")

    except Exception as e:
        fail("SSE 连接失败", str(e))
        passed = False

    return passed


# ─────────────────────────────────────────────
# 层 B：真实功能端到端（依赖 presenton:7860）
# ─────────────────────────────────────────────

async def test_layer_b() -> bool:
    section("层 B：真实功能端到端（依赖 presenton:7860）")
    passed = True
    http_client = httpx.Client(timeout=5, trust_env=False)

    # B0: 前置检查 — presenton:7860 是否在线
    print("\n[B0] presenton:7860 可达性检查")
    presenton_up = False
    try:
        r = http_client.get("http://localhost:7860/", timeout=3)
        presenton_up = r.status_code < 500
        ok(f"presenton:7860 可达，HTTP {r.status_code}")
    except Exception as e:
        fail("presenton:7860 不可达（未部署）", str(e))
        warn("层 B 需要 presenton 容器运行：docker-compose up -d presenton")
        return False  # 前置依赖不满足，跳过后续

    # B1: generate_ppt 端到端
    print("\n[B1] generate_ppt 端到端（MCP → presenton → .pptx 落盘 → HTTP 下载）")
    ppt_filename = f"e2e_test_{int(time.time())}.pptx"
    try:
        async with sse_client("http://localhost:9002/sse") as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                result = await s.call_tool("generate_ppt", {
                    "filename": ppt_filename,
                    "topic": "小学数学分数复习",
                    "outline": [
                        "第一页：分数的概念\n- 什么是分数\n- 分子与分母",
                        "第二页：分数的运算\n- 加减法\n- 约分通分",
                        "第三页：练习题\n- 典型例题\n- 课堂小结",
                    ],
                    "style": "educational",
                    "language": "zh",
                })

                if result.isError:
                    detail = result.content[0].text if result.content else ""
                    fail("generate_ppt 调用失败", detail)
                    passed = False
                else:
                    data = json.loads(result.content[0].text)
                    file_url = data.get("file_url", "")
                    slide_count = data.get("slide_count", 0)
                    ok(f"generate_ppt 成功: slide_count={slide_count}, url={file_url}")

                    # B2: 文件落盘检查
                    print("\n[B2] 文件落盘检查")
                    pptx_path = OUTPUTS_DIR / ppt_filename
                    if pptx_path.exists():
                        ok(f"文件已落盘: {pptx_path.name} ({pptx_path.stat().st_size} bytes)")
                    else:
                        fail(f"文件未找到: {pptx_path}")
                        passed = False

                    # B3: file-server HTTP 下载
                    print("\n[B3] file-server HTTP 下载")
                    if file_url:
                        try:
                            r_dl = http_client.get(file_url, timeout=10)
                            if r_dl.status_code == 200 and len(r_dl.content) > 1000:
                                ok(f"HTTP 下载成功: {r_dl.status_code}, {len(r_dl.content)} bytes")
                            else:
                                fail(f"下载异常: HTTP {r_dl.status_code}, {len(r_dl.content)} bytes")
                                passed = False
                        except Exception as e:
                            fail("HTTP 下载失败", str(e))
                            passed = False
                    else:
                        fail("file_url 为空，无法验证下载")
                        passed = False

    except Exception as e:
        fail("generate_ppt 测试异常", str(e))
        passed = False

    # B4: generate_ppt_from_markdown
    print("\n[B4] generate_ppt_from_markdown 端到端")
    md_filename = f"e2e_md_{int(time.time())}.pptx"
    markdown_content = """## 分数加减法

分母相同时，直接加减分子。

## 约分与通分

找最大公因数（约分）或最小公倍数（通分）。

## 练习

计算：1/3 + 1/6 = ?
"""
    try:
        async with sse_client("http://localhost:9002/sse") as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                result = await s.call_tool("generate_ppt_from_markdown", {
                    "filename": md_filename,
                    "markdown": markdown_content,
                    "style": "educational",
                })
                if result.isError:
                    fail("generate_ppt_from_markdown 失败", result.content[0].text if result.content else "")
                    passed = False
                else:
                    data = json.loads(result.content[0].text)
                    ok(f"generate_ppt_from_markdown 成功: slide_count={data.get('slide_count')}, url={data.get('file_url')}")
    except Exception as e:
        fail("generate_ppt_from_markdown 异常", str(e))
        passed = False

    # B5: list_ppts 能找到生成的文件
    print("\n[B5] list_ppts 确认生成文件可见")
    try:
        async with sse_client("http://localhost:9002/sse") as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                result = await s.call_tool("list_ppts", {})
                data = json.loads(result.content[0].text)
                pptx_files = {f["filename"] for f in data.get("files", [])}
                if ppt_filename in pptx_files:
                    ok(f"list_ppts 能看到 {ppt_filename}")
                else:
                    fail(f"list_ppts 未找到 {ppt_filename}，当前列表: {pptx_files}")
                    passed = False
    except Exception as e:
        fail("list_ppts 异常", str(e))
        passed = False

    return passed


# ─────────────────────────────────────────────
# main
# ─────────────────────────────────────────────

async def main(layer: str) -> None:
    print("=" * 60)
    print("presenton 端到端测试")
    print("=" * 60)

    results_a, results_b = True, True

    if layer in ("a", "all"):
        results_a = await test_layer_a()

    if layer in ("b", "all"):
        results_b = await test_layer_b()

    # 汇总
    print(f"\n{'='*60}")
    print("测试结果汇总")
    print(f"{'='*60}")
    if layer in ("a", "all"):
        status = f"{GREEN}PASS{RESET}" if results_a else f"{RED}FAIL{RESET}"
        print(f"  {status}  层 A（SSE 层，无上游）")
    if layer in ("b", "all"):
        status = f"{GREEN}PASS{RESET}" if results_b else f"{RED}FAIL{RESET}"
        print(f"  {status}  层 B（真实功能，依赖 presenton:7860）")
    print()

    all_pass = (results_a if layer in ("a", "all") else True) and \
               (results_b if layer in ("b", "all") else True)
    if all_pass:
        print(f"{GREEN}✅ 全部通过{RESET}")
        sys.exit(0)
    else:
        print(f"{RED}❌ 存在失败项{RESET}")
        print(f"\n排查建议:")
        print(f"  层 A 失败 → 检查 presenton-mcp(9002) 和 file-server(8090) 是否启动")
        print(f"             运行：bash tools/start_mcp_servers.sh start")
        print(f"  层 B 失败 → 检查 presenton:7860 是否启动")
        print(f"             运行：docker-compose up -d presenton  (在 infra/ 目录)")
        print(f"             然后查看日志：docker-compose logs presenton")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="presenton 端到端测试")
    parser.add_argument(
        "--layer",
        choices=["a", "b", "all"],
        default="all",
        help="运行哪层测试：a=仅SSE层, b=仅真实功能, all=全部（默认）",
    )
    args = parser.parse_args()
    asyncio.run(main(args.layer))
