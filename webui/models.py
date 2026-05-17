"""
Pydantic models shared across WebUI routes.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OverviewResponse(BaseModel):
    total_adapters: int = 0
    active_adapters: int = 0
    total_providers: int = 0
    active_providers: int = 0
    total_messages: int = 0
    system_status: str = "unknown"
    runtime_duration: int = 0  # System uptime in seconds
    memory_usage: int = 0  # Process memory usage in MB
    total_memory: int = 0  # Total system memory in MB


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


class PersonaBase(BaseModel):
    name: str
    format: str = "text"
    content: str = ""


class PersonaResponse(PersonaBase):
    id: str
    created_at: int = 0


class SettingsRequest(BaseModel):
    language: str = "en"
    theme: str = "light"


class SettingsResponse(SettingsRequest):
    updated_by: Optional[str] = None


class TokenLoginRequest(BaseModel):
    access_token: str


class StickerItem(BaseModel):
    id: str
    desc: str = ""
    path: str


class StickerUpdateRequest(BaseModel):
    desc: str = ""


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


class PluginConfigUpdateRequest(BaseModel):
    config: Dict[str, Any] = Field(default_factory=dict)


class PluginInstallGithubRequest(BaseModel):
    repo_url: str
    proxy: Optional[str] = None
    gh_proxy: Optional[str] = None


class PluginInstallResult(PluginItem):
    warnings: List[str] = Field(default_factory=list)


class PluginStoreItemResponse(BaseModel):
    id: str
    name: str
    version: str = ""
    author: str = ""
    description: str = ""
    category: Optional[str] = None
    repo: Optional[str] = None
    locales: Dict[str, Dict[str, str]] = Field(default_factory=dict)


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


class DownloadReleaseRequest(BaseModel):
    tag_name: str
