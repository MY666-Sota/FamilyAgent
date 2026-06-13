# infra — 基础设施层

FamilyAgent 基础设施层，负责部署和配置所有开源组件。

## 目录结构

```
infra/
├── chatgpt-on-wechat/
│   ├── Dockerfile                          # 官方镜像 + 插件
│   ├── config.json.example                 # 企微配置模板
│   ├── plugins/orchestrator_forwarder/     # 转发消息到编排层
│   └── reply_server/                       # POST /v1/reply 端点
├── dify/
│   ├── Dockerfile
│   └── adapter.py                          # /v1/rag/query → Dify API
├── mem0/
│   ├── Dockerfile
│   └── app.py                              # /v1/memory/{user_id}
├── postgres/
│   └── init.sql                            # 创建 pgvector 扩展
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

# 3. 启动核心栈
docker compose up -d

# 4. 如需外网访问（需先在 Cloudflare 创建 Tunnel 并获取 Token）
docker compose --profile tunnel up -d cloudflared

# 5. 查看日志
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
```
POST http://localhost:5001/v1/rag/query
{
  "user_id": "family_xiaoming",
  "query": "牛顿第二定律是什么",
  "mode": "simple",
  "top_k": 5
}
→ { "context": "...", "sources": [{"title": "...", "score": 0.9}] }
```

### 1.2 记忆读取
```
GET http://localhost:8082/v1/memory/family_xiaoming
→ { "profile": {...}, "mistakes": [...], "history": [...] }
```

### 1.2 记忆写入
```
POST http://localhost:8082/v1/memory/family_xiaoming
{
  "type": "mistake",
  "data": {
    "subject": "物理",
    "knowledge_point": "牛顿第二定律",
    "description": "F=ma 中 a 的方向与合外力方向混淆"
  }
}
```

### 1.3 企微回复（编排层调用）
```
POST http://localhost:8080/v1/reply
{
  "user_id": "family_xiaoming",
  "content_type": "text",
  "content": "已完成批改，共发现2处错误",
  "file_url": null
}
```

## 初始化步骤

### Dify 知识库
1. 访问 `http://localhost/dify/` 完成管理员注册
2. 创建知识库，上传家庭文档
3. 在「API 访问」页面获取 API Key，填入 `.env` 的 `DIFY_API_KEY`
4. 复制知识库 ID，填入 `.env` 的 `DIFY_DATASET_ID`
5. `docker compose restart dify-adapter`

### Xinference 模型加载
```bash
curl -X POST http://localhost:9997/v1/models \
  -H 'Content-Type: application/json' \
  -d '{"model_name":"qwen3-embedding","model_type":"embedding"}'

curl -X POST http://localhost:9997/v1/models \
  -H 'Content-Type: application/json' \
  -d '{"model_name":"qwen3-reranker","model_type":"rerank"}'
```

### Cloudflare Tunnel（外网访问）
1. 在 Cloudflare Zero Trust 控制台创建 Tunnel
2. 复制 Token，填入 `.env` 的 `CLOUDFLARE_TUNNEL_TOKEN`
3. 配置 Tunnel 指向 `http://localhost:80`
4. `docker compose --profile tunnel up -d cloudflared`

## 健康检查

```bash
curl http://localhost/healthz              # nginx
curl http://localhost:5001/healthz         # dify-adapter
curl http://localhost:8082/healthz         # mem0
curl http://localhost:8080/healthz         # wechat-reply-server
```