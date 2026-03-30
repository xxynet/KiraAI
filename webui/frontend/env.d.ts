/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

declare module 'vite-plugin-monaco-editor' {
  import type { Plugin } from 'vite'
  export default function monacoEditorPlugin(options?: any): Plugin
}
