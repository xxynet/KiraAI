from dataclasses import dataclass
from typing import Literal


@dataclass
class PersonaInfo:
    id: str
    name: str | None = None
    format: Literal["text", "yaml", "markdown", "xml"] | None = None
    content: str | None = None
    created_at: int | None = None
    is_active: bool | None = None
    reference_image_path: str | None = None
    chat_rules: str | None = None
    private_chat_rules: str | None = None
    group_chat_rules: str | None = None
