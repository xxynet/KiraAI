<template>
  <div>
    <!-- Toolbar -->
    <div class="flex items-center justify-between mb-4 flex-wrap gap-2">
      <div class="flex items-center gap-2">
        <el-input
          v-model="searchTerm"
          :placeholder="$t('configuration.search_placeholder')"
          size="small"
          clearable
          :prefix-icon="Search"
          style="width: 260px;"
        />
        <el-button size="small" :disabled="undoStack.length === 0" @click="undo" title="Ctrl+Z">
          ↩ {{ $t('configuration.undo') }}
        </el-button>
        <el-button size="small" :disabled="redoStack.length === 0" @click="redo" title="Ctrl+Y">
          ↪ {{ $t('configuration.redo') }}
        </el-button>
      </div>
      <div class="flex items-center gap-2">
        <el-tag v-if="modifiedFields.size > 0" type="warning" size="small">
          {{ modifiedFields.size }} {{ $t('configuration.changes') }}
        </el-tag>
        <el-button type="primary" size="small" :loading="saving" :disabled="modifiedFields.size === 0" @click="handleSave">
          {{ $t('configuration.save') }}
        </el-button>
        <el-button size="small" :disabled="modifiedFields.size === 0" @click="resetAll">
          {{ $t('configuration.reset') }}
        </el-button>
      </div>
    </div>

    <!-- Tabs for Message Config and Model Config -->
    <el-tabs v-model="activeTab">
      <!-- Message Configuration Tab -->
      <el-tab-pane :label="$t('configuration.message_tab')" name="message">
        <div class="space-y-4">
          <div
            v-for="group in filteredGroups"
            :key="group.id"
            class="glass-card rounded-lg overflow-hidden"
          >
            <!-- Group Header -->
            <div
              class="flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-gray-800 cursor-pointer select-none"
              role="button"
              tabindex="0"
              :aria-expanded="!collapsedGroups.has(group.id)"
              @click="toggleGroup(group.id)"
              @keydown.enter.prevent="toggleGroup(group.id)"
              @keydown.space.prevent="toggleGroup(group.id)"
            >
              <div class="flex items-center gap-3">
                <span class="text-gray-500 dark:text-gray-400">{{ group.icon }}</span>
                <div>
                  <h4 class="text-sm font-semibold text-gray-800 dark:text-gray-100">
                    {{ $t(group.labelKey, group.labelFallback) }}
                    <span v-if="groupHasModified(group)" class="inline-block w-2 h-2 bg-amber-400 rounded-full ml-2"></span>
                  </h4>
                  <p class="text-xs text-gray-500">{{ $t(group.descKey, group.descFallback) }}</p>
                </div>
              </div>
              <el-icon :class="{ 'rotate-180': !collapsedGroups.has(group.id) }" class="transition-transform">
                <ArrowDown />
              </el-icon>
            </div>

            <!-- Group Fields -->
            <div v-show="!collapsedGroups.has(group.id)" class="p-4 space-y-4">
              <div
                v-for="field in getVisibleFields(group)"
                :key="field.key"
                class="flex flex-col gap-1"
                :class="{ 'opacity-50': searchTerm && !fieldMatchesSearch(field) }"
              >
                <div class="flex items-center justify-between">
                  <label class="text-sm font-medium text-gray-700 dark:text-gray-300">
                    {{ $t(field.labelKey, field.labelFallback) }}
                    <span v-if="modifiedFields.has(field.key)" class="text-amber-500 ml-1">●</span>
                  </label>
                  <span v-if="field.hintKey" class="text-xs text-gray-400">
                    {{ $t(field.hintKey, field.hintFallback) }}
                  </span>
                </div>

                <!-- Model select type -->
                <div v-if="field.type === 'model_select'" class="flex gap-2">
                  <el-select
                    :model-value="getModelProvider(field.key)"
                    class="flex-1"
                    size="small"
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
                    class="flex-1"
                    size="small"
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

                <!-- Validation error for model_select -->
                <p v-if="field.type === 'model_select' && validationErrors[field.key]" class="text-xs text-red-500">
                  {{ validationErrors[field.key] }}
                </p>

                <!-- Integer type -->
                <el-input-number
                  v-else-if="field.type === 'integer'"
                  :model-value="getFieldValue(field.key)"
                  size="small"
                  :min="field.validation?.min"
                  :max="field.validation?.max"
                  :step="1"
                  @change="(v: number | undefined) => setFieldValue(field.key, v ?? field.default)"
                />

                <!-- Float type -->
                <el-input-number
                  v-else-if="field.type === 'float'"
                  :model-value="getFieldValue(field.key)"
                  size="small"
                  :min="field.validation?.min"
                  :max="field.validation?.max"
                  :step="0.1"
                  :precision="2"
                  @change="(v: number | undefined) => setFieldValue(field.key, v ?? field.default)"
                />

                <!-- Boolean type -->
                <el-switch
                  v-else-if="field.type === 'boolean'"
                  :model-value="getFieldValue(field.key)"
                  @change="(v: boolean | string | number) => setFieldValue(field.key, v)"
                />

                <!-- String type (default) -->
                <el-input
                  v-else
                  :model-value="getFieldValue(field.key)"
                  size="small"
                  @change="(v: string) => setFieldValue(field.key, v)"
                />

                <!-- Validation error -->
                <p v-if="field.type !== 'model_select' && validationErrors[field.key]" class="text-xs text-red-500">
                  {{ validationErrors[field.key] }}
                </p>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- Model Configuration Tab -->
      <el-tab-pane :label="$t('configuration.model_tab')" name="model">
        <div class="space-y-4">
          <div v-for="group in filteredModelGroups" :key="group.id" class="glass-card rounded-lg p-4">
            <h4 class="text-sm font-semibold text-gray-800 dark:text-gray-100 mb-3">
              {{ $t(group.labelKey, group.labelFallback) }}
            </h4>
            <p class="text-xs text-gray-500 mb-4">{{ $t(group.descKey, group.descFallback) }}</p>
            <div class="space-y-4">
              <div v-for="field in getVisibleFields(group)" :key="field.key" class="flex flex-col gap-1">
                <label class="text-sm font-medium text-gray-700 dark:text-gray-300">
                  {{ $t(field.labelKey, field.labelFallback) }}
                  <span v-if="modifiedFields.has(field.key)" class="text-amber-500 ml-1">●</span>
                </label>
                <span class="text-xs text-gray-400 mb-1">{{ $t(field.hintKey, field.hintFallback) }}</span>
                <div class="flex gap-2">
                  <el-select
                    :model-value="getModelProvider(field.key)"
                    class="flex-1"
                    size="small"
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
                    class="flex-1"
                    size="small"
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
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowDown, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getConfiguration, saveConfiguration } from '@/api/config'

const { t } = useI18n()

const activeTab = ref('message')
const searchTerm = ref('')
const saving = ref(false)

// Data
const originalData = ref<Record<string, any>>({})
const currentData = ref<Record<string, any>>({})
const providers = ref<Array<{ id: string; name: string; type: string }>>([])
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
  icon: string
  fields: ConfigField[]
}

const messageGroups: ConfigGroup[] = [
  {
    id: 'bot',
    labelKey: 'configuration.groups.bot',
    labelFallback: 'Bot Settings',
    descKey: 'configuration.groups.bot_desc',
    descFallback: 'Core bot behavior parameters',
    icon: '⚙️',
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
    icon: '🔧',
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
    icon: '🖼️',
    fields: [
      { key: 'bot_config.selfie.path', labelKey: 'configuration.message.selfie_path', labelFallback: 'Selfie Path', hintKey: 'configuration.hints.selfie_path', hintFallback: 'Path to the bot appearance reference image', type: 'string', default: '', validation: { required: false } },
    ],
  },
]

const modelGroups: ConfigGroup[] = [
  {
    id: 'models',
    labelKey: 'configuration.groups.models',
    labelFallback: 'Default Models',
    descKey: 'configuration.groups.models_desc',
    descFallback: 'Select default provider and model for each capability',
    icon: '🧪',
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

  // Push to undo stack
  undoStack.value.push({ key, oldValue, newValue: value })
  redoStack.value = []

  setNestedValue(currentData.value, key, value)

  // Track modifications
  const originalValue = getNestedValue(originalData.value, key)
  if (value === originalValue) {
    modifiedFields.value.delete(key)
  } else {
    modifiedFields.value.add(key)
  }

  // Validate
  validateField(key)
}

// Model reference helpers
function parseModelReference(ref: string): { providerId: string; modelId: string } {
  if (!ref || typeof ref !== 'string') return { providerId: '', modelId: '' }
  const parts = ref.split(':')
  if (parts.length === 1) return { providerId: parts[0], modelId: '' }
  return { providerId: parts[0], modelId: parts.slice(1).join(':') }
}

function getModelProvider(key: string): string {
  const val = getFieldValue(key) || ''
  return parseModelReference(val).providerId
}

function getModelId(key: string): string {
  const val = getFieldValue(key) || ''
  return parseModelReference(val).modelId
}

function setModelProvider(key: string, providerId: string, modelType?: string) {
  // When provider changes, reset model
  setFieldValue(key, providerId ? `${providerId}:` : '')
}

function setModelId(key: string, modelId: string) {
  const providerId = getModelProvider(key)
  setFieldValue(key, providerId && modelId ? `${providerId}:${modelId}` : providerId ? `${providerId}:` : '')
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

function resetAll() {
  currentData.value = deepClone(originalData.value)
  modifiedFields.value.clear()
  undoStack.value = []
  redoStack.value = []
  validationErrors.value = {}
}

// Validation
function validateField(key: string) {
  const allFields = [...messageGroups, ...modelGroups].flatMap(g => g.fields)
  const field = allFields.find(f => f.key === key)
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
    t(field.labelKey, '').toLowerCase().includes(term)
  )
}

const filteredGroups = computed(() => {
  if (!searchTerm.value) return messageGroups
  return messageGroups.filter(group =>
    group.fields.some(f => fieldMatchesSearch(f))
  )
})

const filteredModelGroups = computed(() => {
  if (!searchTerm.value) return modelGroups
  return modelGroups.filter(group =>
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

// Save
async function handleSave() {
  if (saving.value) return
  if (modifiedFields.value.size === 0) {
    ElMessage.info(t('configuration.no_changes'))
    return
  }
  // Run full validation pass
  const allFields = [...messageGroups, ...modelGroups].flatMap(g => g.fields)
  allFields.forEach(f => validateField(f.key))
  // Check for validation errors
  if (Object.keys(validationErrors.value).length > 0) {
    ElMessage.error(t('configuration.validation.has_errors'))
    return
  }
  saving.value = true
  try {
    await saveConfiguration(currentData.value)
    originalData.value = deepClone(currentData.value)
    modifiedFields.value.clear()
    undoStack.value = []
    redoStack.value = []
    ElMessage.success(t('configuration.save_success'))
  } catch (err) {
    console.error('Save failed:', err)
    ElMessage.error(t('configuration.save_failed'))
  } finally {
    saving.value = false
  }
}

// Keyboard shortcuts
function handleKeydown(e: KeyboardEvent) {
  const key = e.key.toLowerCase()
  // Ctrl/Cmd+S should always work, even in input fields
  if ((e.ctrlKey || e.metaKey) && key === 's') {
    e.preventDefault()
    handleSave()
    return
  }
  const target = e.target as HTMLElement
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
    return
  }
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
  try {
    const res = await getConfiguration()
    const data = res.data
    originalData.value = deepClone(data.configuration || data.config || {})
    currentData.value = deepClone(originalData.value)
    providers.value = data.providers || []
    providerModels.value = data.provider_models || {}

    // Ensure defaults
    const allFields = [...messageGroups, ...modelGroups].flatMap(g => g.fields)
    allFields.forEach(field => {
      if (field.default !== undefined) {
        const current = getNestedValue(currentData.value, field.key)
        if (current === undefined || current === null) {
          setNestedValue(currentData.value, field.key, field.default)
          setNestedValue(originalData.value, field.key, field.default)
        }
      }
    })
  } catch (e) {
    console.error('Failed to load configuration:', e)
    ElMessage.error(t('configuration.load_failed'))
  }
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>
