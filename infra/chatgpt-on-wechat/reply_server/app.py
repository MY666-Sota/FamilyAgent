"""
reply_endpoint — 接收编排核心的回调，通过企微发送结果给用户

实现 INTERFACE_CONTRACT 接口一.3：
  POST /v1/reply
  { "user_id": str, "content_type": "text"|"file", "content": str, "file_url": str|null }
"""
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

app = FastAPI(title="wechat-reply", version="1.0.0")

WECHAT_CORP_ID = os.environ["WECHAT_CORP_ID"]
WECHAT_APP_SECRET = os.environ["WECHAT_APP_SECRET"]
WECHAT_AGENT_ID = os.environ["WECHAT_AGENT_ID"]

_token_cache: dict = {"token": None, "expires_at": 0.0}
_client = httpx.AsyncClient(timeout=15.0)


class ReplyRequest(BaseModel):
    user_id: str
    content_type: str   # "text" | "file"
    content: str
    file_url: str | None = None


@app.post("/v1/reply", status_code=200)
async def reply(req: ReplyRequest):
    # user_id 格式 family_xiaoming → 企微 userid 需要从 Mem0/映射表中查
    # 此处约定：user_id 直接用作企微 userid（运维侧保证两者一致）
    wecom_userid = req.user_id

    token = await _get_access_token()

    if req.content_type == "text":
        await _send_text(token, wecom_userid, req.content)
    elif req.content_type == "file" and req.file_url:
        # 先把文件发给企微临时素材，再以 file 消息发送
        media_id = await _upload_media(token, req.file_url)
        await _send_file(token, wecom_userid, media_id)
    else:
        raise HTTPException(status_code=400, detail="invalid content_type or missing file_url")

    return {"status": "ok"}


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


async def _get_access_token() -> str:
    import time
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    url = (
        "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        f"?corpid={WECHAT_CORP_ID}&corpsecret={WECHAT_APP_SECRET}"
    )
    resp = await _client.get(url)
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise HTTPException(status_code=502, detail=f"WeChat token error: {data}")

    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + data["expires_in"]
    return _token_cache["token"]


async def _send_text(token: str, userid: str, content: str):
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": userid,
        "msgtype": "text",
        "agentid": int(WECHAT_AGENT_ID),
        "text": {"content": content},
        "safe": 0,
    }
    resp = await _client.post(url, json=payload)
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise HTTPException(status_code=502, detail=f"WeChat send error: {data}")


async def _upload_media(token: str, file_url: str) -> str:
    # 从 file_url 下载文件后上传到企微临时素材
    file_resp = await _client.get(file_url)
    file_resp.raise_for_status()

    filename = file_url.rsplit("/", 1)[-1] or "result.bin"
    upload_url = (
        f"https://qyapi.weixin.qq.com/cgi-bin/media/upload"
        f"?access_token={token}&type=file"
    )
    resp = await _client.post(
        upload_url,
        files={"media": (filename, file_resp.content)},
    )
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise HTTPException(status_code=502, detail=f"WeChat upload error: {data}")
    return data["media_id"]


async def _send_file(token: str, userid: str, media_id: str):
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": userid,
        "msgtype": "file",
        "agentid": int(WECHAT_AGENT_ID),
        "file": {"media_id": media_id},
        "safe": 0,
    }
    resp = await _client.post(url, json=payload)
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise HTTPException(status_code=502, detail=f"WeChat send file error: {data}")
