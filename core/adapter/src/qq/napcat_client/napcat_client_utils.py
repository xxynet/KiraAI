from typing import Union, Optional, Type
import re


class QQMessageType:
    class Text:
        def __init__(self, text: str):
            self.text: str = text

        @property
        def repr(self):
            return self.text

    class Image:
        def __init__(self, url=None, base64=None):
            self.url: Optional[str] = url
            self.base64: Optional[str] = base64

        @property
        def repr(self):
            return "[Image]"

    class At:
        def __init__(self, pid: Union[int, str], nickname: Optional[str] = None):
            """set pid to 'all' to at all group members"""
            self.pid: str = str(pid)
            self.nickname: str = nickname

        @property
        def repr(self):
            if self.nickname:
                return f"[At {self.nickname}({self.pid})]"
            else:
                return f"[At {self.pid}]"

    class Reply:
        def __init__(self, message_id: Union[int, str], message_content: Optional[str] = None):
            self.message_id: str = str(message_id)
            self.message_content: str = message_content

        @property
        def repr(self):
            return f"[Reply {self.message_id}]"

    class Emoji:
        def __init__(self, emoji_id: Union[int, str]):
            self.emoji_id: str = str(emoji_id)

        @property
        def repr(self):
            return f"[Emoji {self.emoji_id}]"

    class Sticker:
        def __init__(self, sticker_id: Union[int, str], sticker_bs64: str):
            self.sticker_id: str = str(sticker_id)
            self.sticker_bs64: str = sticker_bs64

        @property
        def repr(self):
            return f"[Sticker {self.sticker_id}]"

    class Record:
        def __init__(self, bs64: str):
            self.bs64: str = bs64

        @property
        def repr(self):
            return f"[Record]"

    class Notice:
        def __init__(self, text: str):
            self.text = text

        @property
        def repr(self):
            return f"[Notice]"

    class Poke:
        def __init__(self, pid: Union[int, str]):
            self.pid = str(pid)

        @property
        def repr(self):
            return f"[Poke]"


class QQMessageChain:
    def __init__(self, msg_list: Optional[list] = None):
        self.msg_seg_list = msg_list if msg_list else []

    def to_list(self):
        msg_list = []
        for ele in self.msg_seg_list:
            if isinstance(ele, QQMessageType.Text):
                msg_list.append({
                    "type": "text",
                    "data": {
                        "text": ele.text
                    }
                })
            elif isinstance(ele, QQMessageType.Image):
                if ele.url:
                    file_param = ele.url
                elif ele.base64:
                    if ele.base64.startswith("base64://"):
                        file_param = ele.base64
                    elif re.match(r"data:image/(jpg|jpeg|png|gif|bmp|webp|tiff|svg);base64,", ele.base64):
                        m = re.match(r"data:image/(jpg|jpeg|png|gif|bmp|webp|tiff|svg);base64,(.*)", ele.base64)
                        file_param = f"base64://{m.group(2)}"
                    else:
                        file_param = ""
                else:
                    file_param = ""

                msg_list.append({
                    "type": "image",
                    "data": {
                        "file": file_param,
                        "summary": "[图片]"
                    }
                })
            elif isinstance(ele, QQMessageType.At):
                msg_list.append({
                    "type": "at",
                    "data": {
                        "qq": ele.pid,
                    }
                })
            elif isinstance(ele, QQMessageType.Reply):
                if any(isinstance(item, QQMessageType.Reply) for item in msg_list):
                    pass
                else:
                    msg_list.insert(0, {
                        "type": "reply",
                        "data": {
                            "id": ele.message_id
                        }
                    },)
            elif isinstance(ele, QQMessageType.Emoji):
                try:
                    msg_list.append({
                        "type": "face",
                        "data": {
                            "id": int(ele.emoji_id)
                        }
                    })
                except:
                    pass
            elif isinstance(ele, QQMessageType.Sticker):
                if ele.sticker_bs64.startswith("base64://"):
                    file_param = ele.sticker_bs64
                elif re.match(r"data:image/(jpg|jpeg|png|gif|bmp|webp|tiff|svg);base64,", ele.sticker_bs64):
                    m = re.match(r"data:image/(jpg|jpeg|png|gif|bmp|webp|tiff|svg);base64,(.*)", ele.sticker_bs64)
                    file_param = f"base64://{m.group(2)}"
                else:
                    file_param = ""
                msg_list.append({
                    "type": "image",
                    "data": {
                        "file": file_param,
                        "summary": "[动画表情]"
                    }
                })
            elif isinstance(ele, QQMessageType.Record):
                if ele.bs64.startswith("base64://"):
                    file_param = ele.bs64
                elif re.match(r"data:(.*)/(.*);base64,", ele.bs64):
                    m = re.match(r"data:(.*)/(.*);base64,(.*)", ele.bs64)
                    file_param = f"base64://{m.group(3)}"
                else:
                    file_param = ""
                msg_list.append({
                    "type": "record",
                    "data": {
                        "file": file_param
                    }
                })
        return msg_list
