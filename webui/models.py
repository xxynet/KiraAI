"""
Pydantic models shared across WebUI routes.
"""
from typing import Any, Dict, List, Literal, Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OverviewWidget(BaseModel):
    widget_id: str
    label: Union[str, Dict[str, str]]
    content: str = ""
    icon: str = "Box"
    color: Literal["blue", "green", "purple", "yellow", "red", "gray"] = "blue"
    order: int = 100
    size: Literal["small", "wide"] = "small"


class HourlyMessageCount(BaseModel):
    """One data point for the hourly message line chart."""
    hour_ts: int = 0  # Unix timestamp of the hour bucket
    count: int = 0


class PlatformMessageCount(BaseModel):
    """One data point for the platform distribution pie chart."""
    platform: str = ""
    count: int = 0


class LLMModelStat(BaseModel):
    """Per-model LLM usage summary."""
    model: str = ""
    calls: int = 0
    success: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    total_response_ms: int = 0
    avg_response_ms: float = 0


class LLMSummary(BaseModel):
    """Aggregated LLM usage statistics."""
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0
    success_count: int = 0
    total_response_ms: int = 0
    by_model: List[LLMModelStat] = Field(default_factory=list)


class OverviewResponse(BaseModel):
    total_adapters: int = 0
    active_adapters: int = 0
    total_providers: int = 0
    active_providers: int = 0
    total_messages: int = 0
    runtime_duration: int = 0  # System uptime in seconds
    memory_usage: int = 0  # Process memory usage in MB
    total_memory: int = 0  # Total system memory in MB
    widgets: List[OverviewWidget] = Field(default_factory=list)
    message_hourly: List[HourlyMessageCount] = Field(default_factory=list)
    message_by_platform: List[PlatformMessageCount] = Field(default_factory=list)
    llm_summary: LLMSummary = Field(default_factory=LLMSummary)


class VersionResponse(BaseModel):
    version: str


class ProviderBase(BaseModel):
    name: str
    type: str
    status: str = "inactive"
    config: Dict = Field(default_factory=dict)
    locales: Dict[str, Dict[str, str]] = Field(default_factory=dict)


class ProviderResponse(ProviderBase):
    id: str
    model_config_data: Dict = Field(default_factory=dict, alias="model_config")
    supported_model_types: List[str] = Field(default_factory=list)
    type_display_name: str = ""
    type_locales: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    type_icon: Optional[str] = None
    type_icon_dark: Optional[str] = None


class ModelCreateRequest(BaseModel):
    model_type: str
    model_id: str
    config: Dict = Field(default_factory=dict)


class ModelUpdateRequest(BaseModel):
    config: Dict = Field(default_factory=dict)


class ModelSyncRequest(BaseModel):
    """Batch sync: add new model IDs and delete removed ones."""
    add_ids: List[str] = Field(default_factory=list)
    delete_ids: List[str] = Field(default_factory=list)
    config: Dict = Field(default_factory=dict)


class HealthCheckRequest(BaseModel):
    """Health check request for a specific model."""
    model_type: str
    model_id: str


class HealthCheckResponse(BaseModel):
    """Health check result."""
    success: bool
    latency: Optional[int] = None
    error: Optional[str] = None


class AdapterBase(BaseModel):
    name: str
    platform: str
    status: str = "inactive"
    description: str = ""
    config: Dict = Field(default_factory=dict)
    locales: Dict[str, Dict[str, str]] = Field(default_factory=dict)


class AdapterResponse(AdapterBase):
    id: str
    platform_display_name: str = ""
    platform_locales: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    platform_icon: Optional[str] = None
    platform_icon_dark: Optional[str] = None


class PersonaBase(BaseModel):
    name: str
    format: str = "text"
    content: str = ""


class PersonaGeneratorMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class PersonaGeneratorTurnRequest(BaseModel):
    messages: List[PersonaGeneratorMessage] = Field(default_factory=list, max_length=50)


class PersonaGeneratorTurnResponse(BaseModel):
    type: Literal["question", "proposal"]
    question: Optional[str] = None
    options: List[str] = Field(default_factory=list)
    allow_custom: bool = True
    name: Optional[str] = None
    format: Optional[str] = None
    content: Optional[str] = None


class PersonaResponse(PersonaBase):
    id: str
    created_at: int = 0
    is_active: bool = False


class TokenLoginRequest(BaseModel):
    access_token: str


class OnboardingStatusResponse(BaseModel):
    completed: bool
    version: int


class OnboardingCompleteRequest(BaseModel):
    lang: Literal["en", "zh"]
    timezone: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        try:
            ZoneInfo(value)
        except (OSError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Invalid IANA timezone") from exc
        return value


class ChangeTokenRequest(BaseModel):
    old_token: str
    new_token: str


class StickerItem(BaseModel):
    id: str
    desc: str = ""
    path: str


class StickerUpdateRequest(BaseModel):
    desc: str = ""


class PageMenu(BaseModel):
    """Menu entry for a plugin page, shown in sidebar."""
    route: str
    label: Union[str, Dict[str, str]]
    icon: Optional[str] = None
    order: int = 100

    @field_validator('label')
    @classmethod
    def validate_label(cls, v):
        if isinstance(v, str):
            if not v.strip():
                raise ValueError("label string must not be empty or whitespace")
            return v
        if isinstance(v, dict):
            for key, val in v.items():
                if not isinstance(key, str) or not isinstance(val, str):
                    raise ValueError(f"label dict keys and values must be strings, "
                                     f"got {type(key).__name__}: {type(val).__name__}")
                if not val.strip():
                    raise ValueError(f"label dict value for '{key}' must not be empty or whitespace")
            return v
        raise ValueError(f"label must be a str or dict, got {type(v).__name__}")


class PluginItem(BaseModel):
    id: str
    name: str
    version: str = ""
    author: str = ""
    description: str = ""
    repo: Optional[str] = None
    enabled: bool = True
    builtin: bool = False
    uninstallable: bool = False
    locales: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    core_version: Optional[str] = None
    error: Optional[str] = None
    status: str = "pending"
    menus: List[PageMenu] = Field(default_factory=list)
    icon: Optional[str] = None
    icon_dark: Optional[str] = None


class PluginConfigUpdateRequest(BaseModel):
    config: Dict[str, Any] = Field(default_factory=dict)


class PluginInstallGithubRequest(BaseModel):
    repo_url: str
    proxy: Optional[str] = None
    gh_proxy: Optional[str] = None
    commit_sha: Optional[str] = None

    @field_validator("commit_sha")
    @classmethod
    def validate_commit_sha(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if len(normalized) != 40 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("commit_sha must be a full 40-character Git commit SHA")
        return normalized


class PluginInstallResult(PluginItem):
    warnings: List[str] = Field(default_factory=list)


class PluginInstallTask(BaseModel):
    """A background GitHub plugin installation task."""

    task_id: str
    repo_url: str
    commit_sha: Optional[str] = None
    status: Literal["installing", "completed", "failed", "cancelled"]
    stage: Literal["downloading", "installing_dependencies", "loading", "completed", "failed", "cancelled"]
    plugin_id: Optional[str] = None
    error: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class PluginStoreItemResponse(BaseModel):
    id: str
    name: str
    version: str = ""
    author: str = ""
    description: str = ""
    category: Optional[str] = None
    category_name: Optional[str] = None
    category_locales: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    repo: Optional[str] = None
    commit_sha: Optional[str] = None
    release_tag: Optional[str] = None
    icon: Optional[str] = None
    icon_dark: Optional[str] = None
    locales: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    core_version: Optional[str] = None
    stars: int = 0
    updated_at: Optional[Union[int, str]] = None


class PluginUpdateCheckItem(BaseModel):
    plugin_id: str
    current_version: str = ""
    latest_version: Optional[str] = None
    commit_sha: Optional[str] = None
    has_update: bool = False
    error: Optional[str] = None


class PluginUpdateRequest(BaseModel):
    gh_proxy: Optional[str] = None
    commit_sha: Optional[str] = None

    @field_validator("commit_sha")
    @classmethod
    def validate_commit_sha(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if len(normalized) != 40 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("commit_sha must be a full 40-character Git commit SHA")
        return normalized


class PluginStoreFetchRequest(BaseModel):
    url: Optional[str] = None
    source_id: Optional[str] = None
    force_refresh: bool = False


class PluginStoreSourceItem(BaseModel):
    id: str
    name: str
    url: str
    cache_file: Optional[str] = None
    updated_at: int = 0
    is_current: bool = False
    created_at: int = 0


class PluginStoreSourceCreateRequest(BaseModel):
    name: str
    url: str


class PluginStoreSourceUpdateRequest(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None


class McpServerItem(BaseModel):
    id: str
    type: str = ""
    name: str = ""
    description: str = ""
    enabled: bool = False
    url: str = ""
    tools_count: int = 0


class McpServerConfigUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    # Accept either a raw JSON string or an object so the frontend can
    # send the Monaco editor content directly as a string.
    config: Any = Field(default_factory=dict)


class McpServerCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    config: Any


class SkillItem(BaseModel):
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    path: str = ""
    size_bytes: int = 0


class DirectoryEntry(BaseModel):
    name: str
    path: str
    size_bytes: int = 0
    file_count: int = 0


class StorageInfoResponse(BaseModel):
    data_path: str
    total_size_bytes: int = 0
    disk_total_bytes: int = 0
    disk_used_bytes: int = 0
    disk_free_bytes: int = 0
    directories: List[DirectoryEntry] = Field(default_factory=list)


class ReleaseItem(BaseModel):
    tag_name: str
    name: Optional[str] = None
    body: Optional[str] = None
    html_url: Optional[str] = None
    published_at: Optional[str] = None
    prerelease: bool = False
    draft: bool = False


class ReleasesResponse(BaseModel):
    current_version: str
    releases: List[ReleaseItem]


class BackupCreateResponse(BaseModel):
    filename: str
    size_bytes: int = 0
    created_at: str = ""


class RestoreResponse(BaseModel):
    success: bool
    message: str = ""


class DownloadReleaseRequest(BaseModel):
    tag_name: str


class UpdateStageProgress(BaseModel):
    status: str = "pending"
    percent: int = 0


class ReleaseUpdateProgress(BaseModel):
    id: str
    target_version: str
    status: str
    stage: str
    message: str
    overall_percent: int = 0
    stages: Dict[str, UpdateStageProgress] = Field(default_factory=dict)
