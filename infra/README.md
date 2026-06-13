# infra — 基础设施层

FamilyAgent 基础设施层，负责部署和配置所有开源组件。

## 目录结构

```
infra/
├── chatgpt-on-wechat/
│   └── config.json.example   # 企微配置模板（复制为 config.json 并填写）
├── dify/
│   ├── Dockerfile            # 接口适配器镜像
│   └── adapter.py            # /v1/rag/query → Dify retrieve API
├── mem0/
│   ├── Dockerfile
│   └── app.py                # /v1/memory/{user_id} GET/POST
nginx/
└── nginx.conf                # 反向代理
docker-compose.yml
.env.example                  # 所有密钥占位符（复制为 .env 并填写）
```

## 快速启动

```bash
# 1. 复制并填写环境变量
cp .env.example .env
# 编辑 .env，填写 postgres/redis 密码、DeepSeek API key、企微凭证等

# 2. 复制企微配置
cp infra/chatgpt-on-wechat/config.json.example infra/chatgpt-on-wechat/config.json
# 编辑 config.json，把 ${WECHAT_*} 占位符替换为真实值

# 3. 启动所有服务
docker compose up -d

# 4. 查看日志
docker compose logs -f
```

## 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| nginx | 80 | 统一入口 |
| chatgpt-on-wechat | 8080 | 企微消息接收 |
| dify-adapter | 5001 | 知识库检索（接口契约 1.1）|
| mem0 | 8082 | 记忆读写（接口契约 1.2）|
| xinference | 9997 | Embedding / Reranker |
| ollama | 11434 | 本地 LLM（可选）|
| postgres | 5432 | 数据库 |
| redis | 6379 | 缓存 |

## 对外接口（INTERFACE_CONTRACT 接口一）

### 知识库检索
```
POST http://localhost:5001/v1/rag/query
{
  "user_id": "family_xiaoming",
  "query": "牛顿第二定律是什么",
  "mode": "simple",
  "top_k": 5
}
```

### 记忆读取
```
GET http://localhost:8082/v1/memory/family_xiaoming
```

### 记忆写入
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

### 企微回复（编排层调用）
```
POST http://localhost:8080/v1/reply
{
  "user_id": "family_xiaoming",
  "content_type": "text",
  "content": "已完成批改，共发现2处错误",
  "file_url": null
}
```

## Dify 初始化步骤

1. 访问 `http://localhost/dify/` 完成管理员注册
2. 创建知识库，上传家庭文档
3. 在「API 访问」页面获取 API Key，填入 `.env` 的 `DIFY_API_KEY`
4. 复制知识库 ID，填入 `.env` 的 `DIFY_DATASET_ID`
5. `docker compose restart dify-adapter`

## Xinference 初始化步骤

```bash
# 启动后加载 Embedding 和 Reranker 模型
curl -X POST http://localhost:9997/v1/models \
  -H 'Content-Type: application/json' \
  -d '{"model_name":"qwen3-embedding","model_type":"embedding"}'

curl -X POST http://localhost:9997/v1/models \
  -H 'Content-Type: application/json' \
  -d '{"model_name":"qwen3-reranker","model_type":"rerank"}'
```

## 健康检查

```bash
curl http://localhost/healthz              # nginx
curl http://localhost:5001/healthz         # dify-adapter
curl http://localhost:8082/healthz         # mem0
```
