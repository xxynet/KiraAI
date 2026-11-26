import { ref } from 'vue'
import router from '@/router'

type Phase = 'idle' | 'loading' | 'completing'

const phase = ref<Phase>('idle')
let showTimeout: ReturnType<typeof setTimeout> | null = null
let finishTimeout: ReturnType<typeof setTimeout> | null = null
let stuckTimeout: ReturnType<typeof setTimeout> | null = null
let guardsRegistered = false

const SHOW_DELAY = 200 // ms to wait before showing bar (instant navs skip it)

function reset() {
  phase.value = 'idle'
}

export function useRouteLoading() {
  if (!guardsRegistered) {
    guardsRegistered = true

    router.beforeEach(() => {
      if (finishTimeout) clearTimeout(finishTimeout)
      if (showTimeout) clearTimeout(showTimeout)
      if (stuckTimeout) clearTimeout(stuckTimeout)

      // Wait a tick — if navigation resolves within SHOW_DELAY, bar never appears
      showTimeout = setTimeout(() => {
        showTimeout = null // tell finish() the bar is now visible
        phase.value = 'loading'
        stuckTimeout = setTimeout(reset, 15000)
      }, SHOW_DELAY)
    })

    const finish = (cancelled = false) => {
      if (cancelled) {
        if (showTimeout) clearTimeout(showTimeout)
        if (finishTimeout) clearTimeout(finishTimeout)
        if (stuckTimeout) clearTimeout(stuckTimeout)
        showTimeout = null
        finishTimeout = null
        stuckTimeout = null
        reset()
        return
      }

      if (showTimeout) {
        // Navigation completed before the threshold — keep it invisible
        clearTimeout(showTimeout)
        showTimeout = null
        return
      }

      // A guard can cancel navigation before the loading guard ever runs.
      if (phase.value !== 'loading') return

      if (stuckTimeout) clearTimeout(stuckTimeout)
      phase.value = 'completing'
      finishTimeout = setTimeout(reset, 350)
    }

    router.afterEach((_to, _from, failure) => finish(Boolean(failure)))
    router.onError(() => finish(true))
  }

  return { phase }
}
