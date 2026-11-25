"""Plugin-facing descriptors for reusable subagents."""

from dataclasses import dataclass, field
from typing import Literal

from core.utils.tool_utils import BaseTool


@dataclass(kw_only=True)
class SubAgentPreset:
    """Plugin-owned subagent settings, read-only in WebUI and validated on registration.

    Import from core.plugin and pass an instance to ctx.register_subagent().
    Model selections use provider_id:model_id. Tools accept names or BaseTool
    instances; use tool_mode="custom" to select only those tools. Instances are
    runtime bindings scoped to this preset and must be registered after restart.
    Scope uses session SIDs: None allows all sessions, {"allow": [...]} allows
    only those sessions, and {"deny": [...]} excludes them. Plugins can populate
    the list from their own schema using multi_select with source="session".
    """

    name: str
    description: str = ""
    instruction_source: Literal["persona", "custom", "mixed"] = "persona"
    persona_id: str | None = None
    instruction: str = ""
    max_steps: int = -1
    tool_mode: Literal["inherit", "exclude", "custom"] = "inherit"
    tools: list[str | BaseTool] = field(default_factory=list)
    exclude_tools_from_main: bool = False
    skills: list[str] = field(default_factory=list)
    enabled: bool = True
    model: str | None = None
    scope: dict[Literal["allow", "deny"], list[str]] | None = None
