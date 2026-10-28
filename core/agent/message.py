from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, Field


class OpenAIMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list | dict | None = None

    # assistant
    reasoning_content: str | None = ""

    tool_calls: list[dict] | None = Field(default_factory=list)

    # tool
    tool_call_id: str | None = None

    name: str | None = None
    extra: dict = Field(default_factory=dict, alias="_extra")

    def to_memory_dict(self) -> dict:
        """Include private metadata only when serializing persistent memory."""
        from core.chat.memory_metadata import normalize_memory

        message = self.to_dict()
        message["_extra"] = deepcopy(self.extra)
        message = normalize_memory([[message]])[0][0]
        self.extra = deepcopy(message["_extra"])
        return message

    def to_dict(self) -> dict:
        d = {"role": self.role, "content": self.content}
        if self.reasoning_content:
            d["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d

    def __getitem__(self, key: str):
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def __setitem__(self, key: str, value):
        setattr(self, key, value)


def provider_message_dict(message) -> dict:
    """Remove persistent metadata from both model objects and plugin dictionaries."""
    values = message if isinstance(message, dict) else message.to_dict()
    return {key: value for key, value in values.items() if key != "_extra"}
