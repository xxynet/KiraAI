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
        phase.value = 'loading'
        stuckTimeout = setTimeout(reset, 15000)
      }, SHOW_DELAY)
    })

    const finish = () => {
      if (showTimeout) {
        // Navigation completed before the threshold — keep it invisible
        clearTimeout(showTimeout)
        showTimeout = null
        return
      }

      if (stuckTimeout) clearTimeout(stuckTimeout)
      phase.value = 'completing'
      finishTimeout = setTimeout(reset, 350)
    }

    router.afterEach(finish)
    router.onError(finish)
  }

  return { phase }
}
