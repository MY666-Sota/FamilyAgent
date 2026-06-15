"""
file-server — 端口 8090
静态文件服务，挂载 shared/outputs/ 目录。
URL 格式：http://localhost:8090/files/{filename}

下载由 Starlette StaticFiles 处理（自带 Range 请求支持与目录穿越防护，
适合 .pptx/.docx 等较大文件）。/health 与 /list 为辅助接口。
"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

OUTPUTS_DIR = Path(__file__).parent.parent.parent / "shared" / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="FamilyAgent File Server", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok", "outputs_dir": str(OUTPUTS_DIR)}


@app.get("/list")
def list_files(subdir: str = ""):
    """列出 shared/outputs/ 下所有文件。"""
    base = (OUTPUTS_DIR / subdir).resolve()
    if not str(base).startswith(str(OUTPUTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法路径")
    if not base.exists():
        return {"files": []}
    files = [
        {
            "filename": f.relative_to(OUTPUTS_DIR).as_posix(),
            "url": f"http://localhost:8090/files/{f.relative_to(OUTPUTS_DIR).as_posix()}",
            "size": f.stat().st_size,
        }
        for f in base.rglob("*")
        if f.is_file()
    ]
    return {"files": files}


# StaticFiles 挂载放在自定义路由之后注册，仅接管 /files/* 的下载。
app.mount("/files", StaticFiles(directory=str(OUTPUTS_DIR)), name="files")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("FILE_SERVER_PORT", "8090"))
    uvicorn.run(app, host="0.0.0.0", port=port)
