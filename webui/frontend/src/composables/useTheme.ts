import { computed } from 'vue'
import { useAppStore } from '@/stores/app'
import * as monaco from 'monaco-editor'

export function useTheme() {
  const appStore = useAppStore()

  function syncMonacoTheme() {
    monaco.editor.setTheme(appStore.isDark ? 'vs-dark' : 'vs')
  }

  function toggleTheme() {
    appStore.toggleTheme()
    syncMonacoTheme()
  }

  return {
    isDark: computed(() => appStore.isDark),
    theme: computed(() => appStore.theme),
    toggleTheme,
    syncMonacoTheme,
  }
}
