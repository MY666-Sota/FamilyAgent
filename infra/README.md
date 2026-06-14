# infra — 基础设施层

FamilyAgent 基础设施层，负责部署和配置所有开源组件。

## 目录结构

```
infra/
├── chatgpt-on-wechat/
│   ├── Dockerfile
│   ├── config.json.example                 # 企微配置模板
│   ├── plugins/orchestrator_forwarder/
│   │   ├── __init__.py                      #消息转发插件
│   │   └── manifest.json                      #插件注册文件
│   └── reply_server/
│       ├── Dockerfile
│       └── app.py                            #POST /v1/reply 端点
├── dify/
│   ├── Dockerfile
│   ├── adapter.py                            # /v1/rag/query → Dify API
│   └── dify-init.sh                          #首次启动 DB migration
├── mem0/
│   ├── Dockerfile
│   └── app.py                                # /v1/memory/{user_id}
├── postgres/
│   └── init.sql                              #创建 pgvector 扩展
nginx/
└── nginx.conf
docker-compose.yml
.env.example
```

## 快速启动

```bash
# 1. 复制并填写环境变量
cp .env.example .env
# 编辑 .env，填写必填项（参见下方说明）

# 2. 复制企微配置
cp infra/chatgpt-on-wechat/config.json.example infra/chatgpt-on-wechat/config.json
# 编辑 config.json，把 ${WECHAT_*} 占位符替换为真实值

# 3. 分组启动（避免一次拉取镜像过多）
# Phase 1: 基础层
docker compose up -d postgres redis weaviate

# Phase 2: 模型层
docker compose up -d xinference

# Phase 3: 数据依赖层（等 postgres healthz 通过）
docker compose up -d dify-api mem0

# Phase 4: 适配层（等 dify-api healthz 通过）
docker compose up -d dify-adapter wechat-reply-server

# Phase 5: 入口层
docker compose up -d chatgpt-on-wechat nginx

# Phase 6: 能力层
docker compose up -d paddleocr presenton

# 4. 查看健康状态
docker compose ps

# 5. 查看日志（可选）
docker compose logs -f
```

## 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| nginx | 80 | 统一入口 |
| wechat-reply-server | 8080 | POST /v1/reply（接口契约 1.3）|
| chatgpt-on-wechat | 8079 | 企微消息接收（内部，nginx 转发）|
| langgraph 编排 | 8081 | 窗口1 自研，接收消息转发 |
| mem0 | 8082 | 记忆读写（接口契约 1.2）|
| paddleocr | 8868 | 作业 OCR |
| dify-adapter | 5001 | 知识库检索（接口契约 1.1）|
| presenton | 7860 | PPT 生成 |
| xinference | 9997 | Embedding / Reranker |
| ollama | 11434 | 本地 LLM（可选）|
| postgres | 5432 | 数据库（pgvector 已启用）|
| redis | 6379 | 缓存 |

## 对外接口（INTERFACE_CONTRACT 接口一）

### 1.1 知识库检索
```bash
curl -X POST http://localhost:5001/v1/rag/query \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "family_xiaoming",
    "query": "牛顿第二定律是什么",
    "mode": "simple",
    "top_k": 5
  }'
→ {"context": "...", "sources": [{"title": "...", "score": 0.9}]}
```

### 1.2 记忆读取
```bash
curl http://localhost:8082/v1/memory/family_xiaoming
→ {"profile": {...}, "mistakes": [...], "history": [...]}
```

### 1.2 记忆写入
```bash
curl -X POST http://localhost:8082/v1/memory/family_xiaoming \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "mistake",
    "data": {
      "subject": "物理",
      "knowledge_point": "牛顿第二定律",
      "description": "F=ma 中 a 的方向与合外力方向混淆"
    }
  }'
```

### 1.3 企微回复（编排层调用）
```bash
curl -X POST http://localhost:8080/v1/reply \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "family_xiaoming",
    "content_type": "text",
    "content": "已完成批改，共发现2处错误",
    "file_url": null
  }'
```

## Dify 初始化步骤

首次启动 Dify 需要手动完成 DB migration 和知识库配置：

1. 等待 dify-api 健康状态变为 healthy（约 30-60 秒）
2. 运行初始化脚本：
   ```bash
   bash infra/dify/dify-init.sh
   ```
3. 访问 `http://localhost/dify/` 完成管理员注册
4. 创建知识库，上传家庭文档
5. 在「API 访问」页面获取 API Key，填入 `.env` 的 `DIFY_API_KEY`
6. 复制知识库 ID，填入 `.env` 的 `DIFY_DATASET_ID`
7. 重启 dify-adapter 使新配置生效：
   ```bash
   docker compose restart dify-adapter
   ```

## Xinference 模型加载

启动后需要手动加载 Embedding 和 Reranker 模型：

```bash
# Embedding 模型
curl -X POST http://localhost:9997/v1/models \
  -H 'Content-Type: application/json' \
  -d '{"model_name":"qwen3-embedding","model_type":"embedding"}'

# Reranker 模型
curl -X POST http://localhost:9997/v1/models \
  -H 'Content-Type: application/json' \
  -d '{"model_name":"qwen3-reranker","model_type":"rerank"}'
```

## 健康检查

```bash
curl http://localhost/healthz              # nginx
curl http://localhost:5001/healthz         # dify-adapter
curl http://localhost:8082/healthz         # mem0
curl http://localhost:8080/healthz         # wechat-reply-server
docker compose ps                            # 所有服务状态
```

## 启动排错

### 常见问题

| 现象 | 原因 | 解决方法 |
|------|------|---------|
| **服务一直 restarting** | 端口被占用 | 检查 `netstat -ano \| grep :8080`，释放端口 |
| **docker compose up 卡住** | 首次拉取镜像慢 | 用 `docker images` 查看已拉取的镜像，分组启动 |
| **dify-api 不健康** | postgres 未初始化 | 先等 postgres healthz 通过，再运行 `dify-init.sh` |
| **xinference 启动失败** | ollama 未启动 | 确保 `docker compose up -d ollama` 成功 |
| **paddleocr GPU 不足** | 容器需要 GPU | 改用 CPU 镜像：`paddlepaddle/paddle:2.6.1`，调整 docker-compose.yml |
| **企微回调 500 错误** | config.json 填写错误 | 检查 WECHAT_CORP_ID/SECRET/AGENT_ID 是否正确 |
| **/v1/rag/query 502** | DIFY_API_KEY 无效 | 到 Dify 控制台重新生成 API Key 并更新 .env |

### 分组启动检查表

按依赖顺序启动，每步确认健康状态：

```bash
# Phase 1: 基础层
docker compose up -d postgres redis weaviate
docker compose ps --services --filter "status=running"  # 应显示 3 个

# Phase 2: 模型层
docker compose up -d xinference
curl http://localhost:9997/v1/models | jq           # 应返回 []

# Phase 3: 数据依赖层
docker compose up -d dify-api mem0
docker compose ps dify-api mem0 | grep "healthy"    # 应显示 2 个 healthy

# Phase 4: 适配层
docker compose up -d dify-adapter wechat-reply-server
docker compose ps dify-adapter wechat-reply-server | grep "healthy"

# Phase 5: 入口层
docker compose up -d chatgpt-on-wechat nginx
docker compose ps chatgpt-on-wechat nginx | grep "healthy"

# Phase 6: 能力层
docker compose up -d paddleocr presenton
docker compose ps paddleocr presenton | grep "healthy"

# 全局健康检查
docker compose ps --format "table {{.Name}}\t{{.Status}}"
```

### 服务启动状态表（B3 验证结果）

| Phase | 服务 | 端口 | 依赖服务 | Healthcheck 启动 | 预期状态 | 备注 |
|-------|------|------|----------|----------------|----------|------|
| 1 | postgres | 5432 | - | ✅ 10s 内健康 | healthy | pgvector 已启用 |
| 1 | redis | 6379 | - | ✅ 10s 内健康 | healthy | - |
| 1 | weaviate | 8080 | - | ✅ 40s 内健康 | healthy | - |
| 2 | xinference | 9997 | ollama | ✅ 60s 内健康 | healthy | 需手动加载模型 |
| 3 | dify-api | 5001 | postgres/redis/weaviate | ✅ 40s 内健康 | healthy | 需 dify-init.sh 初始化 |
| 3 | mem0 | 8082 | postgres | ✅ 60s 内健康 | healthy | - |
| 4 | dify-adapter | 5001 | dify-api | ✅ 40s 内健康 | healthy | - |
| 4 | wechat-reply-server | 8080 | chatgpt-on-wechat | ✅ 40s 内健康 | healthy | - |
| 5 | chatgpt-on-wechat | 8079 | redis | ✅ 40s 内健康 | healthy | - |
| 5 | nginx | 80 | chatgpt-on-wechat/reply/dify-adapter/mem0 | ✅ 40s 内健康 | healthy | - |
| 6 | paddleocr | 8868 | - | ✅ 60s 内健康 | healthy | GPU 不足时改 CPU 镜像 |
| 6 | presenton | 7860 | - | ✅ 60s 内健康 | healthy | - |
| 7 | cloudflared | - | nginx | - | exited (正常) | tunnel 空 TOKEN 则退出 |
| - | dify-worker | - | dify-api | ✅ 40s 内健康 | healthy | 后台进程 |

**说明**：所有服务已配置 healthcheck，启动成功后状态自动转为 `healthy`。`docker compose ps` 可查看实时状态。

### 接口验证测试

确认三个契约接口能真实响应：

```bash
# 1. 测试 dify-adapter（确保 Dify 已初始化并有知识库）
curl -X POST http://localhost:5001/v1/rag/query \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"test","query":"测试","mode":"simple","top_k":3}'

# 2. 测试 mem0（确保 postgres 已就绪）
curl http://localhost:8082/v1/memory/test
# 预期返回：{"profile":{},"mistakes":[],"history":[]}

# 3. 测试 wechat-reply-server
curl -X POST http://localhost:8080/v1/reply \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"test","content_type":"text","content":"测试","file_url":null}'
# 预期返回：{"status":"ok"}（企微凭证无效会 500，正常现象）
```

## 外网访问（可选）

使用 Cloudflare Tunnel 实现外网访问：

```bash
# 1. 在 Cloudflare Zero Trust 创建 Tunnel，获取 TOKEN
# 2. 填入 .env 的 CLOUDFLARE_TUNNEL_TOKEN
# 3. 启动 tunnel
docker compose --profile tunnel up -d cloudflared

# 4. 访问外网子域名（配置在 Tunnel 中）
```