// API Response & Request Types - mirrors webui/models.py

export interface LoginRequest {
  username: string
  password: string
}

export interface TokenLoginRequest {
  access_token: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
}

export interface AuthConfigResponse {
  auth_enabled: boolean
}

export interface OverviewWidget {
  widget_id: string
  label: string | Record<string, string>
  value: string
  html: string
  icon: string
  color: string
  order: number
  size: 'small' | 'wide'
}

export interface OverviewResponse {
  total_adapters: number
  active_adapters: number
  total_providers: number
  active_providers: number
  total_messages: number
  system_status: string
  runtime_duration: number
  memory_usage: number
  total_memory: number
  widgets: OverviewWidget[]
}

export interface VersionResponse {
  version: string
}

export interface ProviderBase {
  name: string
  type: string
  status: string
  config: Record<string, any>
}

export interface ProviderResponse extends ProviderBase {
  id: string
  model_config: Record<string, any>
  supported_model_types: string[]
}

export interface ModelCreateRequest {
  model_type: string
  model_id: string
  config: Record<string, any>
}

export interface ModelUpdateRequest {
  config: Record<string, any>
}

export interface AdapterBase {
  name: string
  platform: string
  status: string
  description: string
  config: Record<string, any>
}

export interface AdapterResponse extends AdapterBase {
  id: string
}

export interface PersonaBase {
  name: string
  format: string
  content: string
}

export interface PersonaResponse extends PersonaBase {
  id: string
  created_at?: number
}

export interface PersonaContentResponse {
  content: string
  format: string
}

export interface PersonaContentUpdateRequest {
  content: string
  format?: string
}

export interface StickerItem {
  id: string
  desc: string
  path: string
}

export interface StickerUpdateRequest {
  desc: string
}

export interface PageMenu {
  route: string
  label: string | Record<string, string>
  icon: string | null
  order: number
}

export interface PluginItem {
  id: string
  name: string
  version: string
  author: string
  description: string
  repo: string | null
  enabled: boolean
  builtin?: boolean
  uninstallable?: boolean
  tags: string[]
  core_version?: string | null
  error?: string | null
  status?: string
  menus?: PageMenu[]
}

export interface PluginConfigUpdateRequest {
  config: Record<string, any>
}

export interface PluginInstallGithubRequest {
  repo_url: string
  proxy?: string | null
  gh_proxy?: string | null
}

export interface PluginInstallResult extends PluginItem {
  warnings: string[]
}

export interface McpServerItem {
  id: string
  type: string
  name: string
  description: string
  enabled: boolean
  url: string
  tools_count: number
}

export interface McpServerCreateRequest {
  name: string
  description?: string | null
  config: any
}

export interface McpServerConfigUpdateRequest {
  name?: string | null
  description?: string | null
  config: any
}

// Plugin Store types
export interface PluginStoreSource {
  id: string
  name: string
  url: string
  cache_file?: string | null
  updated_at: number
  is_current: boolean
  created_at: number
}

export interface PluginStoreItem {
  id: string
  name: string
  version: string
  author: string
  description: string
  category?: string
  repo?: string | null
  icon?: string | null
  downloads?: number
  tags?: string[]
  installed?: boolean
}

export interface PluginUpdateCheckItem {
  plugin_id: string
  current_version: string
  latest_version: string | null
  has_update: boolean
  error: string | null
}

// Configuration types — mirrors the shape returned by webui/routes/config.py
export interface ConfigurationProvider {
  id: string
  name: string
}

export interface ConfigurationData {
  configuration: Record<string, any>
  providers: ConfigurationProvider[]
  provider_models: Record<string, Record<string, any>>
}

// Session types — mirrors webui/routes/sessions.py
export interface SessionItem {
  id: string
  adapter_name: string
  session_type: string
  session_id: string
  title?: string
  description?: string
  message_count: number
}

export interface SessionDetail extends SessionItem {
  messages: any[]
}

// Log types
export interface LogEntry {
  timestamp: string
  level: string
  message: string
  logger?: string
  color?: string
}

export interface LogConfig {
  maxQueueSize: number
}

// Schema field types for dynamic form rendering
export interface SchemaField {
  type: string
  title?: string
  description?: string
  default?: any
  minimum?: number
  maximum?: number
  enum?: any[]
  items?: SchemaField
  properties?: Record<string, SchemaField>
  required?: string[]
}

// Release types
export interface ReleaseItem {
  tag_name: string
  name: string | null
  body: string | null
  html_url: string | null
  published_at: string | null
  prerelease: boolean
  draft: boolean
}

export interface ReleasesResponse {
  current_version: string
  releases: ReleaseItem[]
}

// Scope types — mirrors webui/routes/scope.py
export type ScopeEntry = { allow: string[] } | { deny: string[] }

export interface ScopeResponse {
  mcp_scopes: Record<string, ScopeEntry>
  skill_scopes: Record<string, ScopeEntry>
  sessions: { id: string; adapter: string; type: string; session_id: string; title: string }[]
  mcp_servers: { id: string; name: string; enabled: boolean }[]
  skills: { name: string; enabled: boolean }[]
}
