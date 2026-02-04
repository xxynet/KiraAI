import json
import configparser
from pathlib import Path
from tavily import AsyncTavilyClient

from core.utils.tool_utils import BaseTool


class TavilySearchTool(BaseTool):
    name = "search"
    description = "通过关键词在互联网上查找信息"
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "关键词"}
        },
        "required": ["keyword"]
    }

    def __init__(self):
        super().__init__()
        cfg = configparser.RawConfigParser()
        cfg_path = Path(__file__).parent / "tavily.ini"
        cfg.read(cfg_path, encoding="utf-8")
        self._key = cfg.get("tavily", "key")

    async def execute(self, keyword: str) -> str:
        client = AsyncTavilyClient(self._key)
        res = await client.search(query=keyword)
        results = res.get("results") or []
        results = results[:2] if len(results) > 2 else results
        return "".join(json.dumps(ele, ensure_ascii=False) for ele in results)
