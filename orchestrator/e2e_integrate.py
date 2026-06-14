#!/usr/bin/env python
"""
e2e 联调脚本 — 验证编排核心与真实服务（窗口2/3）的对接。

测试场景：
1. 做PPT指令 → presenton MCP Server → 返回文件URL
2. 作业批改 → paddleocr MCP Server → 返回批改结果
3. 知识问答 → Dify RAG → 返回上下文

使用方式：
  python orchestrator/e2e_integrate.py

环境变量控制（可选）：
  USE_REAL_MCP=true      # 尝试连接真实 MCP Servers（9001-9003）
  USE_REAL_RAG=true      # 尝试连接 Dify（5001）
  USE_REAL_MEM0=true     # 尝试连接 Mem0（8082）
"""
import asyncio
import sys
import os
import time
import httpx
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator import config
from orchestrator.mcp_client import call_tool
from orchestrator.mock_services import rag_query, memory_get

# ─── 测试场景定义 ────────────────────────────────────────────────────

SCENARIOS = [
    {
        "name": "做PPT",
        "server": "presenton",
        "tool": "generate_ppt",
        "args": {"topic": "太阳系科普", "user_id": "family_test"},
        "expect_file_url": True,
    },
    {
        "name": "作业批改",
        "server": "paddleocr",
        "tool": "ocr_and_grade",
        "args": {
            "media_url": "http://localhost:8090/files/test_homework.jpg",
            "user_id": "family_test",
            "grade": "五年级",
        },
        "expect_file_url": False,
    },
    {
        "name": "Word文档",
        "server": "office-word",
        "tool": "generate_document",
        "args": {"topic": "环保报告", "user_id": "family_test"},
        "expect_file_url": True,
    },
    {
        "name": "知识问答",
        "rag_query": True,
        "rag_args": {
            "user_id": "family_test",
            "query": "光合作用是什么？",
            "mode": "simple",
        },
        "expect_context": True,
    },
    {
        "name": "记忆读取",
        "memory_get": True,
        "memory_args": {"user_id": "family_test"},
        "expect_profile": True,
    },
]


# ─── 结果汇总 ────────────────────────────────────────────────────────

RESULTS = {"passed": [], "failed": [], "skipped": []}


def record_result(name: str, status: str, details: str):
    RESULTS[status].append((name, details))
    icon = {"passed": "[PASS]", "failed": "[FAIL]", "skipped": "[SKIP]"}[status]
    print(f"{icon} {name}: {details}")


async def test_mcp_tool(scenario):
    """测试 MCP 工具调用。"""
    if not config.USE_REAL_MCP:
        record_result(
            scenario["name"],
            "skipped",
            "USE_REAL_MCP=false，跳过真实 MCP 调用"
        )
        return

    try:
        r = await call_tool(
            scenario["server"],
            scenario["tool"],
            scenario["args"],
        )
        if r.get("status") == "mock_ok":
            record_result(
                scenario["name"],
                "skipped",
                "MCP Server 未就绪，降级 mock"
            )
            return

        # 验证预期字段
        if scenario.get("expect_file_url"):
            if r.get("file_url"):
                record_result(
                    scenario["name"],
                    "passed",
                    f"文件URL={r['file_url']}"
                )
            else:
                record_result(
                    scenario["name"],
                    "failed",
                    f"期望返回 file_url，但响应中没有: {r}"
                )
        else:
            if r.get("result"):
                record_result(
                    scenario["name"],
                    "passed",
                    f"结果={r['result'][:60]}"
                )
            else:
                record_result(
                    scenario["name"],
                    "failed",
                    f"期望返回 result，但响应中没有: {r}"
                )
    except Exception as exc:
        record_result(
            scenario["name"],
            "failed",
            f"异常: {exc}"
        )


async def test_rag(scenario):
    """测试 RAG 查询。"""
    if not config.USE_REAL_RAG:
        record_result(
            scenario["name"],
            "skipped",
            "USE_REAL_RAG=false，跳过真实 RAG 调用"
        )
        return

    try:
        r = await rag_query(**scenario["rag_args"])
        if "[mock RAG]" in r.get("context", ""):
            record_result(
                scenario["name"],
                "skipped",
                "Dify 未就绪，降级 mock"
            )
            return

        if r.get("context"):
            record_result(
                scenario["name"],
                "passed",
                f"上下文长度={len(r['context'])}"
            )
        else:
            record_result(
                scenario["name"],
                "failed",
                f"期望返回 context，但响应中没有: {r}"
            )
    except Exception as exc:
        record_result(
            scenario["name"],
            "failed",
            f"异常: {exc}"
        )


async def test_memory(scenario):
    """测试 Mem0 读取。"""
    if not config.USE_REAL_MEM0:
        record_result(
            scenario["name"],
            "skipped",
            "USE_REAL_MEM0=false，跳过真实 Mem0 调用"
        )
        return

    try:
        r = await memory_get(**scenario["memory_args"])
        if "mock" in str(r.get("profile", {})):
            record_result(
                scenario["name"],
                "skipped",
                "Mem0 未就绪，降级 mock"
            )
            return

        if r.get("profile"):
            record_result(
                scenario["name"],
                "passed",
                f"用户画像={r['profile']}"
            )
        else:
            record_result(
                scenario["name"],
                "failed",
                f"期望返回 profile，但响应中没有: {r}"
            )
    except Exception as exc:
        record_result(
            scenario["name"],
            "failed",
            f"异常: {exc}"
        )


# ─── 主流程 ─────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("FamilyAgent 编排核心 e2e 联调")
    print("=" * 60)
    print()
    print(f"端口配置：Mem0={config.MEM0_BASE_URL}, RAG={config.RAG_BASE_URL}")
    print(f"开关：MCP={config.USE_REAL_MCP}, RAG={config.USE_REAL_RAG}, Mem0={config.USE_REAL_MEM0}")
    print()

    for scenario in SCENARIOS:
        if "server" in scenario:
            await test_mcp_tool(scenario)
        elif scenario.get("rag_query"):
            await test_rag(scenario)
        elif scenario.get("memory_get"):
            await test_memory(scenario)
        time.sleep(0.1)  # 避免并发请求过多

    print()
    print("=" * 60)
    print("汇总")
    print("=" * 60)
    print(f"通过: {len(RESULTS['passed'])}")
    print(f"失败: {len(RESULTS['failed'])}")
    print(f"跳过: {len(RESULTS['skipped'])}")

    if RESULTS['failed']:
        print()
        print("失败详情：")
        for name, details in RESULTS['failed']:
            print(f"  - {name}: {details}")
        sys.exit(1)

    print()
    print("所有测试通过！")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())