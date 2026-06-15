# MCP 工具层（窗口3）

负责将能力组件封装为 MCP 协议工具，供编排核心（窗口1）调用。
详见根目录 INTERFACE_CONTRACT.md 接口二。

## 架构概览

```
编排核心（窗口1）
    ↓ MCP 协议
MCP 工具层（窗口3）
    ├── office-word-mcp    (9001 SSE)  → Office-Word-MCP-Server 代理
    ├── presenton-mcp      (9002 SSE)  → Presenton HTTP API 封装
    ├── paddleocr-mcp      (9003 SSE)  → PaddleOCR-VL HTTP 桥接
    └── filesystem-mcp     (stdio)     → 本地文件读写（限定 shared/outputs/）
    ↓ 文件落地
File Server (8090) → http://localhost:8090/files/{name}
    ↓ 静态文件服务
shared/outputs/
```

## 工具状态表

> 最近实测：2026-06-15（本地组件全部通过；上游依赖服务待窗口2 Docker 部署后联调）

| MCP Server | 端口 | 传输 | 工具数 | 上游服务 | 状态 | 测试日期 |
|-----------|------|------|--------|----------|------|----------|
| office-word-mcp | 9001 | SSE | 4 | Office-Word-MCP-Server (9011) | 🟡 骨架就绪/待上游 | 2026-06-15 |
| presenton-mcp | 9002 | SSE | 3 | Presenton (7860) | 🟡 骨架就绪/待上游 | 2026-06-15 |
| paddleocr-mcp | 9003 | SSE | 2 | PaddleOCR-VL (8868) | 🟡 骨架就绪/待上游 | 2026-06-15 |
| filesystem-mcp | — | stdio | 5 | 本地文件系统 | ✅ 已实测 | 2026-06-15 |
| file-server | 8090 | HTTP | — | — | ✅ 已实测 | 2026-06-15 |

**状态说明**：
- ✅ **已实测**：功能完整，端到端验证通过（含异常路径）
- 🟡 **骨架就绪/待上游**：MCP 层启动正常、工具列表与 schema 一致、能连接调用、上游错误能优雅返回；真实功能需窗口2 部署上游服务后联调
- ⚠️ **待上游**：依赖的服务尚未部署
- ❌ **已阻断**：遇到阻塞性问题

### 实测结论（2026-06-15）

**✅ 已通过（本地，无上游依赖）**

| 验证项 | 结果 |
|--------|------|
| 5 个组件工具列表与 `mcp_registry.json` 一致 | 14 个工具全部匹配，无缺失/多余 |
| 只读 smoke call（list_documents / list_ppts / list_files / file_exists） | 全部成功 |
| filesystem-mcp 读写删闭环（含中文、覆盖保护、路径越界防护） | 11/11 通过 |
| file-server 下载闭环（写入→列表→HTTP 下载→内容校验→目录穿越防护） | 全部通过 |
| 文件 URL 格式 `http://localhost:8090/files/{name}` | 符合契约 §2.2 |

**🟡 待上游联调（依赖窗口2 Docker 服务）**

| MCP Server | 上游服务 | 阻塞原因 | 已验证 |
|-----------|----------|----------|--------|
| paddleocr-mcp | PaddleOCR-VL (8868) | Docker 未运行，8868 无监听 | 工具可调用，上游连不上时优雅返回 `isError=True` |
| presenton-mcp | Presenton (7860) | Docker 未运行，7860 无监听 | 同上 |
| office-word-mcp | Office-Word-MCP-Server (9011) | 窗口2 尚未部署此服务 | 工具列表/schema 就绪 |

**联调前置条件**：窗口2 执行 `docker-compose up -d paddleocr presenton`，并补充部署 Office-Word-MCP-Server（9011）。届时运行 `python tools/test/integration_test.py` 完成端到端验证。

### 本轮修复的问题

1. **测试脚本在 Windows 控制台崩溃**：`✓`/`✗` 等 Unicode 字符在 GBK 控制台报 `UnicodeEncodeError`。已在测试脚本入口强制 `stdout/stderr` 为 UTF-8。
2. **file-server 死代码**：`StaticFiles` 挂载与自定义 `/files/{path}` 路由路径冲突，后者永不执行。已删除死代码，统一由 `StaticFiles` 处理下载（自带 Range 请求与目录穿越防护）。
3. **httpx 走系统代理导致 localhost 调用失败**（联调关键）：httpx 默认 `trust_env=True` 会读取 Windows 系统代理，把 `localhost` 上游请求转给代理，导致超时/502。已为全部 6 处上游调用加 `trust_env=False`，确保本地服务间直连。

## 快速开始

### 1. 安装依赖
```bash
pip install -r mcp-servers/requirements.txt
```

### 2. 启动窗口2服务（在其他终端）
```bash
cd ../infra
docker-compose up -d paddleocr presenton
```

### 3. 启动 MCP 工具层
```bash
# 终端 1: file-server
python tools/file-server/server.py

# 终端 2: presenton-mcp
python mcp-servers/presenton-mcp/server.py

# 终端 3: paddleocr-mcp
python mcp-servers/paddleocr-mcp/server.py
```

或使用一键启动脚本：
```bash
bash start_all.sh
```

### 4. 测试工具连接
```bash
# 基础功能测试（只验证工具列表）
python tools/test/test_mcp.py --quick

# 完整集成测试（验证端到端功能）
python tools/test/integration_test.py
```

## 工具详情

### office-word-mcp (端口 9001)
代理 GongRzhe/Office-Word-MCP-Server，提供 Word 文档操作。

**工具**：
- `create_document(filename, content, title?, author?)` → 创建 .docx
- `read_document(filename)` → 读取文档文本
- `list_documents()` → 列出所有 .docx 文件
- `append_to_document(filename, content)` → 追加内容

**输出**：
- 文件保存到 `shared/outputs/`
- 返回可下载 URL：`http://localhost:8090/files/{filename}`

### presenton-mcp (端口 9002)
封装 Presenton HTTP API，提供 PPT 生成功能。

**工具**：
- `generate_ppt(filename, topic, outline, style?, language?)` → 生成 PPT
- `generate_ppt_from_markdown(filename, markdown, style?)` → Markdown 转 PPT
- `list_ppts()` → 列出所有 .pptx 文件

**输出**：
- 文件保存到 `shared/outputs/`
- 返回可下载 URL 和幻灯片数量

### paddleocr-mcp (端口 9003)
桥接 PaddleOCR-VL 服务，提供图片 OCR 识别。

**工具**：
- `ocr_image(image_path?, image_url?, language?, return_layout?)` → 图片 OCR
- `ocr_image_structured(image_path?, image_url?, subject?)` → 作业图片结构化识别

**输出**：
- `text`: 全文拼接
- `lines`: 按行分割的文本
- `layout`: 布局框（仅 `return_layout=True` 时返回）
- `questions`: 结构化题目列表（仅 `ocr_image_structured` 返回）

### filesystem-mcp (stdio)
本地文件读写工具，根路径锁定为 `shared/outputs/`。

**工具**：
- `list_files(directory?)` → 列出文件
- `read_file(path)` → 读取文本文件
- `write_file(path, content, overwrite?)` → 写入文本文件
- `delete_file(path)` → 删除文件
- `file_exists(path)` → 检查文件是否存在

**安全特性**：
- 路径锁定到 `shared/outputs/`
- 防目录穿越攻击
- 需显式 `overwrite=True` 覆盖已有文件

### file-server (端口 8090)
FastAPI 静态文件服务，挂载 `shared/outputs/` 目录。

**端点**：
- `GET /health` → 健康检查
- `GET /list` → 列出所有文件
- `GET /files/{path}` → 下载文件

**安全特性**：
- 防目录穿越攻击
- 仅限 GET 请求（写入需通过 MCP 工具）

## MCP 注册表

窗口1 通过读取 `shared/mcp_registry.json` 发现可用的 MCP server：

```json
[
  {
    "name": "office-word",
    "transport": "sse",
    "url": "http://localhost:9001/sse",
    "description": "Word 文档生成与编辑",
    "tools": ["create_document", "read_document", "list_documents", "append_to_document"]
  },
  {
    "name": "presenton",
    "transport": "sse",
    "url": "http://localhost:9002/sse",
    "description": "PPT 生成",
    "tools": ["generate_ppt", "generate_ppt_from_markdown", "list_ppts"]
  },
  {
    "name": "paddleocr",
    "transport": "sse",
    "url": "http://localhost:9003/sse",
    "description": "图片 OCR 识别",
    "tools": ["ocr_image", "ocr_image_structured"]
  },
  {
    "name": "filesystem",
    "transport": "stdio",
    "command": "python tools/filesystem-mcp/server.py",
    "description": "本地文件读写",
    "tools": ["list_files", "read_file", "write_file", "delete_file", "file_exists"]
  }
]
```

## 工具 Schema

每个工具的输入/输出 JSON Schema 定义在 `shared/tool_schemas/` 目录：

- `office-word.json` — Word 文档工具
- `presenton.json` — PPT 生成工具
- `paddleocr.json` — OCR 识别工具
- `filesystem.json` — 文件系统工具

窗口1 可参考这些 schema 进行类型检查和参数校验。

## 端口配置与窗口2对齐

| 服务 | 窗口2 端口 | 环境变量 | 状态 |
|------|-----------|---------|------|
| PaddleOCR | 8868 | `PADDLEOCR_BASE` | ✅ 一致 |
| Presenton | 7860 | `PRESENTON_BASE` | ✅ 已修正 |
| Office-Word-MCP-Server | 9011 | `OFFICE_WORD_MCP_BASE` | ⚠️ 窗口2待部署 |
| File Server | 8090 | `FILE_SERVER_PORT` | ✅ 独立服务 |

**修正记录**：
- 2026-06-14: presenton-mcp 端口从 7001 改为 7860（与 docker-compose 一致）

## 测试

### 基础功能测试
```bash
python tools/test/test_mcp.py --quick
```
验证各 MCP server 能启动，工具列表与 schema 一致。

### 完整集成测试
```bash
python tools/test/integration_test.py
```
验证与窗口2服务的联通性、端到端功能、文件落地和 URL 可访问性。

**测试用例**：
- File Server 健康检查和文件列表
- PaddleOCR-VL 图片识别（测试图片自动生成）
- Presenton PPT 生成
- 文件落地到 `shared/outputs/`
- 文件 URL 可访问

**详细测试计划**：见 `tools/test/TEST_PLAN.md`

## 常见问题

### 1. MCP server 启动失败
检查端口是否被占用：
```bash
netstat -ano | findstr <port>
```

### 2. 无法连接窗口2服务
确保窗口2服务已启动：
```bash
cd ../infra
docker-compose ps
```

### 3. 文件未落到 shared/outputs/
检查 `shared/outputs/` 目录权限和环境变量。

### 4. Office-Word-MCP-Server 连接失败
该服务由窗口2部署，等待窗口2完成后再测试。

## 开发规范

### 代码风格
- Python 3.11+
- 使用 `mcp[cli]` 官方 SDK
- SSE server 使用 `FastMCP` 类
- 所有工具都有完整 docstring

### 文件输出
- 统一保存到 `shared/outputs/`
- 返回 URL 格式：`http://localhost:8090/files/{name}`
- 通过 file-server 提供静态文件服务

### 安全考虑
- filesystem-mcp 根路径锁定到 `shared/outputs/`
- 防目录穿越攻击
- 需显式确认才能覆盖已有文件

## 依赖关系

```
MCP 工具层（本目录）
    ↓ 依赖
窗口2（infra/）
    ├── PaddleOCR-VL (8868)
    ├── Presenton (7860)
    └── Office-Word-MCP-Server (9011)
```

## 更新日志

### 2026-06-15
- ✅ 本地组件实测全部通过（filesystem-mcp 11/11、file-server 下载闭环、5 组件工具列表一致）
- 🐛 修复测试脚本在 Windows GBK 控制台的 `UnicodeEncodeError`（强制 UTF-8 输出）
- 🐛 删除 file-server 死代码（`StaticFiles` 与自定义路由冲突），统一由 `StaticFiles` 处理下载
- 🐛 修复 httpx 走系统代理导致 localhost 上游调用失败（6 处加 `trust_env=False`，联调关键）
- ➕ 新增 `tools/test/test_filesystem.py` 读写删闭环测试
- 🟡 上游三项（PaddleOCR/Presenton/Office-Word）确认阻塞，待窗口2 Docker 部署后联调

### 2026-06-14
- ✅ 完成 MCP 工具层骨架
- ✅ 修正 Presenton 端口（7001 → 7860）
- ✅ 添加集成测试脚本
- ✅ 添加详细测试计划
- 🔶 待执行集成测试
- 🔶 待上游部署 Office-Word-MCP-Server

### 2026-06-13
- ✅ 初始提交（commit a768fee）
- ✅ 实现 4 个 MCP server
- ✅ 实现 file-server
- ✅ 完成 tool_schemas
- ✅ 完成 mcp_registry.json

## 贡献

本目录由窗口3负责，仅修改 `mcp-servers/`、`tools/` 和 `shared/tool_schemas/`。
跨目录修改需先在 INTERFACE_CONTRACT.md 登记。