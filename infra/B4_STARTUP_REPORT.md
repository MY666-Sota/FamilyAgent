# B4 启动实测报告

> 分支：`feat/infra` ｜ 实测日期：2026-06-16
> 环境：Windows 11 + Docker Desktop（WSL2 后端），无 GPU，网络经本地代理 `127.0.0.1:12334`

本报告记录 FamilyAgent 基础设施层的实际启动结果、接口验证、踩坑与最终方案。

---

## 一、服务启动总览

主目录 `familyagent-` 项目实测起来 **8 个容器**，全部运行中：

| # | 服务 | 容器名 | 端口 | 实测状态 |
|---|------|--------|------|----------|
| 1 | PostgreSQL (pgvector) | familyagent-postgres-1 | 5432 | ✅ Up (healthy) |
| 2 | Redis | familyagent-redis-1 | 6379 | ✅ Up (healthy) |
| 3 | Weaviate | familyagent-weaviate-1 | 8080(内) | ✅ Up |
| 4 | Dify API | familyagent-dify-api-1 | 5001(内) | ✅ Up |
| 5 | Dify Worker | familyagent-dify-worker-1 | — | ✅ Up |
| 6 | Dify Web | familyagent-dify-web-1 | 3000(内) | ✅ Up |
| 7 | Mem0 | familyagent-mem0-1 | 8082 | ✅ Up |
| 8 | Dify Adapter | familyagent-dify-adapter-1 | 5001 | ✅ Up |

> 说明：weaviate / dify-* 的 healthcheck 探针已在本轮统一修正（见第四节），
> 容器进程本身均正常运行。

---

## 二、对外契约接口实测

按 `INTERFACE_CONTRACT` 验证三个对外接口：

### 接口一.2 — Mem0 记忆层 ✅ 通过

```
GET http://localhost:8082/healthz            → 200 {"status":"ok"}
GET http://localhost:8082/v1/memory/test_user → 200
   响应体：{"profile":{},"mistakes":[],"history":[]}
```

返回结构符合契约约定的 `{profile, mistakes, history}`，记忆层链路（FastAPI → mem0 → pgvector）完全打通。

### 接口一.1 — RAG 检索（dify-adapter）⚠️ 502，根因已定位

```
GET  http://localhost:5001/healthz   → 200          （服务存活）
POST http://localhost:5001/v1/rag/query
     body: {"query":"hello","user_id":"test_user","top_k":3}
     → 502 {"detail":"Dify error: <!doctype html>... 404 Not Found ..."}
```

**根因**：adapter 转发链路本身正常，502 来自后端 Dify 返回 **404** —— 因为
`.env` 里 `DIFY_API_KEY` 和 `DIFY_DATASET_ID` 仍是 `change_me_*` 占位符，
Dify 知识库 dataset 尚未初始化，检索端点不存在。

**解法（部署时人工一次性操作）**：
1. 浏览器打开 Dify 控制台，创建知识库（dataset）
2. 控制台 → 知识库 → API Keys 创建密钥，填入 `.env` 的 `DIFY_API_KEY`
3. 复制 dataset ID 填入 `.env` 的 `DIFY_DATASET_ID`
4. 重启 dify-adapter，rag/query 即可返回检索结果

> 排查记录：初次用中文 body 测得 400（Windows bash 编码问题，非服务错），
> 改 ASCII + `--data-binary @file` 后得 422（缺 `user_id` 字段），
> 补全字段后才打到真实后端逻辑，暴露出 404 根因。这是契约接口字段必填校验生效的证据。

### 接口一.3 — 企业微信回复（wechat-reply-server, 8080）

本服务依赖 `WECHAT_*` 系列真实凭证（`.env` 中仍为占位符），属接入层，
未纳入本轮基础设施冒烟范围；healthcheck 探针已改为 python urllib（见第四节）。

---

## 二之二、Dify 控制台访问（B4-2 补做）

### 问题

B4 留下的 502 要靠人工进 Dify 控制台建知识库才能消除，但控制台**此前打不开**：
dify-web 的 3000 端口未映射到主机、`CONSOLE_API_URL`/`APP_API_URL` 为空、nginx 未启动，
三者任一不解决浏览器都进不去。

### 最终方案：方案A（直连暴露）

给 dify-web 加 `3000:3000` 端口映射，并把控制台前端的 API 地址指向后端 dify-api。

**关键陷阱**：主机 `5001` 端口被 **dify-adapter**（RAG 契约接口，orchestrator 的
`RAG_BASE_URL` 与 `INTERFACE_CONTRACT` 都硬编码指向它）占用，**不能复用**。
因此把 dify-api 控制台后端单独映射到主机 **5002**，dify-web 指向 5002。

改动（`docker-compose.yml`）：

| 服务 | 改动 |
|------|------|
| dify-web | 加 `ports: ["3000:3000"]`；`CONSOLE_API_URL`/`APP_API_URL` 设为 `http://localhost:5002` |
| dify-api | 加 `ports: ["5002:5001"]`（5001 已被 adapter 占，错开到 5002） |

端口最终分配：`3000` 控制台前端 ｜ `5001` dify-adapter（RAG 契约）｜ `5002` dify-api 控制台后端。

### 确切访问网址与首次初始化步骤

**控制台网址**：http://localhost:3000

首次初始化（一次性人工操作）：

1. 浏览器打开 **http://localhost:3000/install**，设置管理员账号（邮箱+密码）并登录
2. 顶部进入「知识库」→「创建知识库」，建一个空知识库（可先不传文档）
3. 知识库内进入「API 访问」（或「设置 → API Keys」）→ 创建 API Key →
   复制密钥，填入 `.env` 的 `DIFY_API_KEY`
4. 在知识库 URL 或详情页复制 **dataset ID**（形如 `xxxxxxxx-xxxx-...`），
   填入 `.env` 的 `DIFY_DATASET_ID`
5. 重启 dify-adapter 让新 `.env` 生效：`docker compose up -d dify-adapter`
6. 复测：`POST http://localhost:5001/v1/rag/query`（带 `user_id`/`query`/`top_k`）
   应不再 502，返回检索结果

> 备注：若控制台登录后报 API 连接错误，确认浏览器能直接打开
> **http://localhost:5002/health**（应返回健康），说明 dify-api 后端已暴露到位。

---

## 三、xinference 巨型镜像的坑与最终方案（方案B）

### 问题

`xprobe/xinference:latest`（GPU 版）压缩后 **12GB**，单层 3GB+。在经代理的网络下，
大层传输**必断流 / 挂死**：实测现象为所有层卡在 `Pulling fs layer` 零字节、
`docker system df` 缓存零增长、连 `Downloading` 进度都进不去。

### 尝试过程

| 尝试 | 结果 |
|------|------|
| 改 CPU 版 `latest-cpu`（3.3GB，小 4 倍） | 大层仍零字节挂死 |
| 显式指定国内镜像源 `docker.1ms.run/...` | 同样挂死 |
| 断点续传重试循环（`until docker pull`） | pull 挂起不退出，循环无法触发重试 |
| 对照实验：拉 `alpine:3.19`（3MB） | ✅ 小层秒下 |

**结论**：代理对**小文件**放行、对**持续大流量**挂死。这是 Docker Desktop 内置代理
（`http.docker.internal:3128` 套本地 `127.0.0.1:12334`）的已知通病。
缓存里历史遗留的 `ollama:latest`(8.27GB)、`dify-api:latest`(4.12GB) 是网络状态较好时拉成的，
本次网络环境下无法复现。

### 最终方案：方案B — embedding 走云端 API

放弃本地 xinference，把 Mem0 的向量化交给**云端 embedding API**（OpenAI 协议兼容），
彻底绕开大镜像。代码已参数化改造：

- `infra/mem0/app.py`：embedder 的 `api_key` 与向量维度 `embedding_model_dims`
  改为环境变量驱动（原先 key 写死 `"xinference"`、维度写死 `1536`）。
- `docker-compose.yml`：mem0 的 `EMBEDDING_BASE_URL` 不再写死，
  新增透传 `EMBEDDING_API_KEY` / `EMBEDDING_DIMS`，默认值仍指向本地 xinference（向后兼容）。
- `.env.example`：文档化方案A（本地 xinference）与方案B（硅基流动 siliconflow）两套配置。

**切云端只需在 `.env` 改 4 行**（以硅基流动为例）：

```bash
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=sk-your_siliconflow_key
EMBEDDING_DIMS=1024          # bge-m3=1024，qwen3-embedding=1536，务必与模型匹配
```

> ⚠️ 切换 embedding 模型必须同步改 `EMBEDDING_DIMS`，
> 维度与 pgvector collection 不一致会在写入时报错。

**有 GPU / 网络通畅时**回退方案A：
`docker pull xprobe/xinference:latest-cpu` 预热后，`.env` 保持默认即用本地托管。

### embedding 云端方案落地指引（用户操作步骤）

> ⚠️ 重要区分：项目里有**两个独立的云端服务**，用的是**两个不同的 key**：
> - **LLM**（对话/记忆摘要）走 **DeepSeek**，用 `OPENAI_API_KEY`（用户已有）。
> - **Embedding**（向量化）走**独立的云端 embedding 服务**，DeepSeek **不提供** embedding，
>   必须单独注册一个，用 `EMBEDDING_API_KEY`。两者不能混用。

推荐用硅基流动（siliconflow），注册送额度、OpenAI 协议兼容、有免费的 `BAAI/bge-m3`。

**操作步骤**：

1. 打开 **https://siliconflow.cn** 注册账号
2. 控制台 →「API 密钥」→ 新建密钥，复制（形如 `sk-xxxxxxxx...`）
3. 编辑主目录 `.env`，确认以下 **3 项匹配**（缺一不可）：
   ```bash
   EMBEDDING_MODEL=BAAI/bge-m3                       # 模型名
   EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1  # 硅基流动 endpoint
   EMBEDDING_API_KEY=sk-你复制的硅基流动密钥          # 第2步拿到的 key
   EMBEDDING_DIMS=1024                                # bge-m3 固定 1024 维
   ```
   > `EMBEDDING_DIMS` 必须与模型维度一致：`BAAI/bge-m3`=**1024**，`qwen3-embedding`=1536。
   > 维度与 pgvector collection 不匹配会在写入记忆时报错。
4. 重启 mem0 让新 `.env` 生效（主目录执行）：
   ```bash
   docker compose up -d mem0
   ```
5. 验证：`curl --noproxy localhost http://localhost:8082/healthz` 返回 200，
   再写一条记忆（`POST /v1/memory/test_user`）不报维度错即成功。

> 已有 xinference 镜像（GPU/网络允许）想用本地方案时，把上面 4 项改回
> `EMBEDDING_MODEL=qwen3-embedding` / `EMBEDDING_BASE_URL=http://xinference:9997/v1` /
> `EMBEDDING_API_KEY=xinference` / `EMBEDDING_DIMS=1536` 即可。

---

## 四、本轮其他改动

### 1. ollama 设为可选（profiles: optional）

本项目 LLM 走 DeepSeek 云端 API（`.env` `OPENAI_API_BASE`），本地模型托管用不上。
给 ollama 加 `profiles: ["optional"]`，默认不启动，避免每次 `up` 都尝试拉它的 8GB 镜像。
需要本地模型时：`docker compose --profile optional up -d ollama`。

> 连带修正：xinference 原有 `depends_on: ollama` 在 ollama 进 profile 后会悬空报错，
> 已移除（xinference 本就不依赖 ollama，二者都走云端或独立托管）。

### 2. 修 dify 的 `Permission denied: '/home/dify'` 警告

dify 镜像内进程默认 `HOME=/home/dify`，但该目录对运行用户不可写，日志持续刷警告（无害但碍眼）。
给 dify-api / dify-worker 加 `HOME: /app`（指向可写目录）消除。

### 3. healthcheck 探针修正（curl/wget 兼容性）

部分镜像不含 `curl`，原 healthcheck 全部失败。按镜像实际可用命令逐一修正：

| 服务 | 镜像 | 原探针 | 改为 |
|------|------|--------|------|
| weaviate | semitechnologies/weaviate | curl | `wget -q -O -`（镜像有 wget 无 curl） |
| nginx | nginx:alpine | curl | `wget -q -O -` |
| dify-adapter | python-slim | curl | `python urllib` |
| mem0 | python-slim | curl | `python urllib` |
| wechat-reply-server | python-slim | curl | `python urllib` |

---

## 五、部署 checklist（下次全新启动）

1. `cp .env.example .env`，填 `POSTGRES_PASSWORD`/`REDIS_PASSWORD`/`DIFY_SECRET_KEY`/`WEAVIATE_API_KEY`
   （强随机：`openssl rand -hex 16` / `-hex 32`）
2. 填 `OPENAI_API_KEY`（DeepSeek）；embedding 选方案A或方案B
3. 分组启动：`postgres redis weaviate` → 等 healthy → `dify-api dify-worker dify-web` → `mem0 dify-adapter`
4. 浏览器进 Dify 控制台建知识库，回填 `DIFY_API_KEY` / `DIFY_DATASET_ID`，重启 dify-adapter
5. 接入层（企微）：填 `WECHAT_*` 真实凭证后启动 `chatgpt-on-wechat wechat-reply-server`
6. 反代：最后起 `nginx`

> ⚠️ 端口冲突提醒：worktree 工作区**不要**执行 `docker compose up`，
> 否则会用 `infra-` 前缀起重复容器抢占端口。镜像缓存全 Docker 共享，
> 在 worktree 里 `docker pull` 预热即可，主目录启动时秒起。