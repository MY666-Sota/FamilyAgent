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

## A7 联调发现（2026-06-16，窗口1 登记，待相关窗口确认）

> 真实联调（Mem0 8082 / MCP 9001-9003 在线）暴露的契约偏差。窗口1 已在 `orchestrator/`
> 内做了协议层适配与优雅降级，但**工具名/参数/枚举等契约层差异需窗口2/3 确认**。
> 在统一前，编排核心对这些调用一律优雅降级到 mock，不会崩溃。

### F1. MCP transport 是标准 SSE，非裸 JSON-RPC POST（已由窗口1 适配）
- **现象**：§2.2 未明确 transport 细节。实测窗口3 用标准 MCP SSE transport：
  `GET /sse` 建连 → 服务端回 `endpoint` 事件给出 `/messages/?session_id=xxx` →
  POST JSON-RPC 到该 endpoint → 结果经 SSE 流回。直接 `POST /sse` 返回 `405`。
- **处置**：窗口1 已改用官方 `mcp` SDK（`sse_client` + `ClientSession`）完成握手，
  见 `orchestrator/mcp_client.py`。**无需其他窗口改动**，仅登记澄清协议。

### F2. MCP 工具名与参数与编排核心假设不一致（待窗口3 确认）
编排核心 `nodes/agents.py` 当前按以下假设构造调用，与窗口3 实际暴露的工具签名不符：

| 用途 | 编排核心当前调用 | 窗口3 实际工具签名（实测） |
|------|----------------|--------------------------|
| 做PPT (presenton 9002) | `generate_ppt(topic, user_id)` | `generate_ppt(filename*, topic*, outline[]*, style?, language?)` |
| Word (office-word 9001) | `generate_document(topic, user_id)` | `create_document(filename*, content*, title?, author?)` |
| 作业批改 (paddleocr 9003) | `ocr_and_grade(media_url, user_id, grade)` | `ocr_image(image_url, language?)` / `ocr_image_structured(image_url, subject?)` |

- **关键差异**：①工具名不同（`generate_document`→`create_document`，`ocr_and_grade`→`ocr_image*`）；
  ②`user_id` 不是工具参数（编排核心应自己持有，不传给工具）；
  ③presenton 需要 `outline` 数组与 `filename`，编排核心需先用 LLM 生成大纲再调；
  ④office-word 无"按 topic 生成"语义，只接受现成 `content`，需编排核心先产出正文。
- **建议**：请窗口3 在 `shared/tool_schemas/` 导出各工具 JSON Schema（§2.2 已约定但尚未见文件）。
  窗口1 据此改造 `agents.py` 的参数构造（属窗口1 目录内工作，待 schema 确认后进行）。

### F3. paddleocr 只做 OCR，不含"批改"语义（待窗口3/产品确认）
- 编排核心期望 `ocr_and_grade` 直接返回批改结果（对错、错题列表）。实际 9003 只提供
  `ocr_image`（出文字）与 `ocr_image_structured`（出结构化文字）。**批改逻辑需编排核心
  侧用 LLM 完成**（OCR 取文字 → LLM 判对错）。请确认这是预期分工。

### F4. Mem0 写入 type 枚举校验严格（待窗口2 确认）
- §1.2 约定 `type: "mistake"|"profile"|"history"`。实测 8082 **严格校验**：传其他值
  （如 `preference`）返回 `400 {"detail":"type must be mistake|profile|history"}`。
- **处置**：编排核心 `memory_post` 需保证只用这三个枚举值。已确认非法值会被优雅降级
  捕获不崩。登记提醒：OpenAPI schema 只标了 `type: string` 未暴露枚举，建议窗口2 在
  schema 中补 enum 约束便于对齐。

### F5. Mem0 写入依赖 embedding，当前 401 阻塞（窗口2 已知阻塞）
- 实测 `POST /v1/memory/{user_id}`（合法 type）返回 `500`，根因是上游 embedding 服务
  `401 Authentication Fails (api key ****e95d invalid)`——即 xinference/embedding 未就绪或
  key 未配。**读路径（GET）正常**，新用户返回 `{"profile":{},"mistakes":[],"history":[]}`。
- **影响**：记忆写入暂不可用。编排核心 `save_memory` 已优雅降级（写失败不阻断主流程），
  待窗口2 配好 embedding 后写入自动恢复，无需窗口1 改动。

### F6. office-word create_document 上游连接失败（待窗口3 确认）
- 实测 `create_document` 返回工具级错误 `isError=True: "All connection attempts failed"`，
  疑似 office-word server 的上游依赖（文件存储/转换）未就绪。`list_documents`/`list_ppts`
  等只读工具正常。请窗口3 确认 9001 的写入依赖是否已部署。

