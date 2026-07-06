import { ref } from 'vue'

const visible = ref(false)

export function openChangeTokenModal() {
  visible.value = true
}

export function useChangeTokenModal() {
  return { visible, open: openChangeTokenModal }
}
