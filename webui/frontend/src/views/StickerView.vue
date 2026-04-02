<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div></div>
      <el-button type="primary" size="small" @click="openAddDialog">
        + {{ $t('sticker.add') }}
      </el-button>
    </div>

    <div v-if="stickers.length === 0" class="text-center py-12 text-gray-400">
      <el-icon :size="48"><Picture /></el-icon>
      <p class="mt-2 text-sm">{{ $t('sticker.no_stickers') }}</p>
    </div>

    <div v-else class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
      <div v-for="sticker in stickers" :key="sticker.id" class="glass-card rounded-lg overflow-hidden flex flex-col">
        <div class="relative bg-gray-100 dark:bg-gray-800 flex items-center justify-center" style="padding-top: 100%;">
          <img
            v-if="sticker.path"
            :src="`/sticker/${encodeURIComponent(sticker.path)}`"
            :alt="sticker.desc || `Sticker ${sticker.id}`"
            class="absolute inset-0 w-full h-full object-contain"
          />
        </div>
        <div class="p-4 flex-1 flex flex-col">
          <div class="flex items-center justify-between mb-2">
            <span class="text-sm font-semibold text-gray-800 dark:text-gray-100">#{{ sticker.id }}</span>
          </div>
          <p class="text-sm text-gray-600 dark:text-gray-300 truncate" :title="sticker.desc">{{ sticker.desc }}</p>
          <div class="mt-3 flex justify-end gap-3">
            <el-button size="small" @click="openEditDialog(sticker)">{{ $t('sticker.edit') }}</el-button>
            <el-button size="small" type="danger" @click="handleDelete(sticker.id)">{{ $t('sticker.delete') }}</el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Sticker Dialog -->
    <el-dialog v-model="addDialogVisible" :title="$t('sticker.add')" width="500">
      <el-form label-position="top">
        <el-form-item :label="$t('sticker.description')">
          <el-input v-model="addForm.desc" />
        </el-form-item>
        <el-form-item :label="$t('sticker.file')">
          <el-upload
            drag
            action=""
            :auto-upload="false"
            :limit="1"
            accept="image/*"
            :on-change="onAddFileChange"
          >
            <el-icon :size="48"><UploadFilled /></el-icon>
            <div class="el-upload__text">{{ $t('sticker.upload_hint') }}</div>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addDialogVisible = false">{{ $t('sticker.cancel') }}</el-button>
        <el-button type="primary" :loading="uploading" @click="handleAdd">{{ $t('sticker.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- Edit Sticker Dialog -->
    <el-dialog v-model="editDialogVisible" :title="$t('sticker.edit')" width="500">
      <el-form label-position="top">
        <el-form-item label="ID">
          <el-input :model-value="editForm.id" disabled />
        </el-form-item>
        <el-form-item :label="$t('sticker.path')">
          <el-input :model-value="editForm.path" disabled />
        </el-form-item>
        <el-form-item :label="$t('sticker.description')">
          <el-input v-model="editForm.desc" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">{{ $t('sticker.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="handleEdit">{{ $t('sticker.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Picture, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { getStickers, updateSticker, deleteSticker as apiDeleteSticker, uploadSticker } from '@/api/sticker'
import type { StickerItem } from '@/types'

const { t } = useI18n()
const stickers = ref<StickerItem[]>([])

// Add
const addDialogVisible = ref(false)
const addForm = ref({ desc: '' })
const addFile = ref<File | null>(null)
const uploading = ref(false)

// Edit
const editDialogVisible = ref(false)
const editForm = ref({ id: '', path: '', desc: '' })
const saving = ref(false)

async function loadStickers() {
  try {
    const res = await getStickers()
    stickers.value = Array.isArray(res.data) ? res.data : []
  } catch (e) { console.error('Failed to load stickers:', e) }
}

function openAddDialog() {
  addForm.value = { desc: '' }
  addFile.value = null
  addDialogVisible.value = true
}

function onAddFileChange(file: UploadFile) {
  addFile.value = file.raw || null
}

async function handleAdd() {
  if (!addFile.value) {
    ElMessage.error(t('sticker.file_required'))
    return
  }
  uploading.value = true
  try {
    await uploadSticker(addFile.value, undefined, addForm.value.desc || undefined)
    addDialogVisible.value = false
    ElMessage.success(t('sticker.upload_success'))
    await loadStickers()
  } catch {
    ElMessage.error(t('sticker.upload_failed'))
  } finally {
    uploading.value = false
  }
}

function openEditDialog(sticker: StickerItem) {
  editForm.value = { id: sticker.id, path: sticker.path, desc: sticker.desc }
  editDialogVisible.value = true
}

async function handleEdit() {
  saving.value = true
  try {
    await updateSticker(editForm.value.id, { desc: editForm.value.desc })
    editDialogVisible.value = false
    ElMessage.success(t('sticker.save_success'))
    await loadStickers()
  } catch {
    ElMessage.error(t('sticker.save_failed'))
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: string) {
  try {
    await ElMessageBox.confirm(t('sticker.delete_confirm'), t('sticker.delete'), { type: 'warning' })
  } catch {
    return
  }
  try {
    await apiDeleteSticker(id)
    ElMessage.success(t('sticker.delete_success'))
    await loadStickers()
  } catch {
    ElMessage.error(t('sticker.delete_failed'))
  }
}

onMounted(() => {
  loadStickers()
})
</script>
