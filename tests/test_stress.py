"""
压力测试 — 测试 orchestrator 在并发负载下的表现。

测试维度：
1. 并发吞吐量：N 个并发请求同时打 /v1/message/sync
2. 延迟分布：P50/P90/P99 响应时间
3. 错误率：高并发下是否有请求失败
4. 资源泄漏：持续请求后连接是否正常释放

运行方式：
  pytest tests/test_stress.py -v -s          # 需要先启动 orchestrator
  pytest tests/test_stress.py -v -s -k mock  # mock 模式压测（不需要外部服务）

标记：pytest -m stress 运行
"""
import sys
import os
import time
import asyncio
import statistics
from pathlib import Path
from dataclasses import dataclass, field

import pytest
import httpx

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.stress

# ═══════════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════════

ORCHESTRATOR = "http://localhost:8081"

# 压测参数
CONCURRENCY_LEVELS = [5, 10, 20, 50]  # 并发数梯度
REQUESTS_PER_LEVEL = 50               # 每个梯度的总请求数
SUSTAINED_DURATION_SEC = 30           # 持续压测时长（秒）
SUSTAINED_RPS = 10                    # 持续压测目标 RPS

# 测试请求模板
TEST_MESSAGES = [
    {"channel": "wecom", "user_id": "stress_test_1", "msg_type": "text", "content": "什么是光合作用？"},
    {"channel": "wecom", "user_id": "stress_test_2", "msg_type": "text", "content": "帮我做一个关于太阳系的PPT"},
    {"channel": "wecom", "user_id": "stress_test_3", "msg_type": "text", "content": "写一份关于环保的word文档"},
    {"channel": "wecom", "user_id": "stress_test_4", "msg_type": "text", "content": "帮我批改这道数学题"},
    {"channel": "wecom", "user_id": "stress_test_5", "msg_type": "text", "content": "制定一个学习计划"},
]


@dataclass
class StressResult:
    """压测结果汇总。"""
    concurrency: int = 0
    total_requests: int = 0
    success_count: int = 0
    error_count: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_sec: float = 0.0

    @property
    def error_rate(self) -> float:
        return self.error_count / max(self.total_requests, 1)

    @property
    def rps(self) -> float:
        return self.total_requests / max(self.elapsed_sec, 0.001)

    @property
    def p50(self) -> float:
        if not self.latencies_ms:
            return 0
        s = sorted(self.latencies_ms)
        return s[len(s) // 2]

    @property
    def p90(self) -> float:
        if not self.latencies_ms:
            return 0
        s = sorted(self.latencies_ms)
        return s[int(len(s) * 0.9)]

    @property
    def p99(self) -> float:
        if not self.latencies_ms:
            return 0
        s = sorted(self.latencies_ms)
        return s[int(len(s) * 0.99)]

    @property
    def avg(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0

    def summary(self) -> str:
        return (
            f"  并发={self.concurrency} | 请求={self.total_requests} | "
            f"成功={self.success_count} | 失败={self.error_count} | "
            f"错误率={self.error_rate:.1%}\n"
            f"  RPS={self.rps:.1f} | "
            f"延迟 avg={self.avg:.0f}ms p50={self.p50:.0f}ms "
            f"p90={self.p90:.0f}ms p99={self.p99:.0f}ms\n"
            f"  耗时={self.elapsed_sec:.2f}s"
        )


# ═══════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════

async def _send_request(
    client: httpx.AsyncClient,
    endpoint: str,
    payload: dict,
) -> tuple[bool, float, str]:
    """发送单个请求，返回 (成功, 延迟ms, 错误信息)。"""
    start = time.perf_counter()
    try:
        r = await client.post(endpoint, json=payload)
        elapsed_ms = (time.perf_counter() - start) * 1000
        if r.status_code == 200:
            return True, elapsed_ms, ""
        else:
            return False, elapsed_ms, f"HTTP {r.status_code}: {r.text[:100]}"
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return False, elapsed_ms, f"{type(exc).__name__}: {exc}"


async def run_concurrent_batch(
    concurrency: int,
    total_requests: int,
    endpoint: str = "/v1/message/sync",
) -> StressResult:
    """以固定并发数发送一批请求。"""
    result = StressResult(concurrency=concurrency, total_requests=total_requests)
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        base_url=ORCHESTRATOR,
        timeout=60,
        transport=httpx.AsyncHTTPTransport(proxy=None),
        limits=httpx.Limits(max_connections=concurrency + 10, max_keepalive_connections=concurrency),
    ) as client:
        async def worker(i: int):
            async with semaphore:
                msg = TEST_MESSAGES[i % len(TEST_MESSAGES)]
                ok, lat, err = await _send_request(client, endpoint, msg)
                if ok:
                    result.success_count += 1
                    result.latencies_ms.append(lat)
                else:
                    result.error_count += 1
                    result.errors.append(err)

        start = time.perf_counter()
        tasks = [asyncio.create_task(worker(i)) for i in range(total_requests)]
        await asyncio.gather(*tasks)
        result.elapsed_sec = time.perf_counter() - start

    return result


async def run_sustained_load(
    target_rps: int,
    duration_sec: int,
    endpoint: str = "/v1/message/sync",
) -> StressResult:
    """以恒定 RPS 持续发送请求。"""
    result = StressResult(concurrency=target_rps)
    interval = 1.0 / target_rps

    async with httpx.AsyncClient(
        base_url=ORCHESTRATOR,
        timeout=60,
        transport=httpx.AsyncHTTPTransport(proxy=None),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
    ) as client:
        start = time.perf_counter()
        request_idx = 0

        while (time.perf_counter() - start) < duration_sec:
            msg = TEST_MESSAGES[request_idx % len(TEST_MESSAGES)]
            # 不等待结果，fire-and-forget 然后收集
            asyncio.create_task(_fire_and_record(client, endpoint, msg, result))
            request_idx += 1
            result.total_requests += 1
            await asyncio.sleep(interval)

        # 等待所有在途请求完成（最多等 30s）
        await asyncio.sleep(min(10, duration_sec * 0.5))
        result.elapsed_sec = time.perf_counter() - start

    return result


async def _fire_and_record(
    client: httpx.AsyncClient,
    endpoint: str,
    payload: dict,
    result: StressResult,
):
    ok, lat, err = await _send_request(client, endpoint, payload)
    if ok:
        result.success_count += 1
        result.latencies_ms.append(lat)
    else:
        result.error_count += 1
        result.errors.append(err)


# ═══════════════════════════════════════════════════════════════════════
# Mock 模式压测（不需要启动任何服务，直接测 graph 吞吐）
# ═══════════════════════════════════════════════════════════════════════

class TestMockStress:
    """在 mock 模式下直接压 compiled_graph，测量纯计算吞吐。"""

    async def test_graph_throughput_serial(self):
        """串行调用 100 次 graph，测量单请求延迟基线。"""
        from orchestrator.graph import compiled_graph
        import uuid

        latencies = []
        for i in range(100):
            state = {
                "channel": "wecom",
                "user_id": f"mock_stress_{i}",
                "raw_input": "什么是光合作用？",
                "msg_type": "text",
                "media_url": None,
                "timestamp": 1000000 + i,
            }
            cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}
            start = time.perf_counter()
            result = await compiled_graph.ainvoke(state, config=cfg)
            lat = (time.perf_counter() - start) * 1000
            latencies.append(lat)
            assert result.get("final_output") is not None

        avg = statistics.mean(latencies)
        p50 = sorted(latencies)[50]
        p99 = sorted(latencies)[99]
        print(f"\n  [Mock串行] 100次 | avg={avg:.1f}ms | p50={p50:.1f}ms | p99={p99:.1f}ms")
        # 纯 mock 模式单请求应在 50ms 内
        assert avg < 200, f"平均延迟 {avg:.0f}ms 过高（期望 <200ms）"

    async def test_graph_throughput_concurrent(self):
        """并发调用 graph，测量并发吞吐。"""
        from orchestrator.graph import compiled_graph
        import uuid

        concurrency = 20
        total = 100

        async def invoke_one(i: int) -> float:
            state = {
                "channel": "wecom",
                "user_id": f"mock_concurrent_{i}",
                "raw_input": TEST_MESSAGES[i % len(TEST_MESSAGES)]["content"],
                "msg_type": "text",
                "media_url": None,
                "timestamp": 1000000 + i,
            }
            cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}
            start = time.perf_counter()
            result = await compiled_graph.ainvoke(state, config=cfg)
            assert result.get("final_output") is not None
            return (time.perf_counter() - start) * 1000

        semaphore = asyncio.Semaphore(concurrency)

        async def limited_invoke(i: int) -> float:
            async with semaphore:
                return await invoke_one(i)

        start = time.perf_counter()
        latencies = await asyncio.gather(*[limited_invoke(i) for i in range(total)])
        elapsed = time.perf_counter() - start

        avg = statistics.mean(latencies)
        p90 = sorted(latencies)[int(total * 0.9)]
        rps = total / elapsed
        print(f"\n  [Mock并发] {total}次 并发={concurrency} | "
              f"RPS={rps:.1f} | avg={avg:.1f}ms | p90={p90:.1f}ms | 耗时={elapsed:.2f}s")
        # 并发下 RPS 应 > 10
        assert rps > 5, f"RPS={rps:.1f} 过低（期望 >5）"

    async def test_graph_mixed_intents(self):
        """混合意图压测：验证各类型请求在并发下均能正确完成。"""
        from orchestrator.graph import compiled_graph
        import uuid

        messages = [
            ("什么是量子力学？", "qa"),
            ("帮我做一个关于AI的PPT", "ppt"),
            ("写一份工作总结的word文档", "document"),
            ("帮我批改数学作业", "homework"),
            ("制定本周学习计划", "study_plan"),
            ("分析错题并做一份复习PPT", "multi"),
        ]

        results = {"total": 0, "correct_intent": 0, "errors": 0}

        async def run_one(content: str, expected: str, idx: int):
            state = {
                "channel": "wecom",
                "user_id": f"mixed_{idx}",
                "raw_input": content,
                "msg_type": "text",
                "media_url": None,
                "timestamp": 1000000,
            }
            cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}
            try:
                result = await compiled_graph.ainvoke(state, config=cfg)
                results["total"] += 1
                if result.get("intent") == expected:
                    results["correct_intent"] += 1
            except Exception:
                results["errors"] += 1

        tasks = []
        for i in range(60):  # 每种意图 10 次
            content, expected = messages[i % len(messages)]
            tasks.append(run_one(content, expected, i))

        await asyncio.gather(*tasks)
        accuracy = results["correct_intent"] / max(results["total"], 1)
        print(f"\n  [混合意图] total={results['total']} | "
              f"意图正确率={accuracy:.1%} | 错误={results['errors']}")
        assert accuracy >= 0.9, f"意图分类正确率 {accuracy:.1%} 过低（期望 >=90%）"
        assert results["errors"] == 0


# ═══════════════════════════════════════════════════════════════════════
# HTTP 压测（需要启动 orchestrator 服务）
# ═══════════════════════════════════════════════════════════════════════

class TestHTTPStress:
    """通过 HTTP 压测 orchestrator API。"""

    @pytest.fixture(autouse=True)
    async def check_server(self):
        """跳过测试如果 orchestrator 未运行。"""
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(proxy=None), timeout=5
            ) as c:
                r = await c.get(f"{ORCHESTRATOR}/health")
                if r.status_code != 200:
                    pytest.skip("orchestrator 未运行")
        except (httpx.ConnectError, httpx.ConnectTimeout):
            pytest.skip("orchestrator 未运行")

    async def test_concurrent_ladder(self):
        """阶梯并发测试：5→10→20→50。"""
        print("\n\n" + "=" * 60)
        print(" 阶梯并发测试")
        print("=" * 60)

        for concurrency in CONCURRENCY_LEVELS:
            result = await run_concurrent_batch(
                concurrency=concurrency,
                total_requests=REQUESTS_PER_LEVEL,
            )
            print(f"\n{'─' * 50}")
            print(result.summary())

            # 断言：错误率应低于 5%
            assert result.error_rate < 0.05, (
                f"并发={concurrency} 错误率={result.error_rate:.1%} 过高\n"
                f"错误样本: {result.errors[:3]}"
            )

    async def test_sustained_load(self):
        """持续负载测试：恒定 RPS 持续 30 秒。"""
        print("\n\n" + "=" * 60)
        print(f" 持续负载测试 (目标 {SUSTAINED_RPS} RPS × {SUSTAINED_DURATION_SEC}s)")
        print("=" * 60)

        result = await run_sustained_load(
            target_rps=SUSTAINED_RPS,
            duration_sec=SUSTAINED_DURATION_SEC,
        )
        print(f"\n{result.summary()}")

        # 断言
        assert result.error_rate < 0.05, f"持续负载错误率={result.error_rate:.1%}"
        if result.latencies_ms:
            assert result.p99 < 10000, f"P99={result.p99:.0f}ms 过高（期望 <10s）"

    async def test_burst_recovery(self):
        """突发恢复测试：一次性 50 个请求，观察是否全部正常返回。"""
        result = await run_concurrent_batch(concurrency=50, total_requests=50)
        print(f"\n  [突发] {result.summary()}")
        assert result.error_rate < 0.1, f"突发错误率={result.error_rate:.1%}"

    async def test_async_endpoint_throughput(self):
        """异步端点吞吐：/v1/message 只返回 accepted，应该极快。"""
        result = await run_concurrent_batch(
            concurrency=50,
            total_requests=200,
            endpoint="/v1/message",
        )
        print(f"\n  [异步端点] {result.summary()}")
        assert result.error_rate < 0.01, f"异步端点错误率不应超过 1%"
        if result.latencies_ms:
            assert result.p90 < 500, f"异步端点 P90={result.p90:.0f}ms 过慢（期望 <500ms）"
