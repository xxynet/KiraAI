import requests
import configparser
from pathlib import Path

from utils.tool_utils import BaseTool


class NtfyTool(BaseTool):
    name = "ntfy"
    description = "推送通知的工具，标题中不得出现中文"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "通知标题"},
            "msg": {"type": "string", "description": "通知内容"}
        },
        "required": ["msg"]
    }

    def __init__(self):
        super().__init__()
        cfg = configparser.RawConfigParser()
        cfg_path = Path("core/tools/ntfy.ini")
        cfg.read(cfg_path, encoding="utf-8")
        self._url = cfg.get("ntfy", "url")

    async def execute(self, msg: str, title: str = None) -> str:
        resp = requests.post(
            self._url,
            data=msg.encode(encoding="utf-8"),
            headers={
                "Title": title,
            }
        )
        return resp.text
