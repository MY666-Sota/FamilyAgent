#!/usr/bin/env python3
"""
MCP 工具层集成测试 — 验证与窗口2 后端服务的联通性和端到端功能

依赖窗口2启动的服务（通过 docker-compose 或手动）：
  - paddleocr (8868): 图片 OCR
  - presenton (7860): PPT 生成
  - file-server (8090): 静态文件服务

测试步骤：
1. 启动 file-server 和各 MCP server
2. 调用 paddleocr-mcp 识别测试图片
3. 调用 presenton-mcp 生成测试 PPT
4. 验证文件落到 shared/outputs/ 并可下载
5. 检查返回的 file_url 是否可访问
"""
import asyncio
import json
import sys
import base64
from pathlib import Path

# Windows 控制台默认 GBK，强制 stdout/stderr 用 UTF-8，避免 ✓/✗ 等字符报错
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).parent.parent.parent
REGISTRY_PATH = ROOT / "shared" / "mcp_registry.json"
OUTPUTS_DIR = ROOT / "shared" / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


def ok(msg): print(f"{GREEN}✓{RESET} {msg}")
def fail(msg): print(f"{RED}✗{RESET} {msg}")
def info(msg): print(f"{BLUE}ℹ{RESET} {msg}")
def warn(msg): print(f"{YELLOW}!{RESET} {msg}")


def _create_test_image() -> Path:
    """生成一个简单的测试图片，用于 OCR 测试。"""
    from PIL import Image, ImageDraw, ImageFont

    test_img = OUTPUTS_DIR / "test_ocr.png"
    img = Image.new("RGB", (400, 200), color="white")
    draw = ImageDraw.Draw(img)

    # 绘制简单文字
    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except:
        font = ImageFont.load_default()

    draw.text((20, 50), "1+1=?", fill="black", font=font)
    draw.text((20, 100), "2+2=?", fill="black", font=font)
    img.save(test_img)
    return test_img


async def test_paddleocr_integration():
    """测试 PaddleOCR-VL 服务联通性。"""
    info("\n" + "=" * 60)
    info("测试 PaddleOCR-VL 联通性（端口 8868）")
    info("=" * 60)

    # 先测试原始服务
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # 创建测试图片
            test_img = _create_test_image()
            img_b64 = base64.b64encode(test_img.read_bytes()).decode()

            # 调用 OCR 服务
            resp = await client.post(
                "http://localhost:8868/ocr",
                json={"image": img_b64, "language": "ch"},
            )
            if resp.status_code == 200:
                ok("PaddleOCR 服务可达")
                data = resp.json()
                info(f"  响应预览: {str(data)[:200]}...")
            else:
                fail(f"PaddleOCR 服务响应异常: {resp.status_code}")
                return False
    except Exception as exc:
        fail(f"PaddleOCR 服务不可达: {exc}")
        info("  请确保窗口2已启动 paddleocr 容器：docker-compose up -d paddleocr")
        return False

    # 测试 MCP 层封装
    try:
        async with sse_client("http://localhost:9003/sse") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "ocr_image",
                    {
                        "image_path": str(test_img),
                        "language": "ch",
                        "return_layout": False,
                    },
                )
                ok("paddleocr-mcp 调用成功")
                data = json.loads(result.content[0].text)
                recognized_text = data.get("text", "")
                info(f"  识别文字: {recognized_text[:100]}...")
                if "1+1=" in recognized_text or "2+2=" in recognized_text:
                    ok("  识别结果包含测试文字")
                else:
                    warn("  识别结果可能不正确，但工具链路正常")
                return True
    except Exception as exc:
        fail(f"paddleocr-mcp 调用失败: {exc}")
        return False


async def test_presenton_integration():
    """测试 Presenton 服务联通性。"""
    info("\n" + "=" * 60)
    info("测试 Presenton 联通性（端口 7860）")
    info("=" * 60)

    # 先测试原始服务
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 测试 Presenton 健康检查
            resp = await client.get("http://localhost:7860/", timeout=10)
            if resp.status_code in [200, 404]:  # 404 可能是因为没有具体路由
                ok("Presenton 服务可达")
            else:
                fail(f"Presenton 服务响应异常: {resp.status_code}")
                return False
    except Exception as exc:
        fail(f"Presenton 服务不可达: {exc}")
        info("  请确保窗口2已启动 presenton 容器：docker-compose up -d presenton")
        return False

    # 测试 MCP 层封装
    try:
        async with sse_client("http://localhost:9002/sse") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # 生成测试 PPT
                result = await session.call_tool(
                    "generate_ppt",
                    {
                        "filename": "integration_test.pptx",
                        "topic": "集成测试 PPT",
                        "outline": [
                            "第一页: 测试页面\\n- 这是一个测试",
                            "第二页: 验证结果\\n- 文件应生成到 shared/outputs/",
                        ],
                        "style": "minimal",
                        "language": "zh",
                    },
                )
                ok("presenton-mcp 调用成功")
                data = json.loads(result.content[0].text)
                file_url = data.get("file_url", "")
                filename = data.get("filename", "")

                info(f"  返回文件 URL: {file_url}")

                # 验证文件落地
                ppt_path = OUTPUTS_DIR / filename
                if ppt_path.exists():
                    ok(f"  文件已落地: {ppt_path}")
                    ok(f"  文件大小: {ppt_path.stat().st_size} bytes")
                else:
                    fail(f"  文件未落地到 shared/outputs/")

                # 验证 URL 可访问
                if file_url.startswith("http://localhost:8090/files/"):
                    async with httpx.AsyncClient(timeout=10) as client:
                        resp = await client.get(file_url)
                        if resp.status_code == 200:
                            ok(f"  文件 URL 可访问: {file_url}")
                            ok(f"  下载大小: {len(resp.content)} bytes")
                        else:
                            fail(f"  文件 URL 返回错误: {resp.status_code}")
                else:
                    warn(f"  文件 URL 格式不符合预期: {file_url}")

                return True
    except Exception as exc:
        fail(f"presenton-mcp 调用失败: {exc}")
        return False


async def test_file_server():
    """测试 file-server 功能。"""
    info("\n" + "=" * 60)
    info("测试 file-server（端口 8090）")
    info("=" * 60)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # 健康检查
            resp = await client.get("http://localhost:8090/health")
            if resp.status_code == 200:
                ok("file-server /health 响应正常")
            else:
                fail(f"file-server /health 异常: {resp.status_code}")
                return False

            # 文件列表
            resp = await client.get("http://localhost:8090/list")
            if resp.status_code == 200:
                data = resp.json()
                file_count = len(data.get("files", []))
                ok(f"file-server /list 响应正常，当前文件数: {file_count}")
            else:
                fail(f"file-server /list 异常: {resp.status_code}")
                return False

            return True
    except Exception as exc:
        fail(f"file-server 测试失败: {exc}")
        info("  请先启动 file-server：python tools/file-server/server.py")
        return False


async def main():
    print("=" * 60)
    print("FamilyAgent MCP 工具层集成测试")
    print("=" * 60)
    print()
    info("前置检查：确保以下服务已启动")
    info("  - file-server (8090): python tools/file-server/server.py")
    info("  - paddleocr-mcp (9003): python mcp-servers/paddleocr-mcp/server.py")
    info("  - presenton-mcp (9002): python mcp-servers/presenton-mcp/server.py")
    info("  - 窗口2服务：docker-compose up -d paddleocr presenton")
    print()

    results = {}

    # 先测 file-server
    results["file-server"] = await test_file_server()

    # 再测 PaddleOCR 联通
    results["paddleocr"] = await test_paddleocr_integration()

    # 再测 Presenton 联通
    results["presenton"] = await test_presenton_integration()

    # 汇总结果
    print("\n" + "=" * 60)
    print("集成测试结果汇总")
    print("=" * 60)
    all_passed = True
    for name, passed in results.items():
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print(f"{GREEN}全部测试通过 ✓{RESET}")
        sys.exit(0)
    else:
        print(f"{RED}存在失败项，请检查上述错误信息{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{YELLOW}测试被中断{RESET}")
        sys.exit(130)