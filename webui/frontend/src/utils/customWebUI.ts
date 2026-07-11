export const DEFAULT_WEBUI_TITLE = 'KiraAI Admin Panel'
export const CUSTOM_WEBUI_TITLE_KEY = 'custom_webui_title'

export function resolveWebUITitle(title: string | null): string {
  const value = title?.trim()
  return value || DEFAULT_WEBUI_TITLE
}

export function applyWebUITitle(title: string | null) {
  document.title = resolveWebUITitle(title)
}
