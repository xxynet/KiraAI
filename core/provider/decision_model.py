"""Typed results for text decision models."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DecisionContent = str | dict[str, Any] | list[Any]
Probability = Annotated[float, Field(strict=True, ge=0, le=1)]


class DecisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)


class DecisionUsage(DecisionModel):
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)


class DecisionResponse(DecisionModel):
    model: str = Field(min_length=1)
    usage: DecisionUsage


class NoulResponse(DecisionResponse):
    type: Literal["noul"]
    noul: Probability


class ChoiceResponse(DecisionResponse):
    type: Literal["choice"]
    choice: str
    confidence: Probability
    probabilities: dict[str, Probability] = Field(min_length=1)


class ScoreResponse(DecisionResponse):
    type: Literal["score"]
    score: float = Field(strict=True, ge=0)
    confidence: Probability
    probabilities: dict[str, Probability] = Field(min_length=2, max_length=10)
    legend: dict[str, DecisionContent | None]
