"""
共享数据结构定义 —— 全体窗口只读，不得擅自修改。
变更需先在 INTERFACE_CONTRACT.md 登记并通知所有窗口。
"""
from typing import TypedDict, Optional, Literal


class StandardMessage(TypedDict):
    """统一消息结构：各渠道适配器产出，编排核心消费。"""
    channel: str                              # wecom / mp / web / miniapp
    user_id: str                              # family_{姓名拼音}
    msg_type: Literal["text", "image", "file"]
    content: str
    media_url: Optional[str]
    timestamp: int


class ReplyMessage(TypedDict):
    """编排核心 → 渠道的回复结构。"""
    user_id: str
    content_type: Literal["text", "file"]
    content: str
    file_url: Optional[str]
