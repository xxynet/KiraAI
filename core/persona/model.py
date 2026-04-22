from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class PersonaInfo:
    id: str
    name: Optional[str] = None
    format: Optional[Literal["text", "yaml", "markdown", "xml"]] = None
    content: Optional[str] = None
    created_at: Optional[int] = None
