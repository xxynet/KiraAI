import asyncio
from pathlib import Path
from typing import Optional, Sequence

import httpx

from core.plugin import logger


class AnySearchClient:
    """Asynchronous client for the AnySearch API."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: float = 60.0,
        auto_key_path: Optional[Path] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._auto_key_path = auto_key_path
        self._auto_key = ""
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._timeout = timeout

    @property
    def has_credentials(self) -> bool:
        return bool(self._api_key or self._auto_key)

    async def initialize(self) -> None:
        """Load a previously issued anonymous API key, if available."""
        if not self._api_key and self._auto_key_path:
            self._auto_key = await asyncio.to_thread(self._read_auto_key)

    async def close(self) -> None:
        """Release the HTTP client owned by this instance."""
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def _read_auto_key(self) -> str:
        try:
            if self._auto_key_path and self._auto_key_path.exists():
                return self._auto_key_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Unable to read AnySearch anonymous API key: %s", exc)
        return ""

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self._timeout)
        return self._http_client

    def _headers(self, api_key: Optional[str] = None) -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-Anysearch-Client": "kiraai/1.0.0",
        }
        key = api_key or self._api_key or self._auto_key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def _save_auto_key(self, key: str) -> None:
        if not key or key == self._auto_key:
            return
        self._auto_key = key
        if not self._auto_key_path:
            return
        try:
            await asyncio.to_thread(self._write_auto_key, key)
        except OSError as exc:
            logger.warning("Unable to save AnySearch anonymous API key: %s", exc)

    def _write_auto_key(self, key: str) -> None:
        if not self._auto_key_path:
            return
        self._auto_key_path.parent.mkdir(parents=True, exist_ok=True)
        self._auto_key_path.write_text(key, encoding="utf-8")
        try:
            self._auto_key_path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _extract_auto_key(message: str) -> str:
        for line in (message or "").splitlines():
            line = line.strip()
            if line.startswith("api_key="):
                return line.split("=", 1)[1].strip().rstrip(".")
        return ""

    async def _send(
        self,
        method: str,
        path: str,
        payload: Optional[dict] = None,
        params: Optional[Sequence[tuple[str, str]]] = None,
        api_key: Optional[str] = None,
    ) -> httpx.Response:
        client = await self._get_http_client()
        return await client.request(
            method,
            f"{self._base_url}{path}",
            json=payload,
            params=params,
            headers=self._headers(api_key),
        )

    async def _request(
        self,
        method: str,
        path: str,
        payload: Optional[dict] = None,
        params: Optional[Sequence[tuple[str, str]]] = None,
    ) -> dict:
        try:
            response = await self._send(method, path, payload, params)
        except httpx.TimeoutException:
            return {"error": "AnySearch 请求超时，请稍后重试"}
        except httpx.HTTPError as exc:
            return {"error": f"AnySearch 网络错误：{exc}"}

        try:
            body = response.json()
        except ValueError:
            return {"error": f"AnySearch 无效响应（HTTP {response.status_code}）：{response.text[:200]}"}
        if not isinstance(body, dict):
            return {"error": f"AnySearch 无效响应（HTTP {response.status_code}）：非 JSON 对象"}

        if response.status_code >= 400 and body.get("code", 0) != 0:
            auto_key = self._extract_auto_key(body.get("message", ""))
            if auto_key:
                await self._save_auto_key(auto_key)
                try:
                    response = await self._send(method, path, payload, params, auto_key)
                    body = response.json()
                    if response.status_code < 400 and body.get("code", 0) == 0:
                        return body
                except Exception as exc:
                    logger.warning("AnySearch retry after anonymous key issuance failed: %s", exc)
                return {"error": "AnySearch 匿名开户后重试失败，请稍后重试"}

        if response.status_code >= 400 or body.get("code", 0) != 0:
            message = body.get("message") or f"HTTP {response.status_code}"
            request_id = body.get("request_id", "")
            return {"error": f"{message}（request_id: {request_id}）" if request_id else message}
        return body

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        sub_domain: Optional[str] = None,
        params: Optional[dict] = None,
        topic: str = "general",
    ) -> dict:
        """Search the web and return normalized result items."""
        payload = {"query": query}
        if sub_domain:
            payload["tag"] = sub_domain
        if params:
            payload["params"] = params
        if topic == "news":
            payload["language"] = "zh"
        if max_results is not None:
            payload["max_results"] = max_results

        body = await self._request("POST", "/v1/search", payload=payload)
        if "error" in body:
            return {"results": [], "error": body["error"]}

        results = []
        for item in (body.get("data") or {}).get("results") or []:
            result = dict(item)
            result["source"] = "anysearch"
            result["score"] = float(result.get("score") or 0.0)
            results.append(result)
        return {"results": results, "error": None}

    async def extract(self, url: str) -> dict:
        """Extract page content for a URL."""
        return await self._request("POST", "/v1/extract", payload={"url": url})

    async def get_sub_domains(self, domains: Sequence[str]) -> dict:
        """Return the vertical search catalog for the requested domains."""
        return await self._request(
            "GET",
            "/v1/sub-domains",
            params=[("domain", domain) for domain in domains],
        )
