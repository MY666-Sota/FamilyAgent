"""
file-server — 端口 8090
静态文件服务，挂载 shared/outputs/ 目录。
URL 格式：http://localhost:8090/files/{filename}
"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

OUTPUTS_DIR = Path(__file__).parent.parent.parent / "shared" / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="FamilyAgent File Server", version="1.0.0")

app.mount("/files", StaticFiles(directory=str(OUTPUTS_DIR)), name="files")


@app.get("/health")
def health():
    return {"status": "ok", "outputs_dir": str(OUTPUTS_DIR)}


@app.get("/files/{filename:path}")
def get_file(filename: str):
    """下载 shared/outputs/ 下的文件，支持子路径。"""
    # 防目录穿越
    target = (OUTPUTS_DIR / filename).resolve()
    if not str(target).startswith(str(OUTPUTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法路径")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")
    return FileResponse(str(target), filename=target.name)


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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("FILE_SERVER_PORT", "8090"))
    uvicorn.run(app, host="0.0.0.0", port=port)
