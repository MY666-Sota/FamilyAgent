# MCP 工具层实测计划

## 1. 端口配置对齐

| 服务 | 窗口2 docker-compose | mcp_servers 代码 | 状态 |
|------|---------------------|----------------|------|
| PaddleOCR | 8868 | 8868 | ✅ 一致 |
| Presenton | 7860 | 7860 | ✅ 已修正 |
| File Server | — | 8090 | ✅ 独立服务 |
| Office-Word-MCP-Server | 未配置 | 9011（待定） | ⚠️  窗口2待部署 |

**修正记录**：
- 2026-06-14: presenton-mcp/server.py 端口从 7001 改为 7860（与 docker-compose 一致）

## 2. 测试前准备

### 2.1 依赖安装
```bash
pip install "mcp[cli]==1.9.4" httpx fastapi "uvicorn[standard]" Pillow
```

### 2.2 启动窗口2服务
```bash
cd .worktrees/infra
docker-compose up -d paddleocr presenton
```

### 2.3 启动 MCP 工具层
```bash
# 终端 1: file-server
python tools/file-server/server.py

# 终端 2: presenton-mcp
python mcp-servers/presenton-mcp/server.py

# 终端 3: paddleocr-mcp
python mcp-servers/paddleocr-mcp/server.py
```

或使用一键启动脚本（端口对齐后）：
```bash
bash start_all.sh
```

## 3. 测试用例

### 3.1 PaddleOCR-VL 联通测试
- **目标**：验证 `paddleocr-mcp` 能调用窗口2的 PaddleOCR 服务（8868）
- **方法**：
  1. 生成测试图片（包含文字 "1+1=" "2+2="）
  2. 调用 `ocr_image` 工具识别
  3. 验证返回的 `text` 字段包含测试文字
- **预期结果**：
  - HTTP 服务可达
  - MCP 工具调用成功
  - 识别结果包含测试文字
  - `return_layout=True` 时返回布局框

### 3.2 Presenton 联通测试
- **目标**：验证 `presenton-mcp` 能调用窗口2的 Presenton 服务（7860）
- **方法**：
  1. 调用 `generate_ppt` 生成测试 PPT
  2. 验证文件落到 `shared/outputs/`
  3. 验证返回的 `file_url` 格式正确（`http://localhost:8090/files/{name}`）
  4. 通过 file-server 下载文件验证完整性
- **预期结果**：
  - Presenton 服务可达
  - MCP 工具调用成功
  - `.pptx` 文件落地到 `shared/outputs/`
  - 文件 URL 可访问
  - 下载文件大小 > 0

### 3.3 File Server 测试
- **目标**：验证 `file-server` 提供静态文件服务
- **方法**：
  1. 调用 `GET /health` 验证服务启动
  2. 调用 `GET /list` 验证文件列表功能
  3. 上传测试文件到 `shared/outputs/`
  4. 通过 `GET /files/{name}` 下载验证
- **预期结果**：
  - 健康检查正常
  - 文件列表正确
  - 文件可下载

### 3.4 Filesystem MCP 测试
- **目标**：验证 `filesystem-mcp` (stdio) 功能
- **方法**：
  1. 调用 `list_files` 列出根目录
  2. 调用 `write_file` 写入测试文件
  3. 调用 `read_file` 读取验证
  4. 调用 `delete_file` 删除测试文件
- **预期结果**：
  - 文件列表正确
  - 文件读写成功
  - 删除操作成功
  - 根路径锁定到 `shared/outputs/`

### 3.5 Office-Word-MCP 测试（待窗口2部署后）
- **目标**：验证 `office-word-mcp` 能代理 Office-Word-MCP-Server
- **方法**：
  1. 调用 `create_document` 生成测试 `.docx`
  2. 验证文件落地和 URL 可访问
  3. 调用 `read_document` 读取内容
- **预期结果**：
  - 上游服务可达
  - 文件生成成功
  - 内容读取正确

## 4. 测试脚本

### 4.1 基础功能测试
```bash
python tools/test/test_mcp.py --quick
```
- 验证各 MCP server 能启动
- 验证工具列表与 schema 一致

### 4.2 完整集成测试
```bash
python tools/test/integration_test.py
```
- 验证与窗口2服务的联通性
- 验证端到端功能
- 验证文件落地和 URL 可访问

## 5. 测试数据

### 5.1 OCR 测试图片
- 位置：自动生成到 `shared/outputs/test_ocr.png`
- 内容：手写体风格文字 "1+1=" "2+2="

### 5.2 PPT 测试大纲
- 文件名：`integration_test.pptx`
- 主题："集成测试 PPT"
- 大纲：2 页，每页包含标题和要点

### 5.3 Filesystem 测试文件
- 写入文件：`shared/outputs/fs_test.txt`
- 内容：测试文本 "Hello from filesystem-mcp"

## 6. 预期测试时间

| 测试项 | 预计时间 |
|--------|---------|
| 端口对齐检查 | 5 分钟 |
| 服务启动 | 5 分钟 |
| File Server 测试 | 2 分钟 |
| Filesystem MCP 测试 | 3 分钟 |
| PaddleOCR 联通测试 | 10 分钟 |
| Presenton 联通测试 | 15 分钟 |
| Office-Word 测试 | 10 分钟（待上游） |
| **总计** | **50 分钟** |

## 7. 失败排查

### 7.1 连接失败
- 检查 docker-compose 是否启动：`docker-compose ps`
- 检查端口是否占用：`netstat -ano | findstr <port>`

### 7.2 MCP 工具调用失败
- 检查 MCP server 是否启动：`netstat -ano | findstr 9001/9002/9003`
- 查看日志：`tail -f .logs/<server_name>.log`

### 7.3 文件未落地
- 检查 `shared/outputs/` 目录权限
- 检查环境变量 `FILE_SERVER_BASE`

## 8. 测试记录

| 日期 | 测试项 | 结果 | 备注 |
|------|--------|------|------|
| 2026-06-14 | 端口对齐检查 | PASS | Presenton 端口已修正为 7860 |
| — | File Server 测试 | — | 待执行 |
| — | Filesystem MCP 测试 | — | 待执行 |
| — | PaddleOCR 联通测试 | — | 待执行 |
| — | Presenton 联通测试 | — | 待执行 |
| — | Office-Word 测试 | — | 待上游服务部署 |

## 9. 下一步

1. 执行集成测试：`python tools/test/integration_test.py`
2. 根据测试结果更新 README 中的状态表
3. 如果 Office-Word-MCP-Server 未部署，标记为 "待上游"
4. 提交测试结果和文档更新