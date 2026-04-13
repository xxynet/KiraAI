from pydantic import BaseModel, Field
from typing import Literal, Union, Optional


class OpenAIMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Union[str, dict]

    # assistant
    reasoning_content: Optional[str] = ""

    tool_calls: Optional[list[dict]] = Field(default_factory=list)

    # tool
    tool_call_id: Optional[str] = None

    name: Optional[str] = None
