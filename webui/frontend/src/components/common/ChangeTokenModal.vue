<template>
  <Modal v-model="visible" content-class="max-w-md">
    <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
      <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
        <div>
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('settings.token_title') }}</h3>
          <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ $t('settings.token_desc') }}</p>
        </div>
        <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="visible = false">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
        </button>
      </div>
      <div class="px-6 py-4 flex-1 overflow-y-auto space-y-4">
        <div>
          <label for="modal-token-old" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('settings.token_old') }}</label>
          <input
            id="modal-token-old"
            v-model="oldToken"
            type="password"
            :placeholder="$t('settings.token_old_placeholder')"
            class="w-full px-3 py-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-800 dark:text-gray-200"
          />
        </div>
        <div>
          <label for="modal-token-new" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('settings.token_new') }}</label>
          <input
            id="modal-token-new"
            v-model="newToken"
            type="password"
            :placeholder="$t('settings.token_new_placeholder')"
            class="w-full px-3 py-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-800 dark:text-gray-200"
          />
        </div>
        <div>
          <label for="modal-token-confirm" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('settings.token_confirm') }}</label>
          <input
            id="modal-token-confirm"
            v-model="confirmToken"
            type="password"
            :placeholder="$t('settings.token_confirm_placeholder')"
            class="w-full px-3 py-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-800 dark:text-gray-200"
          />
        </div>
      </div>
      <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
        <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="visible = false">{{ $t('settings.backup_confirm_cancel') }}</button>
        <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="tokenChanging" @click="tokenConfirmRef?.open()">{{ tokenChanging ? $t('settings.token_changing') : $t('settings.token_submit') }}</button>
      </div>
    </div>

    <!-- Confirm Modal -->
    <ConfirmModal
      ref="tokenConfirmRef"
      variant="danger"
      :title="$t('settings.token_submit')"
      :message="$t('settings.token_confirm_dialog')"
      :cancel-text="$t('settings.backup_confirm_cancel')"
      :confirm-text="$t('settings.backup_confirm_ok')"
      @confirm="handleChangeToken"
    />
  </Modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { notify } from '@/composables/useNotification'
import { useChangeTokenModal } from '@/composables/useChangeTokenModal'
import { changeAccessToken } from '@/api/settings'
import Modal from './Modal.vue'
import ConfirmModal from './ConfirmModal.vue'

const { t } = useI18n()
const router = useRouter()
const { visible } = useChangeTokenModal()

const oldToken = ref('')
const newToken = ref('')
const confirmToken = ref('')
const tokenChanging = ref(false)
const tokenConfirmRef = ref<InstanceType<typeof ConfirmModal>>()

// Clear inputs when modal opens
watch(visible, (val) => {
  if (val) {
    oldToken.value = ''
    newToken.value = ''
    confirmToken.value = ''
  }
})

async function handleChangeToken() {
  if (!oldToken.value) {
    notify(t('settings.token_old_required'), 'error')
    return
  }
  if (!newToken.value || newToken.value.length < 6) {
    notify(t('settings.token_new_too_short'), 'error')
    return
  }
  if (newToken.value !== confirmToken.value) {
    notify(t('settings.token_mismatch'), 'error')
    return
  }
  tokenChanging.value = true
  try {
    await changeAccessToken(oldToken.value, newToken.value)
    notify(t('settings.token_changed_logout'), 'success')
    visible.value = false
    localStorage.removeItem('jwt_token')
    router.push('/login')
    return
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    if (detail === 'Old token is incorrect') {
      notify(t('settings.token_old_wrong'), 'error')
    } else {
      notify(t('settings.token_change_failed'), 'error')
    }
  } finally {
    tokenChanging.value = false
  }
}
</script>
