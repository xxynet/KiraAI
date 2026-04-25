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

export interface SettingsRequest {
  language: string
  theme: string
}

export interface SettingsResponse extends SettingsRequest {
  updated_by: string | null
}

export interface StickerItem {
  id: string
  desc: string
  path: string
}

export interface StickerUpdateRequest {
  desc: string
}

export interface PluginItem {
  id: string
  name: string
  version: string
  author: string
  description: string
  repo: string | null
  enabled: boolean
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
