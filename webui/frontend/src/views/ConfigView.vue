<template>
  <div class="flex flex-col gap-5 pb-8">
    <!-- Toolbar -->
    <div class="flex items-center justify-between gap-3 flex-wrap">
      <div class="text-lg font-semibold text-gray-800 dark:text-gray-100">
        {{ $t('pages.configuration.title') }}
      </div>

      <div class="flex items-center gap-1.5 flex-wrap">
        <el-input
          ref="searchInputRef"
          v-model="searchTerm"
          :placeholder="$t('configuration.search_placeholder')"
          :aria-label="$t('configuration.search_aria_label')"
          size="small"
          clearable
          :prefix-icon="Search"
          style="width: 260px;"
        />
        <el-button size="small" text bg :disabled="undoStack.length === 0" @click="undo" :aria-label="$t('configuration.undo_aria')" :title="$t('configuration.undo_aria')">
          <el-icon><RefreshLeft /></el-icon>
        </el-button>
        <el-button size="small" text bg :disabled="redoStack.length === 0" @click="redo" :aria-label="$t('configuration.redo_aria')" :title="$t('configuration.redo_aria')">
          <el-icon><RefreshRight /></el-icon>
        </el-button>
        <el-button size="small" text bg :loading="loading" :disabled="modifiedFields.size > 0" @click="loadConfig" :aria-label="$t('configuration.reset_aria')" :title="$t('configuration.reset_aria')">
          <el-icon><Refresh /></el-icon>
        </el-button>
        <el-button size="small" text bg @click="expandAll" :aria-label="$t('configuration.expand_all_aria')" :title="$t('configuration.expand_all_aria')">
          <el-icon><FullScreen /></el-icon>
        </el-button>
        <el-button size="small" text bg @click="collapseAll" :aria-label="$t('configuration.collapse_all_aria')" :title="$t('configuration.collapse_all_aria')">
          <el-icon><Minus /></el-icon>
        </el-button>
        <el-button type="primary" size="small" :loading="saving" :disabled="modifiedFields.size === 0" @click="handleSave">
          <el-icon class="mr-1"><Check /></el-icon>
          {{ $t('configuration.save') }}
          <el-tag v-if="modifiedFields.size > 0" size="small" round effect="dark" type="warning" class="ml-2">
            {{ modifiedFields.size }}
          </el-tag>
        </el-button>
      </div>
    </div>

    <!-- Groups -->
    <div
      v-for="group in filteredAllGroups"
      :key="group.id"
      class="glass-card rounded-xl overflow-hidden"
      :class="{ 'config-group-modified': groupHasModified(group) }"
    >
      <!-- Group Header -->
      <div
        class="config-group-header flex items-center justify-between px-5 py-3.5 cursor-pointer select-none"
        role="button"
        tabindex="0"
        :aria-expanded="!collapsedGroups.has(group.id)"
        @click="toggleGroup(group.id)"
        @keydown.enter.prevent="toggleGroup(group.id)"
        @keydown.space.prevent="toggleGroup(group.id)"
      >
        <div class="flex items-center gap-3 min-w-0">
          <el-icon :size="18" class="config-group-icon shrink-0">
            <component :is="group.icon" />
          </el-icon>
          <div class="min-w-0">
            <h4 class="text-sm font-semibold text-gray-800 dark:text-gray-100 flex items-center">
              {{ $t(group.labelKey, group.labelFallback) }}
              <span
                v-if="groupHasModified(group)"
                class="inline-block w-2 h-2 bg-amber-500 rounded-full ml-2"
                aria-hidden="true"
              ></span>
            </h4>
            <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">
              {{ $t(group.descKey, group.descFallback) }}
            </p>
          </div>
        </div>
        <el-icon
          :class="{ 'rotate-180': !collapsedGroups.has(group.id) }"
          class="transition-transform text-gray-500 dark:text-gray-400 shrink-0 ml-2"
        >
          <ArrowDown />
        </el-icon>
      </div>

      <!-- Horizontal layout (model selects: label+desc left, selects right) -->
      <div
        v-if="group.layout === 'horizontal'"
        v-show="!collapsedGroups.has(group.id)"
        class="config-group-body px-5 py-3 divide-y divide-[rgba(148,163,184,0.14)]"
      >
        <div
          v-for="field in getVisibleFields(group)"
          :key="field.key"
          class="config-row flex items-center gap-4 py-3 flex-wrap"
          :class="{ 'config-field-modified': modifiedFields.has(field.key) }"
        >
          <div class="flex-1 min-w-0 min-w-[180px]">
            <label class="text-sm font-medium text-gray-700 dark:text-gray-300 flex items-center gap-1" :title="field.key">
              <span class="truncate">{{ $t(field.labelKey, field.labelFallback) }}</span>
              <span v-if="modifiedFields.has(field.key)" class="text-amber-500" aria-hidden="true">●</span>
            </label>
            <p v-if="field.hintKey" class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              {{ $t(field.hintKey, field.hintFallback) }}
            </p>
          </div>
          <div class="flex gap-2 shrink-0">
            <el-select
              :model-value="getModelProvider(field.key)"
              size="small"
              style="width: 160px;"
              :placeholder="$t('configuration.select_provider')"
              @change="(v: string) => setModelProvider(field.key, v, field.modelType)"
            >
              <el-option value="" :label="$t('configuration.none')" />
              <el-option
                v-for="p in providers"
                :key="p.id"
                :label="p.name || p.id"
                :value="p.id"
              />
            </el-select>
            <el-select
              :model-value="getModelId(field.key)"
              size="small"
              style="width: 220px;"
              :placeholder="$t('configuration.select_model')"
              @change="(v: string) => setModelId(field.key, v)"
            >
              <el-option value="" :label="$t('configuration.none')" />
              <el-option
                v-for="modelId in getAvailableModels(field.key, field.modelType)"
                :key="modelId"
                :label="modelId"
                :value="modelId"
              />
            </el-select>
          </div>
          <p
            v-if="validationErrors[field.key]"
            class="w-full text-xs text-red-500 dark:text-red-400"
          >
            {{ validationErrors[field.key] }}
          </p>
        </div>
      </div>

      <!-- Grid layout (regular fields: 2-col, hint below input) -->
      <div
        v-else
        v-show="!collapsedGroups.has(group.id)"
        class="config-group-body px-5 py-5 grid grid-cols-1 xl:grid-cols-2 gap-x-6 gap-y-5"
      >
        <div
          v-for="field in getVisibleFields(group)"
          :key="field.key"
          class="config-field flex flex-col gap-1.5"
          :class="{ 'config-field-modified': modifiedFields.has(field.key) }"
        >
          <label class="text-sm font-medium text-gray-700 dark:text-gray-300 flex items-center gap-1" :title="field.key">
            <span class="truncate">{{ $t(field.labelKey, field.labelFallback) }}</span>
            <span v-if="modifiedFields.has(field.key)" class="text-amber-500" aria-hidden="true">●</span>
          </label>

          <!-- Integer -->
          <el-input-number
            v-if="field.type === 'integer'"
            :model-value="getFieldValue(field.key)"
            size="small"
            class="w-full"
            controls-position="right"
            :min="field.validation?.min"
            :max="field.validation?.max"
            :step="1"
            @update:model-value="(v: number | undefined) => setFieldValue(field.key, v ?? field.default)"
          />

          <!-- Float -->
          <el-input-number
            v-else-if="field.type === 'float'"
            :model-value="getFieldValue(field.key)"
            size="small"
            class="w-full"
            controls-position="right"
            :min="field.validation?.min"
            :max="field.validation?.max"
            :step="0.1"
            :precision="2"
            @update:model-value="(v: number | undefined) => setFieldValue(field.key, v ?? field.default)"
          />

          <!-- Boolean -->
          <el-switch
            v-else-if="field.type === 'boolean'"
            :model-value="getFieldValue(field.key)"
            class="self-start"
            @change="(v: boolean | string | number) => setFieldValue(field.key, v)"
          />

          <!-- String -->
          <el-input
            v-else
            :model-value="getFieldValue(field.key)"
            size="small"
            :placeholder="$t(field.hintKey, field.hintFallback)"
            @update:model-value="(v: string) => setFieldValue(field.key, v)"
          />

          <p v-if="field.hintKey" class="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
            {{ $t(field.hintKey, field.hintFallback) }}
          </p>

          <p v-if="validationErrors[field.key]" class="text-xs text-red-500 dark:text-red-400">
            {{ validationErrors[field.key] }}
          </p>
        </div>
      </div>
    </div>

    <!-- Bottom keyboard hints -->
    <div class="flex items-center justify-center gap-5 pt-2 text-xs text-gray-500 dark:text-gray-400">
      <span><kbd class="kbd-hint">Ctrl+Z</kbd> {{ $t('configuration.shortcut_undo') }}</span>
      <span><kbd class="kbd-hint">Ctrl+Shift+Z</kbd> {{ $t('configuration.shortcut_redo') }}</span>
      <span><kbd class="kbd-hint">Ctrl+S</kbd> {{ $t('configuration.shortcut_save') }}</span>
      <span><kbd class="kbd-hint">/</kbd> {{ $t('configuration.shortcut_search') }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowDown,
  Search,
  Setting,
  Tools,
  Picture,
  MagicStick,
  RefreshLeft,
  RefreshRight,
  Refresh,
  FullScreen,
  Minus,
  Check,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getConfiguration, saveConfiguration } from '@/api/config'

const { t } = useI18n()

const searchTerm = ref('')
const saving = ref(false)
const loading = ref(false)
const searchInputRef = ref<any>(null)

// Data
const originalData = ref<Record<string, any>>({})
const currentData = ref<Record<string, any>>({})
const providers = ref<Array<{ id: string; name: string }>>([])
const providerModels = ref<Record<string, Record<string, any>>>({})

// Undo/Redo
interface UndoEntry { key: string; oldValue: any; newValue: any }
const undoStack = ref<UndoEntry[]>([])
const redoStack = ref<UndoEntry[]>([])

// State
const collapsedGroups = ref(new Set<string>())
const modifiedFields = ref(new Set<string>())
const validationErrors = ref<Record<string, string>>({})

// Schema
interface ConfigField {
  key: string
  labelKey: string
  labelFallback: string
  hintKey: string
  hintFallback: string
  type: string
  default?: any
  modelType?: string
  validation?: { min?: number; max?: number; required?: boolean }
}

interface ConfigGroup {
  id: string
  labelKey: string
  labelFallback: string
  descKey: string
  descFallback: string
  icon: Component
  layout?: 'grid' | 'horizontal'
  fields: ConfigField[]
}

const allGroups: ConfigGroup[] = [
  {
    id: 'bot',
    labelKey: 'configuration.groups.bot',
    labelFallback: 'Bot Settings',
    descKey: 'configuration.groups.bot_desc',
    descFallback: 'Core bot behavior parameters',
    icon: Setting,
    fields: [
      { key: 'bot_config.bot.max_memory_length', labelKey: 'configuration.message.max_memory_length', labelFallback: 'Max Memory Length', hintKey: 'configuration.hints.max_memory_length', hintFallback: 'Maximum number of messages retained in context window', type: 'integer', default: 50, validation: { min: 1, max: 9999, required: true } },
      { key: 'bot_config.bot.max_message_interval', labelKey: 'configuration.message.max_message_interval', labelFallback: 'Max Message Interval', hintKey: 'configuration.hints.max_message_interval', hintFallback: 'Maximum seconds to wait before processing buffered messages', type: 'float', default: 5, validation: { min: 0.1, max: 300, required: true } },
      { key: 'bot_config.bot.max_buffer_messages', labelKey: 'configuration.message.max_buffer_messages', labelFallback: 'Max Buffer Messages', hintKey: 'configuration.hints.max_buffer_messages', hintFallback: 'Maximum number of messages to buffer before processing', type: 'integer', default: 5, validation: { min: 1, max: 100, required: true } },
      { key: 'bot_config.bot.min_message_delay', labelKey: 'configuration.message.min_message_delay', labelFallback: 'Min Message Delay', hintKey: 'configuration.hints.min_message_delay', hintFallback: 'Minimum delay in seconds before sending a reply', type: 'float', default: 1, validation: { min: 0, max: 60, required: true } },
      { key: 'bot_config.bot.max_message_delay', labelKey: 'configuration.message.max_message_delay', labelFallback: 'Max Message Delay', hintKey: 'configuration.hints.max_message_delay', hintFallback: 'Maximum delay in seconds before sending a reply', type: 'float', default: 5, validation: { min: 0, max: 60, required: true } },
    ],
  },
  {
    id: 'agent',
    labelKey: 'configuration.groups.agent',
    labelFallback: 'Agent Settings',
    descKey: 'configuration.groups.agent_desc',
    descFallback: 'Agent and tool execution parameters',
    icon: Tools,
    fields: [
      { key: 'bot_config.agent.max_tool_loop', labelKey: 'configuration.message.max_tool_loop', labelFallback: 'Max Tool Loop', hintKey: 'configuration.hints.max_tool_loop', hintFallback: 'Maximum number of tool call iterations per response', type: 'integer', default: 5, validation: { min: 1, max: 50, required: true } },
    ],
  },
  {
    id: 'selfie',
    labelKey: 'configuration.groups.selfie',
    labelFallback: 'Appearance',
    descKey: 'configuration.groups.selfie_desc',
    descFallback: 'Bot appearance reference settings',
    icon: Picture,
    fields: [
      { key: 'bot_config.selfie.path', labelKey: 'configuration.message.selfie_path', labelFallback: 'Selfie Path', hintKey: 'configuration.hints.selfie_path', hintFallback: 'Path to the bot appearance reference image', type: 'string', default: '', validation: { required: false } },
    ],
  },
  {
    id: 'models',
    labelKey: 'configuration.groups.models',
    labelFallback: 'Default Models',
    descKey: 'configuration.groups.models_desc',
    descFallback: 'Select default provider and model for each capability',
    icon: MagicStick,
    layout: 'horizontal',
    fields: [
      { key: 'models.default_llm', labelKey: 'configuration.model.default_llm', labelFallback: 'Default LLM', hintKey: 'configuration.model.default_llm_desc', hintFallback: 'Main chat model.', type: 'model_select', modelType: 'llm' },
      { key: 'models.default_fast_llm', labelKey: 'configuration.model.default_fast_llm', labelFallback: 'Default Fast LLM', hintKey: 'configuration.model.default_fast_llm_desc', hintFallback: 'Fast reply model.', type: 'model_select', modelType: 'llm' },
      { key: 'models.default_vlm', labelKey: 'configuration.model.default_vlm', labelFallback: 'Default VLM', hintKey: 'configuration.model.default_vlm_desc', hintFallback: 'Vision-language model.', type: 'model_select', modelType: 'llm' },
      { key: 'models.default_tts', labelKey: 'configuration.model.default_tts', labelFallback: 'Default TTS', hintKey: 'configuration.model.default_tts_desc', hintFallback: 'Text to speech.', type: 'model_select', modelType: 'tts' },
      { key: 'models.default_stt', labelKey: 'configuration.model.default_stt', labelFallback: 'Default STT', hintKey: 'configuration.model.default_stt_desc', hintFallback: 'Speech to text.', type: 'model_select', modelType: 'stt' },
      { key: 'models.default_image', labelKey: 'configuration.model.default_image', labelFallback: 'Default Image', hintKey: 'configuration.model.default_image_desc', hintFallback: 'Image generation.', type: 'model_select', modelType: 'image' },
      { key: 'models.default_embedding', labelKey: 'configuration.model.default_embedding', labelFallback: 'Default Embedding', hintKey: 'configuration.model.default_embedding_desc', hintFallback: 'Embedding model.', type: 'model_select', modelType: 'embedding' },
      { key: 'models.default_rerank', labelKey: 'configuration.model.default_rerank', labelFallback: 'Default Rerank', hintKey: 'configuration.model.default_rerank_desc', hintFallback: 'Rerank model.', type: 'model_select', modelType: 'rerank' },
      { key: 'models.default_video', labelKey: 'configuration.model.default_video', labelFallback: 'Default Video', hintKey: 'configuration.model.default_video_desc', hintFallback: 'Video generation.', type: 'model_select', modelType: 'video' },
    ],
  },
]

// Nested value helpers
function getNestedValue(obj: any, path: string): any {
  return path.split('.').reduce((o, k) => (o && o[k] !== undefined) ? o[k] : undefined, obj)
}

function setNestedValue(obj: any, path: string, value: any) {
  const keys = path.split('.')
  const lastKey = keys.pop()!
  const target = keys.reduce((o, k) => {
    if (!(k in o) || typeof o[k] !== 'object' || o[k] === null) o[k] = {}
    return o[k]
  }, obj)
  target[lastKey] = value
}

function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj))
}

// Field access
function getFieldValue(key: string): any {
  return getNestedValue(currentData.value, key)
}

function setFieldValue(key: string, value: any) {
  const oldValue = getNestedValue(currentData.value, key)
  if (oldValue === value) return

  undoStack.value.push({ key, oldValue, newValue: value })
  redoStack.value = []

  setNestedValue(currentData.value, key, value)

  const originalValue = getNestedValue(originalData.value, key)
  if (value === originalValue) {
    modifiedFields.value.delete(key)
  } else {
    modifiedFields.value.add(key)
  }

  validateField(key)
}

// Model reference helpers
//
// A `model_select` field stores its value as `"<provider>:<model>"` in config,
// and we never persist a bare `"<provider>:"` — that would be a half-configured
// entry that slips past save. But the UI needs to support the transient state
// where the user has picked a provider and is about to pick a model. We keep
// that state in `pendingProviders` (not persisted) so the provider dropdown
// stays selected and the model dropdown has options to show.
const pendingProviders = ref<Record<string, string>>({})

function parseModelReference(ref: string): { providerId: string; modelId: string } {
  if (!ref || typeof ref !== 'string') return { providerId: '', modelId: '' }
  const parts = ref.split(':')
  if (parts.length === 1) return { providerId: parts[0], modelId: '' }
  return { providerId: parts[0], modelId: parts.slice(1).join(':') }
}

function getModelProvider(key: string): string {
  const persisted = parseModelReference(getFieldValue(key) || '').providerId
  return persisted || pendingProviders.value[key] || ''
}

function getModelId(key: string): string {
  return parseModelReference(getFieldValue(key) || '').modelId
}

function setModelProvider(key: string, providerId: string, _modelType?: string) {
  if (!providerId) {
    delete pendingProviders.value[key]
    setFieldValue(key, '')
    // If the persisted value was already '', setFieldValue is a no-op and
    // won't run validation — call it explicitly so any stale error clears.
    validateField(key)
    return
  }
  // Switching provider invalidates any previously chosen model, so we clear
  // the persisted value and park the provider in pending state until the user
  // picks a model. `validateField` will flag this as required-but-missing.
  pendingProviders.value[key] = providerId
  setFieldValue(key, '')
  validateField(key)
}

function setModelId(key: string, modelId: string) {
  const providerId = getModelProvider(key)
  if (!providerId || !modelId) {
    delete pendingProviders.value[key]
    setFieldValue(key, '')
    validateField(key)
    return
  }
  delete pendingProviders.value[key]
  setFieldValue(key, `${providerId}:${modelId}`)
}

function getAvailableModels(key: string, modelType?: string): string[] {
  const providerId = getModelProvider(key)
  if (!providerId || !modelType) return []
  const providerConfig = providerModels.value[providerId] || {}
  const typeConfig = providerConfig[modelType] || {}
  if (Array.isArray(typeConfig)) return typeConfig
  return Object.keys(typeConfig)
}

// Undo/Redo
function undo() {
  const entry = undoStack.value.pop()
  if (!entry) return
  redoStack.value.push(entry)
  setNestedValue(currentData.value, entry.key, entry.oldValue)
  const originalValue = getNestedValue(originalData.value, entry.key)
  if (entry.oldValue === originalValue) {
    modifiedFields.value.delete(entry.key)
  } else {
    modifiedFields.value.add(entry.key)
  }
  validateField(entry.key)
}

function redo() {
  const entry = redoStack.value.pop()
  if (!entry) return
  undoStack.value.push(entry)
  setNestedValue(currentData.value, entry.key, entry.newValue)
  const originalValue = getNestedValue(originalData.value, entry.key)
  if (entry.newValue === originalValue) {
    modifiedFields.value.delete(entry.key)
  } else {
    modifiedFields.value.add(entry.key)
  }
  validateField(entry.key)
}

// Validation
function validateField(key: string) {
  const allFields = allGroups.flatMap(g => g.fields)
  const field = allFields.find(f => f.key === key)
  // A model_select with a provider but no model is incomplete — flag it even
  // though there's no explicit `validation` block on the schema. Also catches
  // the transient pending state where the user picked a provider but hasn't
  // picked a model yet.
  if (field?.type === 'model_select') {
    const { providerId: persistedProvider, modelId } = parseModelReference(getFieldValue(key) || '')
    const effectiveProvider = persistedProvider || pendingProviders.value[key] || ''
    if (effectiveProvider && !modelId) {
      validationErrors.value[key] = t('configuration.validation.required')
      return
    }
  }
  if (!field?.validation) {
    delete validationErrors.value[key]
    return
  }
  const value = getFieldValue(key)
  const v = field.validation
  if (v.required && (value === null || value === undefined || value === '')) {
    validationErrors.value[key] = t('configuration.validation.required')
    return
  }
  if (v.min !== undefined && typeof value === 'number' && value < v.min) {
    validationErrors.value[key] = t('configuration.validation.min', { min: v.min })
    return
  }
  if (v.max !== undefined && typeof value === 'number' && value > v.max) {
    validationErrors.value[key] = t('configuration.validation.max', { max: v.max })
    return
  }
  delete validationErrors.value[key]
}

// Search & filtering
function fieldMatchesSearch(field: ConfigField): boolean {
  if (!searchTerm.value) return true
  const term = searchTerm.value.toLowerCase()
  return (
    field.labelFallback.toLowerCase().includes(term) ||
    field.hintFallback.toLowerCase().includes(term) ||
    field.key.toLowerCase().includes(term) ||
    t(field.labelKey, '').toLowerCase().includes(term) ||
    t(field.hintKey, '').toLowerCase().includes(term)
  )
}

const filteredAllGroups = computed(() => {
  if (!searchTerm.value) return allGroups
  return allGroups.filter(group =>
    group.fields.some(f => fieldMatchesSearch(f))
  )
})

function getVisibleFields(group: ConfigGroup): ConfigField[] {
  if (!searchTerm.value) return group.fields
  return group.fields.filter(f => fieldMatchesSearch(f))
}

function groupHasModified(group: ConfigGroup): boolean {
  return group.fields.some(f => modifiedFields.value.has(f.key))
}

function toggleGroup(id: string) {
  if (collapsedGroups.value.has(id)) {
    collapsedGroups.value.delete(id)
  } else {
    collapsedGroups.value.add(id)
  }
}

function expandAll() {
  collapsedGroups.value.clear()
}

function collapseAll() {
  collapsedGroups.value = new Set(allGroups.map(g => g.id))
}

// Save
async function handleSave() {
  if (saving.value) return
  if (modifiedFields.value.size === 0) {
    ElMessage.info(t('configuration.no_changes'))
    return
  }
  const allFields = allGroups.flatMap(g => g.fields)
  allFields.forEach(f => validateField(f.key))
  if (Object.keys(validationErrors.value).length > 0) {
    ElMessage.error(t('configuration.validation_failed'))
    return
  }
  saving.value = true
  const snapshot = deepClone(currentData.value)
  try {
    await saveConfiguration(snapshot)
    originalData.value = snapshot
    const allFieldKeys = allFields.map(f => f.key)
    const stillModified = new Set<string>()
    for (const key of allFieldKeys) {
      const current = getNestedValue(currentData.value, key)
      const saved = getNestedValue(snapshot, key)
      if (current !== saved) stillModified.add(key)
    }
    modifiedFields.value = stillModified
    if (stillModified.size === 0) {
      undoStack.value = []
      redoStack.value = []
    }
    ElMessage.success(t('configuration.save_success'))
  } catch (err) {
    console.error('Save failed:', err)
    ElMessage.error(t('configuration.save_failed'))
  } finally {
    saving.value = false
  }
}

async function loadConfig() {
  loading.value = true
  try {
    const res = await getConfiguration()
    const data = res.data
    originalData.value = deepClone(data.configuration || {})
    currentData.value = deepClone(originalData.value)
    providers.value = data.providers || []
    providerModels.value = data.provider_models || {}

    // Ensure defaults
    const allFields = allGroups.flatMap(g => g.fields)
    allFields.forEach(field => {
      if (field.default !== undefined) {
        const current = getNestedValue(currentData.value, field.key)
        if (current === undefined || current === null) {
          setNestedValue(currentData.value, field.key, field.default)
          setNestedValue(originalData.value, field.key, field.default)
        }
      }
    })
    // Reset dirty state since we just re-synced
    modifiedFields.value.clear()
    undoStack.value = []
    redoStack.value = []
    pendingProviders.value = {}
    validationErrors.value = {}
  } catch (e) {
    console.error('Failed to load configuration:', e)
    ElMessage.error(t('configuration.load_failed'))
  } finally {
    loading.value = false
  }
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable
}

function focusSearch() {
  // Element Plus el-input exposes .focus() on the ref
  nextTick(() => {
    searchInputRef.value?.focus?.()
  })
}

// Keyboard shortcuts
function handleKeydown(e: KeyboardEvent) {
  const key = e.key.toLowerCase()
  // Ctrl/Cmd+S saves even from inputs
  if ((e.ctrlKey || e.metaKey) && key === 's') {
    e.preventDefault()
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
    handleSave()
    return
  }
  // "/" focuses search — skip when already in an input
  if (key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey && !isEditableTarget(e.target)) {
    e.preventDefault()
    focusSearch()
    return
  }
  if (isEditableTarget(e.target)) return
  if ((e.ctrlKey || e.metaKey) && key === 'z' && !e.shiftKey) {
    e.preventDefault()
    undo()
  } else if ((e.ctrlKey || e.metaKey) && (key === 'y' || (key === 'z' && e.shiftKey))) {
    e.preventDefault()
    redo()
  }
}

onMounted(async () => {
  document.addEventListener('keydown', handleKeydown)
  await loadConfig()
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
.config-group-header {
  transition: background-color 0.18s ease;
}

.config-group-header:hover {
  background-color: rgba(0, 0, 0, 0.025);
}

:global(.dark) .config-group-header:hover {
  background-color: rgba(255, 255, 255, 0.04);
}

.config-group-icon {
  color: #3b5fd5;
}

:global(.dark) .config-group-icon {
  color: #7cb4ff;
}

.config-group-body {
  border-top: 1px solid rgba(148, 163, 184, 0.2);
}

.config-group-modified {
  position: relative;
}

.config-group-modified::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: linear-gradient(180deg, #f59e0b, #ef4444);
  border-top-left-radius: 12px;
  border-bottom-left-radius: 12px;
  pointer-events: none;
}

.config-field,
.config-row {
  position: relative;
  transition: padding-left 0.18s ease;
}

.config-field-modified {
  padding-left: 10px;
  border-left: 2px solid rgba(245, 158, 11, 0.55);
}

/* Keyboard hint badges */
.kbd-hint {
  display: inline-block;
  padding: 1px 6px;
  margin: 0 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.4;
  color: #475569;
  background: rgba(148, 163, 184, 0.18);
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 4px;
  vertical-align: middle;
}

:global(.dark) .kbd-hint {
  color: #cbd5e1;
  background: rgba(148, 163, 184, 0.15);
  border-color: rgba(148, 163, 184, 0.25);
}
</style>
