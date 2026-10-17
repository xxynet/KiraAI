import asyncio
from typing import Optional, Protocol

import httpx

from core.logging_manager import get_logger

logger = get_logger("telemetry", "green")


class CountryCodeProvider(Protocol):
    """Look up the caller's country, raising on failed or invalid responses."""

    name: str

    async def fetch_country_code(self, client: httpx.AsyncClient) -> str: ...


def _parse_country_code(response: httpx.Response, field: str) -> str:
    response.raise_for_status()
    data = response.json()
    code = data.get(field) if isinstance(data, dict) else None
    if (
        not isinstance(code, str)
        or len(code) != 2
        or not code.isascii()
        or not code.isalpha()
        or data.get("success") is False
    ):
        raise ValueError("Invalid country code response")
    return code.upper()


class CountryIsProvider:
    name = "Country.is"

    async def fetch_country_code(self, client: httpx.AsyncClient) -> str:
        response = await client.get("https://api.country.is/")
        return _parse_country_code(response, "country")


class IpWhoIsProvider:
    name = "ipwho.is"

    async def fetch_country_code(self, client: httpx.AsyncClient) -> str:
        response = await client.get("https://ipwho.is/?fields=success,country_code")
        return _parse_country_code(response, "country_code")


class IpApiProvider:
    name = "ip-api"

    async def fetch_country_code(self, client: httpx.AsyncClient) -> str:
        response = await client.get("http://ip-api.com/json/?fields=countryCode")
        return _parse_country_code(response, "countryCode")


_PROVIDERS: tuple[CountryCodeProvider, ...] = (
    CountryIsProvider(),
    IpWhoIsProvider(),
    IpApiProvider(),
)


async def fetch_country_code() -> Optional[str]:
    """Try providers directly in order, with a 3-second budget for each lookup."""
    failures = []
    try:
        transport = httpx.AsyncHTTPTransport(proxy=None)
        async with httpx.AsyncClient(timeout=3.0, transport=transport, trust_env=False) as client:
            for provider in _PROVIDERS:
                try:
                    # Bound the whole lookup, including connection and response body.
                    code = await asyncio.wait_for(provider.fetch_country_code(client), timeout=3.0)
                    logger.debug(f"Country code detected via {provider.name}: {code}")
                    return code
                except Exception as e:
                    failures.append(f"{provider.name}: {type(e).__name__}")
    except Exception as e:
        failures.append(f"HTTP client: {type(e).__name__}")
    logger.warning(f"Failed to fetch country code: {'; '.join(failures)}")
    return None
