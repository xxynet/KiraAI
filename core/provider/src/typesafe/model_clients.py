"""Asynchronous TypeSafe System One transport and decision client."""

import json
import math
from typing import Annotated, Literal, TypeVar

import httpx
from pydantic import ConfigDict, Field, validate_call

from core.config.default import VERSION
from core.provider import (
    ChoiceResponse, DecisionContent, DecisionModelClient, DecisionResponse,
    NoulResponse, ProviderAPIError, ScoreResponse,
)

DEFAULT_BASE_URL = "https://api.typesafe.ai/v1"


async def request_json(config: dict, method: str, path: str, *, timeout: float, body=None):
    """Send one bounded request without exposing credentials or content in errors."""
    api_key = config.get("api_key")
    if not api_key:
        raise ProviderAPIError("TypeSafe API key is not configured")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("TypeSafe timeout must be a positive finite number")
    base_url = (config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    headers = httpx.Headers({
        "Authorization": f"Bearer {api_key}",
        "User-Agent": f"kira-ai/{VERSION.removeprefix('v')}",
    })
    advanced = config.get("section_advanced") or {}
    headers.update(advanced.get("headers") or {})
    content = None
    if body is not None:
        try:
            content = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            raise ValueError("TypeSafe request must contain finite JSON values") from None
        headers["Content-Type"] = "application/json"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method, f"{base_url}/{path}", headers=headers, content=content,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise ProviderAPIError(f"TypeSafe API returned HTTP {exc.response.status_code}") from None
    except httpx.TimeoutException:
        raise ProviderAPIError("TypeSafe API request timed out") from None
    except httpx.RequestError:
        raise ProviderAPIError("TypeSafe API connection failed") from None
    except ValueError:
        raise ProviderAPIError("TypeSafe API returned invalid JSON") from None


ResponseT = TypeVar("ResponseT", bound=DecisionResponse)
_validate_call = validate_call(config=ConfigDict(hide_input_in_errors=True))


class TypeSafeDecisionClient(DecisionModelClient):
    @_validate_call
    async def noul(
        self, state: DecisionContent, instructions: DecisionContent | None = None, *,
        criteria: dict[Literal["true", "false"], DecisionContent | None] | None = None,
    ) -> NoulResponse:
        return await self._request(state, {
            "type": "noul", "instructions": instructions, "criteria": criteria,
        }, NoulResponse)

    @_validate_call
    async def choice(
        self, state: DecisionContent, instructions: DecisionContent | None = None, *,
        criteria: Annotated[dict[str, DecisionContent | None], Field(min_length=1, max_length=255)],
    ) -> ChoiceResponse:
        result = await self._request(state, {
            "type": "choice", "instructions": instructions, "criteria": criteria,
        }, ChoiceResponse)
        if result.choice not in criteria or result.probabilities.keys() != criteria.keys():
            raise ProviderAPIError("TypeSafe API returned mismatched choices")
        return result

    @_validate_call
    async def score(
        self, state: DecisionContent, instructions: DecisionContent | None = None, *,
        criteria: Annotated[list[DecisionContent], Field(min_length=2, max_length=10)],
    ) -> ScoreResponse:
        result = await self._request(state, {
            "type": "score", "instructions": instructions, "criteria": criteria,
        }, ScoreResponse)
        levels = {str(index) for index in range(len(criteria))}
        if (result.score > len(criteria) - 1
                or result.probabilities.keys() != levels or result.legend.keys() != levels):
            raise ProviderAPIError("TypeSafe API returned mismatched score levels")
        return result

    async def _request(
        self, state: DecisionContent, question: dict, response_type: type[ResponseT],
    ) -> ResponseT:
        body = {
            "model": self.model.model_name,
            "state": state,
            "questions": {"decision": {
                key: value for key, value in question.items() if value is not None
            }},
        }
        data = await request_json(
            self.model.provider_config, "POST", "systemone",
            timeout=float(self.model.model_config.get("timeout", 30)), body=body,
        )
        try:
            if (not isinstance(data, dict) or not isinstance(data.get("answers"), dict)
                    or set(data["answers"]) != {"decision"}):
                raise ValueError("Mismatched questions")
            answer = data["answers"]["decision"]
            if not isinstance(answer, dict):
                raise ValueError("Invalid answer")
            result = response_type.model_validate({
                **answer, "model": data["model"], "usage": data["usage"],
            })
            if isinstance(result, (ChoiceResponse, ScoreResponse)):
                if not math.isclose(sum(result.probabilities.values()), 1, abs_tol=0.01):
                    raise ValueError("Invalid probability distribution")
        except (KeyError, ValueError):
            raise ProviderAPIError("TypeSafe API returned an invalid decision response") from None
        return result
