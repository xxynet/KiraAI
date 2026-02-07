import json
from typing import Literal

from tavily import TavilyClient

from core.plugin import BasePlugin, logger, register_tool as tool


class SearchPlugin(BasePlugin):
    """
    Search plugin that provides internet search capability via Tavily
    """
    
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self._key = None
        self.available = True
    
    async def initialize(self):
        """
        Initialize the search plugin
        Load Tavily API key from plugin configuration
        """
        # Get tavily_key from plugin config
        self._key = self.plugin_cfg.get('tavily_key')

        logger.info("Initializing Tavily Search")

        if not self._key:
            logger.warning("Tavily API key not found. Please configure it in plugin config")
            self.available = False
    
    async def terminate(self):
        """
        Cleanup when plugin is terminated
        """
        pass

    # def get_tools(self) -> list[BaseTool]:
    #     return []

    @tool(
        "search",
        "A web search tool that uses Tavily to search the web for relevant content.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query to execute with Tavily."},
                "topic": {"type": "string", "enum": ["general", "news"], "description": "Optional. The category of the search.news is useful for retrieving real-time updates, general is for broader, more general-purpose searches that may include a wide range of sources. Defaults to general"},
                "search_depth": {"type": "string", "enum": ["basic", "advanced"], "description": "Optional. Controls the latency vs relevance tradeoff.\n\nadvanced: Highest relevance, higher latency.\nbasic: Balanced relevance and latency. Defaults to basic"}
            },
            "required": ["query"]
        }
    )
    async def tavily_search(self, query: str,
                            topic: Literal["general", "news", "finance"] = "general",
                            search_depth: Literal["basic", "advanced"] = "basic") -> str:
        if not self.available:
            return "Tavily API key not found. Please configure it in plugin config"
        client = TavilyClient(self._key)

        max_results = int(str(self.plugin_cfg.get("max_results", 5)))

        res = client.search(query=query, topic=topic, search_depth=search_depth, max_results=max_results)
        results = res.get("results") or []
        return "".join(json.dumps(ele, ensure_ascii=False) for ele in results)

    @tool(
        "extract_webpage",
        "Extract web page content from one specified URL using Tavily Extract.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to extract content from."},
                "query": {"type": "string", "description": "Optional. User intent for reranking extracted content chunks. When provided, chunks are reranked based on relevance to this query."},
                "extract_depth": {"type": "string", "enum": ["basic", "advanced"], "description": "Optional. Controls the latency vs relevance tradeoff.\n\nadvanced: Highest relevance, higher latency.\nbasic: Balanced relevance and latency. Defaults to basic"}
            },
            "required": ["url"]
        }
    )
    async def tavily_extract(self, url: str, query: str = None, extract_depth: Literal["basic", "advanced"] = "basic") -> str:
        if not self.available:
            return "Tavily API key not found. Please configure it in plugin config"
        client = TavilyClient(self._key)

        max_results = int(str(self.plugin_cfg.get("max_results", 5)))

        res = client.extract(urls=url, query=query, max_results=max_results, extract_depth=extract_depth)
        results = res.get("results") or []
        return "".join(json.dumps(ele, ensure_ascii=False) for ele in results)
