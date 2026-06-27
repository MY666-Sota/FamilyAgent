#!/usr/bin/env python3
"""
filesystem-mcp 完整读写删闭环测试（纯本地，无上游依赖）。
验证 write_file / read_file / file_exists / list_files / delete_file
以及路径越界防护。
"""
import asyncio
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).parent.parent.parent
SERVER = ROOT / "tools" / "filesystem-mcp" / "server.py"

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
passed = 0
failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  {GREEN}✓{RESET} {msg}")
    else:
        failed += 1
        print(f"  {RED}✗{RESET} {msg}")


def _payload(result):
    """从 call_tool 结果取出 JSON dict。"""
    return json.loads(result.content[0].text)


async def main():
    print("=" * 60)
    print("filesystem-mcp 读写删闭环测试")
    print("=" * 60)

    params = StdioServerParameters(
        command="python", args=[str(SERVER)], cwd=str(ROOT)
    )
    test_file = "fs_test_probe.txt"
    test_content = "Hello from filesystem-mcp 中文测试 123"

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. 写入前确认不存在
            r = _payload(await session.call_tool("file_exists", {"path": test_file}))
            check(r["exists"] is False, "写入前文件不存在")

            # 2. 写入
            r = _payload(await session.call_tool(
                "write_file", {"path": test_file, "content": test_content}
            ))
            check(r["size"] > 0, f"write_file 成功，size={r['size']}")

            # 3. 存在性确认
            r = _payload(await session.call_tool("file_exists", {"path": test_file}))
            check(r["exists"] is True and r["is_dir"] is False, "写入后文件存在")

            # 4. 读回内容一致
            r = _payload(await session.call_tool("read_file", {"path": test_file}))
            check(r["content"] == test_content, "read_file 内容与写入一致（含中文）")

            # 5. 不带 overwrite 重复写入应报错
            #    FastMCP 把工具内异常包成 isError=True 的结果返回（而非抛客户端异常）
            r = await session.call_tool("write_file", {"path": test_file, "content": "x"})
            check(r.isError is True, "重复写入正确报错（overwrite=False，isError=True）")

            # 6. overwrite=True 覆盖成功
            r = _payload(await session.call_tool(
                "write_file",
                {"path": test_file, "content": "覆盖后内容", "overwrite": True},
            ))
            check(r["size"] > 0, "overwrite=True 覆盖成功")
            r = _payload(await session.call_tool("read_file", {"path": test_file}))
            check(r["content"] == "覆盖后内容", "覆盖后内容正确")

            # 7. list_files 包含测试文件
            r = _payload(await session.call_tool("list_files", {"directory": ""}))
            names = [f["name"] for f in r["files"]]
            check(test_file in names, f"list_files 包含测试文件（共 {len(names)} 项）")

            # 8. 路径越界防护
            r = await session.call_tool("read_file", {"path": "../../../etc/passwd"})
            check(r.isError is True, "路径越界被正确拦截（isError=True）")

            # 9. 删除
            r = _payload(await session.call_tool("delete_file", {"path": test_file}))
            check(r["deleted"] == test_file, "delete_file 成功")

            # 10. 删除后不存在
            r = _payload(await session.call_tool("file_exists", {"path": test_file}))
            check(r["exists"] is False, "删除后文件不存在")

    print("\n" + "=" * 60)
    print(f"结果：{GREEN}{passed} 通过{RESET}，{RED if failed else GREEN}{failed} 失败{RESET}")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())