# orchestrator（窗口1：编排核心）

负责 LangGraph 自研编排逻辑。仅本窗口在此目录写代码。
详见根目录 `INTERFACE_CONTRACT.md`。

## 快速开始

```bash
# 安装依赖
pip install -r orchestrator/requirements.txt

# 启动服务（mock 模式，无需外部依赖）
python -m orchestrator.server

# 运行测试
pytest orchestrator/tests/ -v
```

## 架构概览

```
POST /v1/message → StateGraph (11节点) → 回调 /v1/reply

节点流转：
START → input_guardrail → load_memory → classify_intent → router
                ↓                         ↓            ↓
         friendly_reject            route_to_agent  plan_subtasks
                ↓                         ↓            ↓
               END                 execute_agents ←←←
                                             ↓
                                    merge_results → output_guardrail → save_memory → END
```

## 依赖服务（真实联调时需要）

| 服务 | 窗口 | 端口 | 接口 | 环境变量 |
|------|------|------|------|----------|
| Mem0 记忆层 | 窗口2 | 8082 | GET/POST /v1/memory/{user_id} | USE_REAL_MEM0=true |
| Dify RAG | 窗口2 | 5001 | POST /v1/rag/query | USE_REAL_RAG=true |
| 渠道回调 | 窗口2 | 8080 | POST /v1/reply | USE_REAL_CHANNEL=true |
| office-word MCP | 窗口3 | 9001 | SSE JSON-RPC 2.0 | USE_REAL_MCP=true |
| presenton MCP | 窗口3 | 9002 | SSE JSON-RPC 2.0 | USE_REAL_MCP=true |
| paddleocr MCP | 窗口3 | 9003 | SSE JSON-RPC 2.0 | USE_REAL_MCP=true |

Mock 模式：所有 USE_REAL_* 默认为 false，服务未就绪时自动降级到 mock，保证可独立运行。

## 开发阶段

- **A1** (fbb4c5a): LangGraph 骨架 — FamilyAgentState、11节点 StateGraph、FastAPI 8081
- **A2** (cc56994): pytest 集成测试、Dockerfile、HTTP端到端验证
- **A3** (8419862): config.py 集中环境变量、mock→real 切换机制
- **A4** (597b319): MemorySaver checkpointer + thread_id 隔离 + /v1/message/sync
- **A5** (c859ad1): HTTP 层测试（TestClient + AsyncClient），25条 pytest 全通过
- **A6** (fbffb60): 真实依赖联调 — MCP SSE、Mem0、Dify，优雅降级
- **A7** (当前): 真实联调验证与修复 — 见下方「A7 联调结果」

## A7 联调结果（2026-06-16）

真实服务在线（Mem0 8082、MCP 9001-9003）后逐个打开开关实测。

### 结果矩阵

| 场景 | 依赖服务 | 开关 | 真实联调结果 |
|------|---------|------|------------|
| 记忆读取 | Mem0 8082 | USE_REAL_MEM0 | ✅ **真实通过** — GET 200，新用户返回空 profile 结构完整 |
| 记忆写入 | Mem0 8082 + embedding | USE_REAL_MEM0 | ⛔ **阻塞**（窗口2 embedding 401）→ 优雅降级，主流程不阻断 |
| MCP 连通 | 9001-9003 SSE | USE_REAL_MCP | ✅ **真实通过** — 标准 SSE transport 握手成功，只读工具调通 |
| MCP 写文件 | office-word 9001 | USE_REAL_MCP | ⚠️ **工具级报错**（窗口3 上游 conn failed）→ 透传 error，不崩 |
| 工具名/参数 | 9001-9003 | USE_REAL_MCP | ⚠️ **契约不匹配** → 见 INTERFACE_CONTRACT.md F2/F3，待窗口3 schema |
| 知识问答 | Dify 5001 | USE_REAL_RAG | ⏸️ **暂缓** — 知识库未初始化、DIFY_DATASET_ID 占位，保持 mock |

### A7 修复的编排核心问题

1. **MCP transport 协议错误**：原 `_sse_call` 直接 `POST /sse` 发裸 JSON-RPC，
   真实服务是标准 MCP SSE transport（`POST /sse` 返回 405）。改用官方 `mcp` SDK
   的 `sse_client` + `ClientSession` 完成握手。
2. **网关错误不降级**：原仅对 `ConnectError` 降级，502/503/504（上游未就绪）
   会透传 error。改为连接失败/超时/5xx 统一降级 mock，4xx 透传供排查。
3. **TaskGroup 异常逃逸**：在 `async with` 块内 raise 会被 anyio 包成
   ExceptionGroup 逃逸顶层。改为块内取回结果、块外解析。
4. **e2e 降级误判**：mock 返回加 `_source` sentinel，修正空 profile 被误判为
   失败、降级检测逻辑失效的问题；脚本强制 UTF-8 输出修复 Windows 中文乱码。

新增 `tests/test_mcp_client.py`（7 条）覆盖各降级分支，回归 32/32 通过。

## e2e 联调

```bash
# 启动窗口2/3 服务后，逐个打开开关运行联调脚本
USE_REAL_MEM0=true python orchestrator/e2e_integrate.py   # 记忆读写
USE_REAL_MCP=true  python orchestrator/e2e_integrate.py   # MCP 工具
# 也可在 orchestrator/.env 中配置开关（已 gitignore）
```

服务未就绪 / 网关错误 / 超时时自动降级 mock，对应场景显示 [SKIP]，编排核心不崩。

## 文件结构

```
orchestrator/
├── config.py          # 环境变量中心
├── state.py           # FamilyAgentState TypedDict
├── graph.py           # StateGraph + MemorySaver
├── server.py          # FastAPI 8081，/v1/message (async) + /v1/message/sync
├── mcp_client.py      # MCP Client（支持真实 SSE + 优雅降级 mock）
├── mock_services.py   # Mem0/RAG/Channel 客户端（真实 + 降级）
├── e2e_integrate.py   # e2e 联调脚本
├── nodes/
│   ├── guardrails.py  # input/output guardrail + friendly_reject
│   ├── memory.py      # load_memory / save_memory
│   ├── intent.py      # classify_intent（LLM + 关键词降级）
│   ├── router.py      # route_to_agent / plan_subtasks
│   └── agents.py      # execute_agents / merge_results
├── tests/
│   ├── test_graph.py       # 16条 graph 层测试
│   ├── test_server.py      # 9条 HTTP 层测试
│   └── test_mcp_client.py  # 7条 MCP 降级测试
├── Dockerfile
├── .env.example
└── requirements.txt
```

## 测试覆盖

- pytest: 32 条测试全通过（16 graph + 9 HTTP + 7 MCP 降级）
- e2e 联调: 5 场景（做PPT/作业批改/Word文档/知识问答/记忆读取）

## 约束

- 只写 orchestrator/ 目录，不碰 infra/、mcp-servers/、tools/
- shared/ 只读
- 端口 8081