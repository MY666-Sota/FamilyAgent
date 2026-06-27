# 上游服务本地部署调研（UPSTREAM_DEPLOY.md）

> 调研日期：2026-06-17　负责人：窗口3（MCP 工具层）
> 目的：为窗口1 真实功能联调准备上游服务。本文档**仅调研与方案设计**，未实际拉取大镜像。
> 配套：本层 3 个 SSE server（office-word 9001 / presenton 9002 / paddleocr 9003）已"握手就绪、上游待部署"。

## 摘要（先读这段）

| 上游 | 推荐本地方式 | 体积 | 能否绕大镜像 | 与现有 MCP 代码的契合度 |
|------|-------------|------|-------------|----------------------|
| **Office-Word** | pip 直装 `office-word-mcp-server` | ~10 MB（纯 Python） | ✅ 完全不用 Docker | ⚠️ **架构不符**：上游是 stdio MCP，非 9011 HTTP 服务 |
| **Presenton** | 官方 Docker 镜像 | 镜像较大（含前端+FastAPI+浏览器渲染，估 1.5~3 GB） | 🟡 只能 Docker，无轻量 pip 路径 | ⚠️ **API 路径/字段不符**：真实接口是 `/api/v1/ppt/presentation/generate` |
| **PaddleOCR-VL** | 官方仅 GPU；CPU 用社区版 `Think-Core/paddleocr-vl-cpu` 或退回 PP-OCRv5 pip | GPU 镜像数 GB（CUDA）；CPU pip 方案 ~几百 MB 模型 | 🟡 官方 VL 不支持 CPU；需替代方案 | ⚠️ **接口形态不符**：现有代码假设 `POST /ocr` 自定义格式 |

**结论**：三个上游都能本地跑起来，但**没有一个能直接对上现有 MCP server 代码里的假设**。联调前需要先对齐适配层（见每节"⚠️ 适配差异"）。建议优先级：Office-Word（最轻、改动最小）→ PaddleOCR（CPU 替代）→ Presenton（最重，依赖 Docker）。

---

## 1. Office-Word-MCP-Server（上游，现假设 9011）

### 1.1 真实形态
- **来源**：[GongRzhe/Office-Word-MCP-Server](https://github.com/GongRzhe/Office-Word-MCP-Server)，已发布到 PyPI：[office-word-mcp-server](https://pypi.org/project/office-word-mcp-server/)。
- **本质**：它**本身就是一个 MCP server**（基于 python-docx + FastMCP），默认 **stdio 传输**，不是一个监听 9011 端口的 REST/HTTP 服务。
- **体积**：纯 Python 包，依赖 `python-docx`、`mcp` 等，安装约 10 MB 量级，**完全不需要 Docker**。

### 1.2 部署方式（最轻，推荐）
```bash
# 方式 A：pip 直装
pip install office-word-mcp-server
python -m word_mcp_server          # 默认 stdio

# 方式 B：uvx 免安装运行（官方推荐）
uvx --from office-word-mcp-server word_mcp_server
```

### 1.3 ⚠️ 适配差异（联调前必读）
现有 [office-word-mcp/server.py](office-word-mcp/server.py) 的假设：
```python
WORD_MCP_BASE = "http://localhost:9011"
await client.post(f"{WORD_MCP_BASE}/create", json={...})   # 假设上游是 REST
```
**但真实上游是 stdio MCP，没有 `/create` `/read` `/append` 这些 HTTP 端点。**

有两条对齐路线：
- **路线 A（推荐，零外部依赖）**：放弃"代理外部 9011 服务"的设计，直接在我们自己的 office-word-mcp 里用 `python-docx` 实现文档读写。Word 文档操作本质就是 python-docx，没必要再套一层进程。这样上游依赖直接消失，9001 server 自给自足。
- **路线 B（保留代理设计）**：用一个 stdio→HTTP 适配器把上游 MCP 包起来暴露成 9011 REST，工作量大且无收益。

> 建议联调时走路线 A：把 9011 的 HTTP 调用替换为本地 python-docx 调用。届时 office-word-mcp 可从"上游待部署"直接转"已实测"。

---

## 2. Presenton（上游 7860 / 官方默认 5000）

### 2.1 真实形态
- **来源**：[presenton/presenton](https://github.com/presenton/presenton)，开源 AI PPT 生成器，自带前端 + FastAPI 后端。
- **官方部署**：Docker 镜像 `ghcr.io/presenton/presenton:latest`（[GHCR 包页](https://ghcr.io/presenton/presenton)）。
- **官方文档默认端口是 `5000`**（[quickstart](https://docs.presenton.ai/v3/get-started/quickstart)），docker-compose 里映射成了 7860 —— 两边对齐时以**容器内端口**为准，宿主端口可任意映射。
- **体积**：镜像含 Next.js 前端 + Python 后端 + PPT 渲染链，**偏大（估 1.5~3 GB）**。无纯 pip 轻量路径。

### 2.2 部署方式（官方 Docker）
```bash
# 官方 quickstart 形态（端口可改）
docker run -d --name presenton \
  -p 7860:80 \
  -e LLM="openai" \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -e OPENAI_BASE_URL="$OPENAI_API_BASE" \
  -e CAN_CHANGE_KEYS="false" \
  -v presenton_data:/app_data \
  ghcr.io/presenton/presenton:latest
```
- **LLM 后端**：支持 OpenAI 兼容 API（本项目走 DeepSeek 云端，填 `OPENAI_BASE_URL`），也支持 Ollama 全离线（[using-ollama-models](https://docs.presenton.ai/configurations/using-ollama-models)）。不强制 GPU——用云端 API 时纯 CPU 即可。
- **环境变量**：`CAN_CHANGE_KEYS` 控制是否允许前端改密钥（[environment-variables](https://docs.presenton.ai/configurations/environment-variables)）。

### 2.3 镜像拉取风险（参考窗口2 代理大文件断流）
- ghcr.io 镜像较大，**在受限代理网络下可能断流**（与窗口2 遇到的大镜像问题同类）。
- 缓解方案：
  1. 配置 Docker 走可靠代理或 registry 镜像加速；
  2. 用 `docker pull` 单独预拉、失败可断点重试（比 compose up 中途断更可控）；
  3. 实在拉不动时，PPT 生成可临时降级为"窗口3 本地用 python-pptx 生成简版"，但功能远不如 Presenton，仅应急。

### 2.4 ⚠️ 适配差异（联调前必读）
现有 [presenton-mcp/server.py](presenton-mcp/server.py) 的假设：
```python
PRESENTON_BASE = "http://localhost:7860"
await client.post(f"{PRESENTON_BASE}/api/generate", json={
    "topic":..., "outline":..., "output_filename":...})
data.get("file_path"); data.get("slide_count")
```
**真实 API 不是这个**（见 [API 参考](https://docs.presenton.ai/api-reference/presentation/generate-presentation-sync-v1)）：
- 端点：`POST /api/v1/ppt/presentation/generate`（同步）或 `.../generate/async`
- 请求体字段与 `topic/outline` 不同（用 `prompt`/`n_slides`/`template` 等）
- 响应：`{"presentation_id": "...", "path": "/static/user_data/.../xxx.pptx"}`，**没有 `file_path`/`slide_count`，pptx 路径在 `path` 字段**

**联调动作**：部署后先 `curl` 打一次真实接口拿到准确 schema，再改 presenton-mcp 的请求 URL、请求体字段、响应解析（`path` → 下载/复制到 shared/outputs/）。

---

## 3. PaddleOCR-VL（上游 8868）

### 3.1 真实形态
- **官方 PaddleOCR-VL**：基于 0.9B 视觉语言模型的文档解析方案。**官方明确当前不支持 CPU / ARM**（[PaddleX 文档](https://paddlepaddle.github.io/PaddleX/3.3/en/pipeline_usage/tutorials/ocr_pipelines/PaddleOCR-VL.html)："currently does not support CPU or Arm architecture"）。
- docker-compose 里用的 `paddlepaddle/paddle:2.6.1-gpu-cuda12.0-...` 是 **CUDA GPU 大镜像（数 GB）**，无 GPU 机器跑不动。

### 3.2 本地部署方案（按硬件分支）
**A. 有 NVIDIA GPU** → 用官方 GPU 路径（docker-compose 现状），或一键 Docker（[Medium 教程](https://medium.com/@alex_paddleocr/one-click-deployment-of-paddleocr-vl-with-docker-ce24f3725ac9)）。

**B. 无 GPU（最可能的本地情况）** → 两个绕过大镜像的选择：
- **B1. CPU 社区版**：[Think-Core/paddleocr-vl-cpu](https://github.com/Think-Core/paddleocr-vl-cpu) —— "CPU-friendly OpenAI-compatible API for PaddleOCR-VL"，专为无 GPU 设计，暴露 OpenAI 兼容接口。
- **B2. 退回经典 PP-OCRv5（推荐，最稳）**：放弃 VL 大模型，用 PaddleOCR 3.0 的 PP-OCRv5。CPU 直装：
  ```bash
  python -m pip install paddlepaddle      # CPU 版
  python -m pip install paddleocr
  ```
  PP-OCRv5 mobile 仅 0.07B 参数，**CPU/边缘设备可跑，370+ 字符/秒**（[HF blog](https://huggingface.co/blog/baidu/ppocrv5)）。模型权重几百 MB，比 CUDA 镜像小一两个数量级。对"作业图片 OCR"这类需求，PP-OCRv5 精度已足够。
  - 现成 HTTP 封装可参考 [paddleocrserver-powered](https://pypi.org/project/paddleocrserver-powered/)（Flask+Waitress 一键 OCR HTTP 服务）。

### 3.3 ⚠️ 适配差异（联调前必读）
现有 [paddleocr-mcp/server.py](paddleocr-mcp/server.py) 的假设：
```python
PADDLEOCR_BASE = "http://localhost:8868"
await client.post(f"{PADDLEOCR_BASE}/ocr", json={"image": b64, "language":...})
# 期望返回 {"result": [[box, (text, score)], ...]}
```
真实接口取决于选哪个方案：
- 选 **B1 CPU-VL** → 是 OpenAI 兼容接口（`/v1/chat/completions` 形态），**与 `/ocr` 完全不同**，需要重写请求/解析。
- 选 **B2 PP-OCRv5 pip** → 没有现成的 `/ocr` HTTP 端点，需要我们自己用 FastAPI 包一层，**好处是输出格式我们自己定**，可以直接产出现有代码期望的 `{"result": [[box,(text,score)]]}`，paddleocr-mcp 几乎不用改。

**联调建议**：无 GPU 环境优先 **B2**——自己用 paddleocr pip + FastAPI 在 8868 上实现一个返回 `{"result": [[box,(text,score)]]}` 的 `/ocr`，这样 paddleocr-mcp 现有解析逻辑零改动即可联通。

---

## 4. 联调前 checklist（给窗口1 / 窗口2）

1. **Office-Word**：决定走路线 A（本地 python-docx，推荐）还是 B（代理 9011）。走 A 则无需窗口2 部署任何东西。
2. **Presenton**：窗口2 拉 `ghcr.io/presenton/presenton:latest`（注意大镜像断流风险），起在 7860；窗口3 按真实 `/api/v1/ppt/...` schema 改 presenton-mcp。
3. **PaddleOCR**：确认目标机器有无 GPU。无 GPU → 窗口3 用 B2 自建 8868 OCR 服务（CPU paddleocr + FastAPI），paddleocr-mcp 不动。
4. 任一上游起来后，跑 `python tools/test/integration_test.py` 做端到端验证。

## 5. 体积与"能否绕大镜像"总表

| 上游 | 大镜像 | 绕过方式 | 绕过后体积 |
|------|--------|---------|-----------|
| Office-Word | 无（本就纯 pip） | 路线 A 本地 python-docx | ~10 MB |
| Presenton | ghcr 镜像 1.5~3 GB | 无 pip 路径，只能优化拉取（预拉/加速/重试） | 仍需镜像 |
| PaddleOCR-VL | CUDA GPU 镜像数 GB | B2：CPU paddleocr pip + 自建 FastAPI | 模型权重几百 MB |

---

### 参考来源
- Office-Word：[GitHub](https://github.com/GongRzhe/Office-Word-MCP-Server)、[PyPI](https://pypi.org/project/office-word-mcp-server/)
- Presenton：[GitHub](https://github.com/presenton/presenton)、[Docker API 教程](https://docs.presenton.ai/v3/tutorial/generate-presentation-over-api-using-docker)、[API 参考](https://docs.presenton.ai/api-reference/presentation/generate-presentation-sync-v1)、[环境变量](https://docs.presenton.ai/configurations/environment-variables)、[GHCR 包](https://ghcr.io/presenton/presenton)
- PaddleOCR：[PaddleX VL 文档（CPU 不支持说明）](https://paddlepaddle.github.io/PaddleX/3.3/en/pipeline_usage/tutorials/ocr_pipelines/PaddleOCR-VL.html)、[CPU 社区版 paddleocr-vl-cpu](https://github.com/Think-Core/paddleocr-vl-cpu)、[PP-OCRv5 blog](https://huggingface.co/blog/baidu/ppocrv5)、[paddleocrserver-powered](https://pypi.org/project/paddleocrserver-powered/)
