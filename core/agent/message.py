from pydantic import BaseModel, Field
from typing import Literal, Union, Optional


class OpenAIMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Union[str, list, dict, None] = None

    # assistant
    reasoning_content: Optional[str] = ""

    tool_calls: Optional[list[dict]] = Field(default_factory=list)

    # tool
    tool_call_id: Optional[str] = None

    name: Optional[str] = None

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
