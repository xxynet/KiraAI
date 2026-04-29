<template>
  <div>
    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
      <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">
        {{ $t('pages.sticker.title') }}
      </h3>
      <button
        class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors flex items-center"
        @click="openCreateDialog"
      >
        <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
        </svg>
        <span>{{ $t('sticker.add') }}</span>
      </button>
    </div>

    <!-- Error State -->
    <div v-if="loadError" class="flex flex-col justify-center items-center py-12">
      <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
      </svg>
      <p class="text-gray-500">{{ $t('sticker.load_failed') }}</p>
      <button
        class="mt-3 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors text-sm"
        @click="loadStickers"
      >
        {{ $t('sticker.retry') }}
      </button>
    </div>

    <!-- Empty State -->
    <div v-else-if="stickers.length === 0" class="flex justify-center items-center py-12">
      <div class="text-center">
        <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
        </svg>
        <p class="text-gray-500">{{ $t('sticker.no_stickers') }}</p>
      </div>
    </div>

    <!-- Sticker Cards -->
    <div v-else class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
      <div
        v-for="sticker in stickers"
        :key="sticker.id"
        class="bg-white dark:bg-gray-900 rounded-lg shadow overflow-hidden flex flex-col"
      >
        <div class="relative bg-gray-100 dark:bg-gray-800 flex items-center justify-center" style="padding-top: 100%;">
          <img
            v-if="sticker.path"
            :src="`/sticker/${encodeURIComponent(sticker.path)}`"
            :alt="sticker.desc || `Sticker ${sticker.id}`"
            class="absolute inset-0 w-full h-full object-contain"
            loading="lazy"
          />
        </div>
        <div class="p-4 flex-1 flex flex-col">
          <div class="flex items-center justify-between mb-2 min-w-0">
            <span class="text-sm font-semibold text-gray-800 dark:text-gray-100 truncate">#{{ sticker.id }}</span>
          </div>
          <p class="text-sm text-gray-600 dark:text-gray-300 truncate" :title="sticker.desc">{{ sticker.desc }}</p>
          <div class="mt-auto pt-3 flex justify-end space-x-3">
            <button
              class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800 transition-colors"
              @click="openEditDialog(sticker)"
            >
              {{ $t('sticker.edit') }}
            </button>
            <button
              class="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30 transition-colors"
              @click="handleDelete(sticker.id)"
            >
              {{ $t('common.delete') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Create/Edit Modal -->
    <Modal v-model="dialogVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full mx-4 flex flex-col modal-card" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">
            {{ editMode ? $t('sticker.modal_title_edit') : $t('sticker.modal_title_add') }}
          </h3>
          <button class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="dialogVisible = false">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
          </button>
        </div>
        <div class="px-6 py-4 flex-1 overflow-y-auto">
          <!-- File (add only) -->
          <div v-if="!editMode" class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ $t('sticker.file') }}
            </label>
            <ImageDropzone
              v-model="form.file"
              :title-text="$t('dropzone.title')"
              :subtitle-text="$t('dropzone.subtitle')"
              :selected-prefix="$t('dropzone.selected_prefix')"
              :selected-hint="$t('dropzone.selected_hint')"
            />
          </div>
          <!-- ID (add editable / edit read-only) -->
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">ID</label>
            <input
              v-if="!editMode"
              v-model="form.id"
              type="text"
              class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
              :placeholder="$t('sticker.name')"
            />
            <input
              v-else
              :value="form.id"
              type="text"
              disabled
              class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 cursor-not-allowed"
            />
          </div>
          <!-- Description -->
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ $t('sticker.description') }}
            </label>
            <input
              v-model="form.desc"
              type="text"
              class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
              :placeholder="$t('sticker.description')"
            />
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button
            class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            @click="dialogVisible = false"
          >
            {{ $t('sticker.modal_cancel') }}
          </button>
          <button
            class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50"
            :disabled="saving"
            @click="handleSave"
          >
            {{ $t('sticker.modal_save') }}
          </button>
        </div>
      </div>
    </Modal>

    <ConfirmModal
      ref="confirmModalRef"
      :title="confirmTitle"
      :message="confirmMessage"
      :cancel-text="t('sticker.modal_cancel')"
      :confirm-text="t('common.delete')"
      @confirm="onConfirmDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { notify } from '@/composables/useNotification'
import {
  getStickers,
  updateSticker,
  deleteSticker as apiDeleteSticker,
  uploadSticker,
} from '@/api/sticker'
import Modal from '@/components/common/Modal.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
import ImageDropzone from '@/components/common/ImageDropzone.vue'
import type { StickerItem } from '@/types'

const { t } = useI18n()

const confirmModalRef = ref<InstanceType<typeof ConfirmModal>>()

const stickers = ref<StickerItem[]>([])
const loadError = ref(false)
const dialogVisible = ref(false)
const editMode = ref(false)
const saving = ref(false)

const confirmTitle = ref('')
const confirmMessage = ref('')
let deleteTargetId: string | null = null

const form = ref({
  id: '',
  path: '',
  desc: '',
  file: null as File | null,
})

async function loadStickers() {
  try {
    const res = await getStickers()
    stickers.value = Array.isArray(res.data) ? res.data : []
    loadError.value = false
  } catch (e) {
    console.error('Failed to load stickers:', e)
    stickers.value = []
    loadError.value = true
  }
}

function openCreateDialog() {
  editMode.value = false
  form.value = { id: '', path: '', desc: '', file: null }
  dialogVisible.value = true
}

function openEditDialog(sticker: StickerItem) {
  editMode.value = true
  form.value = { id: sticker.id, path: sticker.path, desc: sticker.desc, file: null }
  dialogVisible.value = true
}

async function handleSave() {
  if (!editMode.value) {
    if (!form.value.file) {
      notify(t('sticker.file_required'), 'warning')
      return
    }
    saving.value = true
    try {
      const id = form.value.id?.trim() || undefined
      await uploadSticker(form.value.file, id, form.value.desc || undefined)
      dialogVisible.value = false
      notify(t('sticker.upload_success'), 'success')
      await loadStickers()
    } catch (error: any) {
      notify(t('sticker.upload_failed') + (error?.message ? ': ' + error.message : ''), 'error')
    } finally {
      saving.value = false
    }
  } else {
    saving.value = true
    try {
      await updateSticker(form.value.id, { desc: form.value.desc })
      dialogVisible.value = false
      notify(t('sticker.save_success'), 'success')
      await loadStickers()
    } catch (error: any) {
      notify(t('sticker.save_failed') + (error?.message ? ': ' + error.message : ''), 'error')
    } finally {
      saving.value = false
    }
  }
}

function handleDelete(id: string) {
  deleteTargetId = id
  confirmTitle.value = t('sticker.delete_confirm_title')
  confirmMessage.value = t('sticker.delete_confirm_message')
  confirmModalRef.value?.open()
}

async function onConfirmDelete() {
  if (!deleteTargetId) return
  const id = deleteTargetId
  deleteTargetId = null
  try {
    await apiDeleteSticker(id)
    notify(t('sticker.delete_success'), 'success')
    await loadStickers()
  } catch (error: any) {
    notify(t('sticker.delete_failed') + (error?.message ? ': ' + error.message : ''), 'error')
  }
}

onMounted(() => {
  loadStickers()
})
</script>
