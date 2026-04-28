<template>
  <div class="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
    <!-- Toolbar -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
      <div class="flex items-center space-x-3">
        <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('configuration.title') }}</h3>
        <Transition name="modified-badge">
          <span
            v-if="modifiedFields.size > 0"
            class="text-xs font-medium text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30 px-2 py-0.5 rounded-full"
          >
            {{ modifiedFields.size }} {{ $t('configuration.changes') }}
          </span>
        </Transition>
      </div>

      <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
        <!-- Search -->
        <div class="relative">
          <input
            ref="searchInputRef"
            v-model="searchTerm"
            type="text"
            :placeholder="$t('configuration.search_placeholder')"
            :aria-label="$t('configuration.search_aria_label')"
            class="w-full sm:w-56 border border-gray-300 dark:border-gray-600 rounded-lg pl-9 pr-3 py-2 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
          />
          <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>

        <!-- Actions -->
        <div class="flex items-center space-x-1">
          <button
            type="button"
            :disabled="undoStack.length === 0"
            :aria-label="$t('configuration.undo_aria')"
            :title="$t('configuration.undo_aria')"
            class="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            @click="undo"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a5 5 0 015 5v2M3 10l4-4m-4 4l4 4" />
            </svg>
          </button>
          <button
            type="button"
            :disabled="redoStack.length === 0"
            :aria-label="$t('configuration.redo_aria')"
            :title="$t('configuration.redo_aria')"
            class="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            @click="redo"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 10H11a5 5 0 00-5 5v2m15-7l-4-4m4 4l-4 4" />
            </svg>
          </button>
          <button
            type="button"
            :aria-label="$t('configuration.reset_aria')"
            :title="$t('configuration.reset_aria')"
            class="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            @click="loadConfig"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
          <div class="w-px h-6 bg-gray-200 dark:bg-gray-700 mx-1" />
          <button
            type="button"
            :aria-label="$t('configuration.expand_all_aria')"
            :title="$t('configuration.expand_all_aria')"
            class="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            @click="expandAll"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
            </svg>
          </button>
          <button
            type="button"
            :aria-label="$t('configuration.collapse_all_aria')"
            :title="$t('configuration.collapse_all_aria')"
            class="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            @click="collapseAll"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 9V4.5M9 9H4.5M9 9L3.5 3.5M9 15v4.5M9 15H4.5M9 15l-5.5 5.5M15 9h4.5M15 9V4.5M15 9l5.5-5.5M15 15h4.5m-4.5 0v4.5m0-4.5l5.5 5.5" />
            </svg>
          </button>
          <div class="w-px h-6 bg-gray-200 dark:bg-gray-700 mx-1" />
          <button
            type="button"
            :disabled="modifiedFields.size === 0 || saving"
            class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors flex items-center text-sm font-medium disabled:opacity-60 disabled:cursor-not-allowed"
            @click="handleSave"
          >
            <svg class="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
            </svg>
            {{ $t('configuration.save') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Groups -->
    <div
      v-for="group in filteredAllGroups"
      :key="group.id"
      class="mb-4"
    >
      <!-- Group Header -->
      <div
        class="config-group-header flex items-center justify-between px-4 py-3 cursor-pointer rounded-t-lg select-none transition-colors duration-150 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 active:bg-gray-200 dark:active:bg-gray-600 border border-gray-200 dark:border-gray-700"
        :class="{ 'rounded-b-lg': collapsedGroups.has(group.id) }"
        role="button"
        tabindex="0"
        :aria-expanded="!collapsedGroups.has(group.id)"
        @click="toggleGroup(group.id)"
        @keydown.enter.prevent="toggleGroup(group.id)"
        @keydown.space.prevent="toggleGroup(group.id)"
      >
        <div class="flex items-center space-x-3 min-w-0">
          <span class="text-gray-500 dark:text-gray-400 shrink-0" v-html="group.iconSvg" />
          <div class="min-w-0">
            <h4 class="text-sm font-semibold text-gray-800 dark:text-gray-100 flex items-center">
              <span v-html="highlightSearch($t(group.labelKey, group.labelFallback))" />
              <Transition name="modified-badge">
                <span
                  v-if="groupHasModified(group)"
                  class="inline-block w-2 h-2 bg-amber-500 rounded-full ml-2"
                  aria-hidden="true"
                ></span>
              </Transition>
            </h4>
            <p class="text-xs text-gray-500 dark:text-gray-400 truncate" v-html="highlightSearch($t(group.descKey, group.descFallback))" />
          </div>
        </div>
        <svg
          class="w-5 h-5 text-gray-400 dark:text-gray-500 transform transition-transform duration-200 shrink-0 ml-2"
          :class="{ 'rotate-180': !collapsedGroups.has(group.id) }"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
      </div>

      <!-- Horizontal layout (model selects) -->
      <div
        v-if="group.layout === 'horizontal'"
        class="config-group-body border border-t-0 border-gray-200 dark:border-gray-700 rounded-b-lg bg-white dark:bg-gray-900 overflow-hidden transition-all duration-200"
        :class="{ 'max-h-0 opacity-0 py-0 border-0': collapsedGroups.has(group.id), 'max-h-[2000px] opacity-100': !collapsedGroups.has(group.id) }"
      >
        <div class="p-4 space-y-4">
          <div
            v-for="field in getVisibleFields(group)"
            :key="field.key"
            class="flex flex-col md:flex-row md:items-center md:justify-between gap-3 py-3 border-b border-gray-100 dark:border-gray-800 last:border-0"
            :class="{ 'config-field-modified': modifiedFields.has(field.key) }"
          >
            <div class="flex-shrink-0">
              <div class="text-sm font-medium text-gray-800 dark:text-gray-100 flex items-center">
                <span v-html="highlightSearch($t(field.labelKey, field.labelFallback))" />
                <Transition name="modified-badge">
                  <span v-if="modifiedFields.has(field.key)" class="ml-2 text-xs text-amber-500 font-normal">{{ $t('configuration.modified') }}</span>
                </Transition>
              </div>
              <div class="text-xs text-gray-500 dark:text-gray-400" v-html="highlightSearch($t(field.hintKey, field.hintFallback))" />
            </div>
            <div class="flex flex-col sm:flex-row gap-2 md:gap-3">
              <select
                :value="getModelProvider(field.key)"
                class="w-full sm:w-40 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
                @change="(e) => setModelProvider(field.key, (e.target as HTMLSelectElement).value, field.modelType)"
              >
                <option value="">{{ $t('configuration.none') }}</option>
                <option
                  v-for="p in providers"
                  :key="p.id"
                  :value="p.id"
                >
                  {{ p.name || p.id }}
                </option>
              </select>
              <select
                :value="getModelId(field.key)"
                class="w-full sm:w-48 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
                @change="(e) => setModelId(field.key, (e.target as HTMLSelectElement).value)"
              >
                <option value="">{{ $t('configuration.none') }}</option>
                <option
                  v-for="modelId in getAvailableModels(field.key, field.modelType)"
                  :key="modelId"
                  :value="modelId"
                >
                  {{ modelId }}
                </option>
              </select>
            </div>
            <p
              v-if="validationErrors[field.key]"
              class="w-full text-xs text-red-500 dark:text-red-400"
            >
              {{ validationErrors[field.key] }}
            </p>
          </div>
        </div>
      </div>

      <!-- Grid layout (regular fields) -->
      <div
        v-else
        class="config-group-body border border-t-0 border-gray-200 dark:border-gray-700 rounded-b-lg bg-white dark:bg-gray-900 overflow-hidden transition-all duration-200"
        :class="{ 'max-h-0 opacity-0 py-0 border-0': collapsedGroups.has(group.id), 'max-h-[2000px] opacity-100': !collapsedGroups.has(group.id) }"
      >
        <div class="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div
            v-for="field in getVisibleFields(group)"
            :key="field.key"
            class="config-field-wrapper"
            :class="{ 'config-field-modified': modifiedFields.has(field.key) }"
          >
            <label
              class="block text-sm font-medium mb-1"
              :class="validationErrors[field.key] ? 'text-red-600 dark:text-red-400' : 'text-gray-700 dark:text-gray-300'"
              :title="field.key"
            >
              <span v-html="highlightSearch($t(field.labelKey, field.labelFallback))" />
              <Transition name="modified-badge">
                <span v-if="modifiedFields.has(field.key)" class="ml-2 text-xs text-amber-500 font-normal">{{ $t('configuration.modified') }}</span>
              </Transition>
            </label>

            <!-- Integer -->
            <input
              v-if="field.type === 'integer'"
              :value="getFieldValue(field.key)"
              type="number"
              step="1"
              :min="field.validation?.min"
              :max="field.validation?.max"
              :placeholder="$t(field.hintKey, field.hintFallback)"
              class="w-full border rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 transition-colors duration-150"
              :class="validationErrors[field.key] ? 'border-red-400 dark:border-red-500 focus:ring-red-500' : 'border-gray-300 dark:border-gray-600 focus:ring-blue-500'"
              @input="(e) => setFieldValue(field.key, (e.target as HTMLInputElement).value === '' ? null : Number((e.target as HTMLInputElement).value))"
              @blur="validateField(field.key)"
            >

            <!-- Float -->
            <input
              v-else-if="field.type === 'float'"
              :value="getFieldValue(field.key)"
              type="number"
              step="0.1"
              :min="field.validation?.min"
              :max="field.validation?.max"
              :placeholder="$t(field.hintKey, field.hintFallback)"
              class="w-full border rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 transition-colors duration-150"
              :class="validationErrors[field.key] ? 'border-red-400 dark:border-red-500 focus:ring-red-500' : 'border-gray-300 dark:border-gray-600 focus:ring-blue-500'"
              @input="(e) => setFieldValue(field.key, (e.target as HTMLInputElement).value === '' ? null : Number((e.target as HTMLInputElement).value))"
              @blur="validateField(field.key)"
            >

            <!-- Boolean / Switch -->
            <button
              v-else-if="field.type === 'boolean'"
              type="button"
              class="relative inline-flex items-center h-6 w-11 rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
              :class="getFieldValue(field.key) ? 'bg-blue-600 dark:bg-blue-500' : 'bg-gray-300 dark:bg-gray-600'"
              :aria-checked="getFieldValue(field.key) ? 'true' : 'false'"
              role="switch"
              @click="setFieldValue(field.key, !getFieldValue(field.key))"
            >
              <span
                class="inline-block h-4 w-4 bg-white rounded-full shadow transform transition-transform duration-200"
                :class="getFieldValue(field.key) ? 'translate-x-6' : 'translate-x-1'"
              />
            </button>

            <!-- String -->
            <input
              v-else
              :value="getFieldValue(field.key)"
              type="text"
              :placeholder="$t(field.hintKey, field.hintFallback)"
              class="w-full border rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 transition-colors duration-150"
              :class="validationErrors[field.key] ? 'border-red-400 dark:border-red-500 focus:ring-red-500' : 'border-gray-300 dark:border-gray-600 focus:ring-blue-500'"
              @input="(e) => setFieldValue(field.key, (e.target as HTMLInputElement).value)"
              @blur="validateField(field.key)"
            >

            <p
              v-if="field.hintKey && !validationErrors[field.key]"
              class="text-xs mt-1 text-gray-500 dark:text-gray-400"
              v-html="highlightSearch($t(field.hintKey, field.hintFallback))"
            />
            <p
              v-if="validationErrors[field.key]"
              class="text-xs mt-1 text-red-500 dark:text-red-400"
            >
              {{ validationErrors[field.key] }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- Bottom keyboard hints -->
    <div class="mt-4 pt-3 border-t border-gray-100 dark:border-gray-800">
      <p class="text-xs text-gray-400 dark:text-gray-500 text-center">
        <kbd class="kbd-hint">Ctrl+Z</kbd> {{ $t('configuration.shortcut_undo') }}
        <kbd class="kbd-hint">Ctrl+Shift+Z</kbd> {{ $t('configuration.shortcut_redo') }}
        <kbd class="kbd-hint">Ctrl+S</kbd> {{ $t('configuration.shortcut_save') }}
        <kbd class="kbd-hint">/</kbd> {{ $t('configuration.shortcut_search') }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { notify } from '@/composables/useNotification'
import { getConfiguration, saveConfiguration } from '@/api/config'

const { t } = useI18n()

const searchTerm = ref('')
const saving = ref(false)
const loading = ref(false)
const searchInputRef = ref<HTMLInputElement | null>(null)

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
const collapsedGroups = reactive(new Set<string>())
const modifiedFields = reactive(new Set<string>())
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
  iconSvg: string
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
    iconSvg: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>',
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
    iconSvg: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>',
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
    iconSvg: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>',
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
    iconSvg: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"></path></svg>',
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

function escapeHtml(str: string): string {
  if (!str) return ''
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function highlightSearch(text: string): string {
  if (!searchTerm.value || !text) return escapeHtml(text)
  const term = escapeHtml(searchTerm.value)
  const escaped = escapeHtml(text)
  const searchEscaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const regex = new RegExp(`(${searchEscaped})`, 'gi')
  return escaped.replace(regex, '<mark class="bg-yellow-200 dark:bg-yellow-700 px-0.5 rounded">$1</mark>')
}

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

function normalizeValue(v: any): any {
  // Treat undefined / empty string as null so comparisons match
  // the old implementation's convention.
  if (v === undefined || v === '') return null
  return v
}

function setFieldValue(key: string, value: any) {
  const oldValue = getNestedValue(currentData.value, key)
  const normOld = normalizeValue(oldValue)
  const normNew = normalizeValue(value)
  const changed = JSON.stringify(normOld) !== JSON.stringify(normNew)

  if (changed) {
    undoStack.value.push({ key, oldValue, newValue: value })
    redoStack.value = []
    setNestedValue(currentData.value, key, value)
  }

  const originalValue = getNestedValue(originalData.value, key)
  if (JSON.stringify(normNew) === JSON.stringify(normalizeValue(originalValue))) {
    modifiedFields.delete(key)
  } else {
    modifiedFields.add(key)
  }

  if (changed) {
    validateField(key)
  }
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
    setFieldValue(key, null)
    // If the persisted value was already null, setFieldValue is a no-op and
    // won't run validation — call it explicitly so any stale error clears.
    validateField(key)
    return
  }
  // Switching provider invalidates any previously chosen model, so we clear
  // the persisted value and park the provider in pending state until the user
  // picks a model. `validateField` will flag this as required-but-missing.
  pendingProviders.value[key] = providerId
  setFieldValue(key, null)
  validateField(key)
}

function setModelId(key: string, modelId: string) {
  const providerId = getModelProvider(key)
  if (!providerId || !modelId) {
    delete pendingProviders.value[key]
    setFieldValue(key, null)
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
  if (JSON.stringify(normalizeValue(entry.oldValue)) === JSON.stringify(normalizeValue(originalValue))) {
    modifiedFields.delete(entry.key)
  } else {
    modifiedFields.add(entry.key)
  }
  validateField(entry.key)
}

function redo() {
  const entry = redoStack.value.pop()
  if (!entry) return
  undoStack.value.push(entry)
  setNestedValue(currentData.value, entry.key, entry.newValue)
  const originalValue = getNestedValue(originalData.value, entry.key)
  if (JSON.stringify(normalizeValue(entry.newValue)) === JSON.stringify(normalizeValue(originalValue))) {
    modifiedFields.delete(entry.key)
  } else {
    modifiedFields.add(entry.key)
  }
  validateField(entry.key)
}

// Validation
function validateField(key: string) {
  const allFields = allGroups.flatMap(g => g.fields)
  const field = allFields.find(f => f.key === key)
  // model_select fields are invalid whenever a provider is parked in
  // pendingProviders without a corresponding model — Save would otherwise
  // persist null while the UI still shows the half-selected row.
  if (field?.type === 'model_select' && pendingProviders.value[key]) {
    validationErrors.value[key] = t('configuration.validation.required')
    return
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
  return group.fields.some(f => modifiedFields.has(f.key))
}

function toggleGroup(id: string) {
  if (collapsedGroups.has(id)) {
    collapsedGroups.delete(id)
  } else {
    collapsedGroups.add(id)
  }
}

function expandAll() {
  collapsedGroups.clear()
}

function collapseAll() {
  collapsedGroups.clear()
  allGroups.forEach(g => collapsedGroups.add(g.id))
}

// Save
async function handleSave() {
  if (saving.value) return
  if (modifiedFields.size === 0) {
    notify(t('configuration.no_changes'), 'info')
    return
  }
  const allFields = allGroups.flatMap(g => g.fields)
  allFields.forEach(f => validateField(f.key))
  if (Object.keys(validationErrors.value).length > 0) {
    notify(t('configuration.validation_failed'), 'error')
    return
  }
  saving.value = true
  const snapshot = deepClone(currentData.value)
  try {
    await saveConfiguration(snapshot)
    originalData.value = snapshot
    const allFieldKeys = allFields.map(f => f.key)
    modifiedFields.clear()
    for (const key of allFieldKeys) {
      const current = getNestedValue(currentData.value, key)
      const saved = getNestedValue(snapshot, key)
      if (current !== saved) modifiedFields.add(key)
    }
    if (modifiedFields.size === 0) {
      undoStack.value = []
      redoStack.value = []
    }
    notify(t('configuration.save_success'), 'success')
  } catch (err) {
    console.error('Save failed:', err)
    notify(t('configuration.save_failed'), 'error')
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

    // Normalize numeric types: backend may return integers/floats as strings,
    // but the <input type="number"> converts user input to Number. Without
    // this step a value like "50" (string) in originalData will never match
    // 50 (number) after the user edits and reverts the field.
    allFields.forEach(field => {
      if (field.type === 'integer' || field.type === 'float') {
        const orig = getNestedValue(originalData.value, field.key)
        if (orig !== undefined && orig !== null && typeof orig !== 'number') {
          const num = field.type === 'integer'
            ? Number.parseInt(orig, 10)
            : Number.parseFloat(orig)
          if (!Number.isNaN(num)) {
            setNestedValue(originalData.value, field.key, num)
            setNestedValue(currentData.value, field.key, num)
          }
        }
      }
    })

    // Reset dirty state since we just re-synced
    modifiedFields.clear()
    undoStack.value = []
    redoStack.value = []
    pendingProviders.value = {}
    validationErrors.value = {}
  } catch (e) {
    console.error('Failed to load configuration:', e)
    notify(t('configuration.load_failed'), 'error')
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
  nextTick(() => {
    searchInputRef.value?.focus()
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
.modified-badge-enter-active,
.modified-badge-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.modified-badge-enter-from,
.modified-badge-leave-to {
  opacity: 0;
  transform: scale(0.9);
}
</style>
