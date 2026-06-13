# 接口契约（INTERFACE CONTRACT）

> 三个窗口并行开发的"分界线"。任何窗口都不得擅自修改本文件中已约定的接口；
> 如需变更，先在此文件登记并通知其他窗口。这是并行开发不冲突的关键。

---

## 模块划分与目录归属

| 模块 | 负责窗口 | 目录（唯一归属，其他窗口不碰） |
|------|---------|------------------------------|
| 编排核心 | 窗口1 | `orchestrator/` |
| 基础设施 | 窗口2 | `infra/`、`docker-compose.yml`、`.env.example` |
| 能力工具 | 窗口3 | `mcp-servers/`、`tools/` |
| 共享契约 | 全体只读 | `INTERFACE_CONTRACT.md`、`shared/` |

**铁律：每个窗口只在自己的目录内写文件。跨目录只通过下面约定的接口通信。**

---

## 接口一：编排核心 → 基础设施

### 1.1 知识库检索（窗口1 调用 窗口2）
```
POST http://localhost:5001/v1/rag/query
Req:  { "user_id": str, "query": str, "mode": "simple"|"agentic", "top_k": int }
Resp: { "context": str, "sources": [{"title": str, "score": float}] }
```

### 1.2 记忆读写（窗口1 调用 窗口2 的 Mem0）
```
GET  http://localhost:8082/v1/memory/{user_id}
Resp: { "profile": {...}, "mistakes": [...], "history": [...] }

POST http://localhost:8082/v1/memory/{user_id}
Req:  { "type": "mistake"|"profile"|"history", "data": {...} }
```

### 1.3 渠道回复（窗口2 入口 → 窗口1 → 窗口2 发送）
```
窗口2 收到企微消息后，转成标准消息 POST 给编排核心：
POST http://localhost:8081/v1/message
Req:  { "channel": str, "user_id": str, "msg_type": "text"|"image"|"file",
        "content": str, "media_url": str|null }
Resp: { "status": "accepted" }   # 立即返回，异步处理

编排核心处理完后，回调窗口2 发送结果：
POST http://localhost:8080/v1/reply
Req:  { "user_id": str, "content_type": "text"|"file", "content": str, "file_url": str|null }
```

---

## 接口二：编排核心 → 能力工具（MCP）

窗口3 的所有工具以 **MCP 协议**暴露，窗口1 作为 MCP Client 调用。

### 2.1 MCP Server 注册表（窗口3 维护，窗口1 读取）
```
shared/mcp_registry.json
[
  { "name": "office-word", "transport": "sse", "url": "http://localhost:9001/sse" },
  { "name": "presenton",   "transport": "sse", "url": "http://localhost:9002/sse" },
  { "name": "paddleocr",   "transport": "sse", "url": "http://localhost:9003/sse" },
  { "name": "filesystem",  "transport": "stdio", "command": "..." }
]
```

### 2.2 工具调用约定
- 每个 MCP 工具的输入/输出 schema 由窗口3 在各 server 内定义，并在 `shared/tool_schemas/` 下导出 JSON Schema 供窗口1 参考。
- 文件类输出统一返回可下载 URL（存到 `shared/outputs/`，通过 `http://localhost:8090/files/{name}` 访问）。

---

## 接口三：共享数据约定

### 3.1 标准消息结构（shared/schemas.py，全体只读）
```python
StandardMessage = {
    "channel": str, "user_id": str, "msg_type": str,
    "content": str, "media_url": str | None, "timestamp": int
}
```

### 3.2 用户ID规范
```
格式：family_{姓名拼音}   例：family_xiaoming
所有模块统一使用，作为记忆/数据隔离键
```

### 3.3 端口分配（避免冲突）
```
8080  chatgpt-on-wechat（窗口2）
8081  langgraph编排（窗口1）
8082  mem0（窗口2）
8090  文件服务（窗口3）
5001  dify/ragflow知识库（窗口2）
9001+ MCP servers（窗口3）
9997  xinference（窗口2）
11434 ollama（窗口2）
5432  postgresql（共享，窗口2起）
6379  redis（共享，窗口2起）
```

---

## 集成测试约定

合流时按此顺序验证：
1. 窗口2 单独验证：企微 → Dify 回复
2. 窗口3 单独验证：MCP 工具能被 MCP Inspector 调用
3. 窗口1 单独验证：mock 接口下编排流程跑通
4. 三方合流：企微发指令 → 编排 → 调用工具/知识库 → 回复
