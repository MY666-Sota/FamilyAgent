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

---

## A7 联调发现（2026-06-17）

> 三窗口真实联调暴露的契约偏差。窗口1 已在 `orchestrator/` 内做了协议层适配与优雅降级，
> 窗口3 已确认工具签名并导出 schema，以下为最终对齐结果。

### F1. MCP transport 是标准 SSE，非裸 JSON-RPC POST（窗口1 已适配）
- **现象**：§2.2 未明确 transport 细节。实测窗口3 用标准 MCP SSE transport：
  `GET /sse` 建连 → 服务端回 `endpoint` 事件给出 `/messages/?session_id=xxx` →
  POST JSON-RPC 到该 endpoint → 结果经 SSE 流回。直接 `POST /sse` 返回 `405`。
- **处置**：窗口1 已改用官方 `mcp` SDK（`sse_client` + `ClientSession`）完成握手，
  见 `orchestrator/mcp_client.py`。**无需其他窗口改动**，仅登记澄清协议。

### F2：工具签名不一致（已对齐）

| MCP server | 编排核心调用（旧） | 窗口3 实际工具签名 | 说明 |
|---|---|---|---|
| presenton 9002 | `generate_ppt(topic, user_id)` | `generate_ppt(filename*, topic*, outline[]*, style?, language?)` | 无 `user_id`；必须提供 `outline[]`；`filename` 必填 |
| office-word 9001 | `generate_document(topic, user_id)` | `create_document(filename*, content*, title?, author?)` | 工具名不同；无 `topic`/`user_id`；`content` 是已生成文本，非主题 |
| paddleocr 9003 | `ocr_and_grade(media_url, user_id, grade)` | `ocr_image(image_url?, image_path?, language?, return_layout?)` 和 `ocr_image_structured(image_url?, image_path?, subject?)` | 工具名不同；无批改逻辑；`grade` 不是参数 |

**权威 schema 在 `shared/tool_schemas/`（office-word.json / presenton.json / paddleocr.json），字段名/类型/required 与窗口3 server 实际定义完全一致。窗口1 请据此修改 agents.py。**

窗口3确认（2026-06-17）：已导出 schema，工具签名以 shared/tool_schemas/ 为准。

### F3：paddleocr 分工确认

paddleocr-mcp 的 `ocr_image` / `ocr_image_structured` 只做文字提取（OCR），
不含批改逻辑。批改判分由窗口1 编排核心的 LLM 处理。

窗口3确认（2026-06-17）：预期分工正确，ocr_image/ocr_image_structured 只做文字提取，批改由编排核心 LLM 处理。

### F4. Mem0 写入 type 枚举校验严格（窗口2 已确认）
- §1.2 约定 `type: "mistake"|"profile"|"history"`。实测 8082 **严格校验**：传其他值
  （如 `preference`）返回 `400 {"detail":"type must be mistake|profile|history"}`。
- **处置**：编排核心 `memory_post` 需保证只用这三个枚举值。已确认非法值会被优雅降级
  捕获不崩。登记提醒：OpenAPI schema 只标了 `type: string` 未暴露枚举，建议窗口2 在
  schema 中补 enum 约束便于对齐。

### F5. Mem0 写入依赖 embedding（窗口2 已修复）
- 实测 `POST /v1/memory/{user_id}`（合法 type）返回 `500`，根因是上游 embedding 服务
  `401 Authentication Fails (api key ****e95d invalid)`——即 `EMBEDDING_API_KEY` 未配。
- **解法**：在 `.env` 填入真实的硅基流动 key（`EMBEDDING_API_KEY`），重启 mem0。
  读路径（GET）正常，新用户返回 `{"profile":{},"mistakes":[],"history":[]}`。
  编排核心 `save_memory` 已优雅降级（写失败不阻断主流程），配好 key 后写入自动恢复。

### F6：office-word create_document 上游连接失败（窗口3 已修复）

**根因**：office-word-mcp/server.py 原实现通过 `httpx` 代理转发到 `http://localhost:9011`（GongRzhe/Office-Word-MCP-Server），但该外部服务未部署，故所有连接均失败。

**修复**（2026-06-17，窗口3）：
- 删除对 9011 的 HTTP 调用，改用本地 `python-docx` 直接读写 .docx 文件。
- `create_document`、`read_document`、`append_to_document` 现在无外部依赖，直接在 `shared/outputs/` 操作文件。
- `list_documents` 扫描 `shared/outputs/*.docx`，不变。
- 新增 `python-docx>=1.1.2` 到 `mcp-servers/requirements.txt`。
- 验证：MCP client 调 `create_document` 写出 36 KB .docx，`http://localhost:8090/files/{name}` HTTP 200 下载，read/append 全链路通过。
