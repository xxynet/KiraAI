import { computed } from 'vue'
import { useAppStore } from '@/stores/app'

export function useTheme() {
  const appStore = useAppStore()

  async function syncMonacoTheme() {
    // Lazy-load Monaco so it stays out of the initial bundle for users who
    // never toggle the theme while an editor is on screen.
    const monaco = await import('monaco-editor')
    monaco.editor.setTheme(appStore.isDark ? 'vs-dark' : 'vs')
  }

  async function toggleTheme() {
    appStore.toggleTheme()
    await syncMonacoTheme()
  }

  return {
    isDark: computed(() => appStore.isDark),
    theme: computed(() => appStore.theme),
    toggleTheme,
    syncMonacoTheme,
  }
}
