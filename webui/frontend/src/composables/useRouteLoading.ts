import { ref } from 'vue'
import router from '@/router'

type Phase = 'idle' | 'loading' | 'completing'

const phase = ref<Phase>('idle')
let finishTimeout: ReturnType<typeof setTimeout> | null = null
let stuckTimeout: ReturnType<typeof setTimeout> | null = null
let guardsRegistered = false

function reset() {
  phase.value = 'idle'
}

export function useRouteLoading() {
  if (!guardsRegistered) {
    guardsRegistered = true

    router.beforeEach(() => {
      if (finishTimeout) clearTimeout(finishTimeout)
      if (stuckTimeout) clearTimeout(stuckTimeout)
      phase.value = 'loading'
      // Safety: auto-reset after 15s if navigation never completes
      stuckTimeout = setTimeout(reset, 15000)
    })

    const finish = () => {
      if (stuckTimeout) clearTimeout(stuckTimeout)
      phase.value = 'completing'
      finishTimeout = setTimeout(reset, 350)
    }

    router.afterEach(finish)
    router.onError(finish)
  }

  return { phase }
}
