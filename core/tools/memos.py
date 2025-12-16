import requests
import configparser
from pathlib import Path
from typing import Optional

from utils.tool_utils import BaseTool


class MemosTool(BaseTool):
    name = "memos"
    description = "Post a memo to memos, a self-hosted version of Twitter"
    parameters = {
        "type": "object",
        "properties": {
            "memo": {"type": "string", "description": "memo content"},
            "location": {"type": "string", "description": "optional: location"},
        },
        "required": ["memo"]
    }

    def __init__(self):
        super().__init__()
        cfg = configparser.RawConfigParser()
        cfg_path = Path("core/tools/memos.ini")
        cfg.read(cfg_path, encoding="utf-8")
        self._url = cfg.get("memos", "url")
        self._access_token = cfg.get("memos", "token")
        self._visibility = cfg.get("memos", "visibility")

    async def execute(self, memo: str, location: str = "") -> str:
        response = requests.post(
            f"{self._url.strip('/')}/api/v1/memos",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._access_token}"
            },
            json={
                "state": "NORMAL",
                "content": memo,
                "visibility": self._visibility,
                "pinned": False,
                "location": {
                    "placeholder": location
                } if location else None
            }
        )
        return response.json()
