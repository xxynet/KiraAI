from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class PersonaInfo:
    id: str
    name: Optional[str] = None
    format: Optional[Literal["text", "yaml", "markdown", "xml"]] = None
    content: Optional[str] = None
    created_at: Optional[int] = None
    is_active: Optional[bool] = None
    reference_image_path: Optional[str] = None
    chat_rules: Optional[str] = None
    private_chat_rules: Optional[str] = None
    group_chat_rules: Optional[str] = None
