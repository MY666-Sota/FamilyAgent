# FamilyAgent

基于 LangGraph 与 MCP 的可审计多 Agent 家庭 AI 服务原型。

FamilyAgent 面向私有化部署场景，将消息接入、任务规划、长期记忆、知识检索和文件类工具组织成一条可恢复的工作流。项目重点不是“聊天 Demo”，而是展示 Agent 系统在状态管理、工具协议、故障降级和测试验证方面的工程实现。

## 能做什么

- 知识问答、作业图片 OCR 与 LLM 批改
- Word 文档和 PPT 生成（通过 MCP 工具接入）
- 多意图任务拆解与 Agent 执行
- Mem0 长期记忆与用户级会话隔离
- 输入/输出安全护栏
- MCP SSE 工具调用、超时/5xx 优雅降级
- Mock 模式独立运行，便于本地开发和测试

## 架构与数据流

```text
消息入口
  -> input_guardrail
  -> load_memory
  -> classify_intent
  -> route_to_agent / plan_subtasks
  -> execute_agents
  -> merge_results
  -> output_guardrail
  -> save_memory
  -> 结果回传
```

编排核心使用 LangGraph StateGraph 管理状态；工具层使用 MCP 统一暴露文档、PPT、OCR 和文件服务；真实依赖不可用时，客户端在边界处降级到 mock，避免单个服务故障拖垮主流程。

## 技术栈

- Python、FastAPI、LangGraph
- MCP（SSE transport）
- Mem0、混合 RAG（BM25 + 向量检索 + Rerank 接口）
- Docker Compose、PostgreSQL、Redis
- pytest、httpx

## 快速开始

### 1. 安装编排核心依赖

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r orchestrator/requirements.txt
```

### 2. 运行 Mock 模式

```bash
python -m orchestrator.server
```

默认服务地址为 `http://localhost:8081`。Mock 模式不要求启动外部模型、记忆库或 MCP 服务。

### 3. 运行测试

```bash
pytest -q
```

核心测试位于 `orchestrator/tests/`，覆盖 StateGraph、HTTP 接口和 MCP 客户端降级分支；`tests/` 包含集成与压力测试，运行这些测试时需要相应本地服务。

### 4. 启用真实依赖（可选）

复制并编辑环境变量模板：

```bash
cp .env.example .env
cp orchestrator/.env.example orchestrator/.env
```

仅在本地 `.env` 中填写 API Key。不要将 `.env`、数据库卷、生成文件或真实家庭数据提交到仓库。

## 项目结构

```text
FamilyAgent/
├── orchestrator/          # LangGraph 编排核心与 HTTP 服务
├── mcp-servers/            # Word、PPT、OCR 等 MCP 服务
├── infra/                  # Docker、Mem0、RAG 与渠道适配
├── tools/                  # 文件服务、Mock 服务和测试工具
├── shared/                 # 跨模块 schema 与工具注册表
├── tests/                  # 集成与压力测试
├── docker-compose.yml
└── INTERFACE_CONTRACT.md   # 模块边界与接口契约
```

## 当前状态与限制

这是一个持续演进的工程实践项目。编排核心、记忆读写、意图分类、Word 生成和 OCR + LLM 批改链路已有联调记录；PPT 生成和知识库检索依赖对应服务的本地配置。请以实际启动日志和测试结果为准，不要将未启动的可选服务描述为默认可用。

## 安全边界

- 默认采用本地化部署思路，敏感数据不应进入公开仓库。
- 所有凭据只能通过环境变量注入，并保留在被 Git 忽略的 `.env` 文件中。
- 生产部署前应补充认证、访问控制、日志脱敏和数据备份策略。

## License

本项目采用 [MIT License](LICENSE) 开源。第三方组件仍受其各自许可证约束。
