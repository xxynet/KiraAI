<template>
  <div>
    <!-- Title -->
    <div class="flex items-center mb-6">
      <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('plugin.title') }}</h3>
    </div>

    <!-- Custom Tabs -->
    <div class="flex space-x-4 mb-4 border-b border-gray-200 dark:border-gray-700">
      <button
        type="button"
        class="px-3 py-2 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
        :class="activeTab === 'plugins' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'"
        @click="activeTab = 'plugins'"
      >
        {{ $t('plugin.plugins') }}
      </button>
      <button
        type="button"
        class="px-3 py-2 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
        :class="activeTab === 'mcp' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'"
        @click="activeTab = 'mcp'"
      >
        {{ $t('plugin.tab_mcp') }}
      </button>
      <button
        type="button"
        class="px-3 py-2 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
        :class="activeTab === 'skills' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'"
        @click="activeTab = 'skills'"
      >
        {{ $t('plugin.skills') }}
      </button>
    </div>

    <!-- Plugins Tab Content -->
    <div v-show="activeTab === 'plugins'">
      <div class="flex items-center justify-start mb-4">
        <button
          type="button"
          class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          @click="installDialogVisible = true"
        >
          <span class="mr-1">+</span>
          <span>{{ $t('plugin.install_add') }}</span>
        </button>
      </div>

      <div v-if="pluginsError" class="flex justify-center items-center py-12">
        <div class="text-center">
          <svg class="w-16 h-16 text-red-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 4a2 2 0 114 0v1a1 1 0 001 1h3a1 1 0 011 1v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H7a1 1 0 01-1-1v-3a1 1 0 00-1-1H4a2 2 0 110-4h1a1 1 0 001-1V7a1 1 0 011-1h3a1 1 0 001-1V4z" />
          </svg>
          <p class="text-red-500">{{ pluginsError }}</p>
        </div>
      </div>

      <div v-else-if="plugins.length === 0" class="flex justify-center items-center py-12">
        <div class="text-center">
          <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 4a2 2 0 114 0v1a1 1 0 001 1h3a1 1 0 011 1v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H7a1 1 0 01-1-1v-3a1 1 0 00-1-1H4a2 2 0 110-4h1a1 1 0 001-1V7a1 1 0 011-1h3a1 1 0 001-1V4z" />
          </svg>
          <p class="text-gray-500">{{ $t('plugin.no_plugins') }}</p>
        </div>
      </div>

      <div v-else class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
        <div
          v-for="plugin in displayedPlugins"
          :key="plugin.id"
          class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 flex flex-col"
        >
          <div class="flex items-start justify-between mb-3">
            <div>
              <div class="text-base font-semibold text-gray-900 dark:text-gray-100">{{ plugin.name || plugin.id }}</div>
              <div v-if="plugin.version || plugin.author" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                {{ plugin.version ? `v${plugin.version}` : '' }}{{ plugin.version && plugin.author ? ' · ' : '' }}{{ plugin.author || '' }}
              </div>
            </div>
            <div class="flex items-start space-x-2">
              <a
                v-if="plugin.safeRepo"
                :href="plugin.safeRepo"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 mt-1"
              >
                <span class="mr-1">{{ $t('plugin.repo_link') }}</span>
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 3h7m0 0v7m0-7L10 14" />
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10v11h11" />
                </svg>
              </a>
              <button
                type="button"
                class="ml-2 relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none"
                :class="plugin.enabled ? 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500' : 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600'"
                :aria-pressed="plugin.enabled ? 'true' : 'false'"
                @click="togglePlugin(plugin)"
              >
                <span
                  class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
                  :class="plugin.enabled ? 'translate-x-4' : 'translate-x-0'"
                />
              </button>
            </div>
          </div>
          <p v-if="plugin.description" class="text-sm text-gray-600 dark:text-gray-300 line-clamp-3 mb-3">
            {{ plugin.description }}
          </p>
          <div class="mt-auto">
            <div class="text-xs font-mono text-gray-400 dark:text-gray-500 break-all mb-3">{{ plugin.id }}</div>
            <div class="flex items-center justify-end space-x-3">
              <button
                type="button"
                class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800 transition-colors"
                @click="openPluginConfig(plugin)"
              >
                {{ $t('plugin.configure') }}
              </button>
              <button
                type="button"
                class="px-3 py-1.5 text-xs font-medium rounded-md border transition-colors"
                :class="(plugin as any).uninstallable
                  ? 'border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30'
                  : 'border-gray-200 text-gray-300 cursor-not-allowed dark:border-gray-700 dark:text-gray-600'"
                :disabled="!(plugin as any).uninstallable"
                @click="(plugin as any).uninstallable && handleDeletePlugin(plugin.id)"
              >
                {{ $t('plugin.uninstall') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- MCP Tab Content -->
    <div v-show="activeTab === 'mcp'">
      <div class="flex items-center justify-start mb-4">
        <button
          type="button"
          class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          @click="openMcpCreate"
        >
          <span class="mr-1">+</span>
          <span>{{ $t('plugin.mcp_add') }}</span>
        </button>
      </div>

      <div v-if="mcpServersError" class="flex justify-center items-center py-12">
        <div class="text-center">
          <svg class="w-16 h-16 text-red-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M12 6a9 9 0 11-9 9 9 9 0 019-9z" />
          </svg>
          <p class="text-red-500">{{ mcpServersError }}</p>
        </div>
      </div>

      <div v-else-if="mcpServers.length === 0" class="flex justify-center items-center py-12">
        <div class="text-center">
          <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M12 6a9 9 0 11-9 9 9 9 0 019-9z" />
          </svg>
          <p class="text-gray-500">{{ $t('plugin.no_mcp_servers') }}</p>
        </div>
      </div>

      <div v-else class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
        <div
          v-for="server in mcpServers"
          :key="server.id"
          class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 flex flex-col"
        >
          <div class="flex items-start justify-between mb-3">
            <div>
              <div class="text-base font-semibold text-gray-900 dark:text-gray-100">{{ server.name || server.id }}</div>
              <div
                v-if="server.type"
                class="mt-1 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
              >
                {{ server.type }}
              </div>
              <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ server.id }}</div>
            </div>
            <button
              type="button"
              class="ml-2 relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none"
              :class="server.enabled ? 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500' : 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600'"
              :aria-pressed="server.enabled ? 'true' : 'false'"
              @click="toggleMcp(server)"
            >
              <span
                class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
                :class="server.enabled ? 'translate-x-4' : 'translate-x-0'"
              />
            </button>
          </div>
          <p v-if="server.description" class="text-sm text-gray-600 dark:text-gray-300 line-clamp-3 mb-3">
            {{ server.description }}
          </p>
          <div class="mt-2 text-xs text-gray-500 dark:text-gray-400">
            {{ $t('plugin.mcp_tools_label') }}: {{ server.tools_count }}
          </div>
          <div class="mt-4 flex items-center justify-end space-x-3 mt-auto">
            <button
              type="button"
              class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800 transition-colors"
              @click="openMcpEdit(server)"
            >
              {{ $t('plugin.mcp_edit') }}
            </button>
            <button
              type="button"
              class="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30 transition-colors"
              @click="handleDeleteMcp(server.id)"
            >
              {{ $t('plugin.mcp_delete') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Skills Tab Content -->
    <div v-show="activeTab === 'skills'">
      <div class="flex items-center justify-start mb-4">
        <button
          type="button"
          class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors mr-2"
          @click="skillsUploadVisible = true"
        >
          <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>
          <span>{{ $t('plugin.skills_upload') }}</span>
        </button>
        <button
          type="button"
          class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          @click="refreshSkillList"
        >
          <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          <span>{{ $t('plugin.skills_refresh') }}</span>
        </button>
      </div>

      <div v-if="skillsError" class="flex justify-center items-center py-12">
        <div class="text-center">
          <svg class="w-16 h-16 text-red-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
          <p class="text-red-500">{{ skillsError }}</p>
        </div>
      </div>

      <div v-else-if="skills.length === 0" class="flex justify-center items-center py-12">
        <div class="text-center">
          <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
          <p class="text-gray-500">{{ $t('plugin.no_skills') }}</p>
        </div>
      </div>

      <div v-else class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
        <div
          v-for="skill in skills"
          :key="skill.id"
          class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 flex flex-col"
        >
          <div class="flex items-start justify-between mb-3">
            <div>
              <div class="text-base font-semibold text-gray-900 dark:text-gray-100">{{ skill.name || skill.id }}</div>
            </div>
            <button
              type="button"
              class="ml-2 relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none"
              :class="skill.enabled ? 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500' : 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600'"
              :aria-pressed="skill.enabled ? 'true' : 'false'"
              @click="toggleSkillItem(skill)"
            >
              <span
                class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
                :class="skill.enabled ? 'translate-x-4' : 'translate-x-0'"
              />
            </button>
          </div>
          <p v-if="skill.description" class="text-sm text-gray-600 dark:text-gray-300 line-clamp-3 mb-3">
            {{ skill.description }}
          </p>
          <div class="mt-auto">
            <div class="text-xs font-mono text-gray-400 dark:text-gray-500 break-all">{{ skill.path }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Install Plugin Dialog -->
    <el-dialog
      v-model="installDialogVisible"
      :title="$t('plugin.install_add')"
      width="500"
      :destroy-on-close="true"
      @closed="resetInstallForm"
    >
      <el-tabs v-model="installTab">
        <el-tab-pane label="GitHub" name="github">
          <el-form label-position="top">
            <el-form-item :label="$t('plugin.repo_url')">
              <el-input v-model="installForm.repo_url" placeholder="https://github.com/user/repo" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane :label="$t('plugin.upload_zip')" name="upload">
          <el-upload
            drag
            action=""
            :auto-upload="false"
            :limit="1"
            accept=".zip"
            :on-change="onUploadChange"
          >
            <el-icon :size="48"><UploadFilled /></el-icon>
            <div class="el-upload__text">{{ $t('plugin.upload_hint') }}</div>
          </el-upload>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="installDialogVisible = false">{{ $t('plugin.cancel') }}</el-button>
        <el-button type="primary" :loading="installing" @click="handleInstall">{{ $t('plugin.install') }}</el-button>
      </template>
    </el-dialog>

    <!-- Plugin Config Dialog -->
    <el-dialog v-model="pluginConfigVisible" :title="$t('plugin.configure')" width="600" :destroy-on-close="true">
      <div v-if="pluginConfigSchema">
        <ConfigForm v-model="pluginConfigValues" :schema="pluginConfigSchema" />
      </div>
      <div v-else class="text-center py-8 text-gray-400">
        {{ $t('plugin.no_config') }}
      </div>
      <template #footer>
        <el-button @click="pluginConfigVisible = false">{{ $t('plugin.cancel') }}</el-button>
        <el-button
          type="primary"
          :loading="savingConfig"
          :disabled="!pluginConfigSchema"
          @click="savePluginConfig"
        >{{ $t('plugin.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- Skills Upload Dialog -->
    <el-dialog v-model="skillsUploadVisible" :title="$t('plugin.skills_upload')" width="500" :destroy-on-close="true">
      <el-upload
        ref="skillsUploadRef"
        drag
        action=""
        :auto-upload="false"
        :limit="1"
        accept=".zip"
        :on-change="onSkillUploadChange"
      >
        <el-icon :size="48"><UploadFilled /></el-icon>
        <div class="el-upload__text">{{ $t('plugin.upload_hint') }}</div>
      </el-upload>
      <template #footer>
        <el-button @click="skillsUploadVisible = false">{{ $t('plugin.cancel') }}</el-button>
        <el-button type="primary" :loading="uploadingSkill" @click="handleSkillUpload">{{ $t('plugin.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- MCP Config Dialog -->
    <el-dialog v-model="mcpDialogVisible" :title="mcpEditMode ? $t('plugin.mcp_edit') : $t('plugin.mcp_add')" width="700" :destroy-on-close="true">
      <el-form label-position="top">
        <el-form-item :label="$t('plugin.mcp_name')">
          <!-- Name doubles as the server's primary key on the backend; the
               PUT /config endpoint silently ignores any rename in the body,
               so disable the field in edit mode to make that contract
               visible instead of letting the user think they renamed it. -->
          <el-input v-model="mcpForm.name" :disabled="mcpEditMode" />
        </el-form-item>
        <el-form-item :label="$t('plugin.mcp_description')">
          <el-input v-model="mcpForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item :label="$t('plugin.mcp_config')">
          <MonacoEditor v-model="mcpConfigJson" language="json" height="300px" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mcpDialogVisible = false">{{ $t('plugin.cancel') }}</el-button>
        <el-button type="primary" :loading="savingMcp" @click="saveMcpForm">{{ $t('plugin.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import {
  getPlugins, getPluginConfig, updatePluginConfig,
  togglePlugin as apiTogglePlugin, deletePlugin,
  installFromGithub, installFromUpload,
} from '@/api/plugin'
import {
  getMcpServers, getMcpServerConfig, createMcpServer, updateMcpServerConfig,
  deleteMcpServer, toggleMcpServer,
} from '@/api/mcp'
import {
  getSkills, toggleSkill as apiToggleSkill, refreshSkills as apiRefreshSkills, uploadSkill as apiUploadSkill,
} from '@/api/skills'
import MonacoEditor from '@/components/common/MonacoEditor.vue'
import ConfigForm from '@/components/common/ConfigForm.vue'
import type { PluginItem, McpServerItem } from '@/types'

const { t } = useI18n()
const activeTab = ref('plugins')

// Plugins
const plugins = ref<PluginItem[]>([])
const installDialogVisible = ref(false)
const installTab = ref('github')
const installForm = ref({ repo_url: '' })
const uploadFile = ref<File | null>(null)
const installing = ref(false)

// Plugin Config
const pluginConfigVisible = ref(false)
const pluginConfigSchema = ref<any>(null)
const pluginConfigValues = ref<Record<string, any>>({})
const configPluginId = ref('')
const savingConfig = ref(false)

// MCP
const mcpServers = ref<McpServerItem[]>([])
const mcpDialogVisible = ref(false)
const mcpEditMode = ref(false)
const mcpEditId = ref<string | null>(null)
const mcpForm = ref({ name: '', description: '' })
const mcpConfigJson = ref('{}')
const savingMcp = ref(false)

// Skills
const skills = ref<any[]>([])
const skillsError = ref<string | null>(null)
const skillsUploadVisible = ref(false)
const skillUploadFile = ref<File | null>(null)
const uploadingSkill = ref(false)
const skillsUploadRef = ref<any>(null)

// Error flags so the UI can distinguish "no data" from "fetch failed"
const pluginsError = ref<string | null>(null)
const mcpServersError = ref<string | null>(null)

// Only render plugin.repo as a link if it is a well-formed http(s) URL.
// Prevents javascript:/data: URLs embedded in plugin metadata from running
// when the user clicks the "Repo" link.
function safeRepoUrl(url: unknown): string | null {
  if (typeof url !== 'string' || !url) return null
  try {
    const parsed = new URL(url)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.toString()
    }
  } catch { /* invalid URL */ }
  return null
}

// Enrich each plugin with a pre-validated `safeRepo` so the template doesn't
// call safeRepoUrl twice per card (v-if + :href) and re-parse the URL.
const displayedPlugins = computed(() =>
  plugins.value.map(p => ({ ...p, safeRepo: safeRepoUrl(p.repo) })),
)

async function loadPlugins() {
  try {
    const res = await getPlugins()
    plugins.value = Array.isArray(res.data) ? res.data : []
    pluginsError.value = null
  } catch (e: any) {
    plugins.value = []
    // Prefer backend detail when useful; always default to the localized
    // message so Chinese users don't see an English fallback.
    pluginsError.value = e?.message || t('plugin.load_failed')
    ElMessage.error(pluginsError.value!)
  }
}

async function loadMcpServers() {
  try {
    const res = await getMcpServers()
    mcpServers.value = Array.isArray(res.data) ? res.data : []
    mcpServersError.value = null
  } catch (e: any) {
    mcpServers.value = []
    mcpServersError.value = e?.message || t('plugin.mcp_load_failed')
    ElMessage.error(mcpServersError.value!)
  }
}

async function togglePlugin(plugin: PluginItem) {
  try {
    await apiTogglePlugin(plugin.id, !plugin.enabled)
    ElMessage.success(t('plugin.toggle_success'))
  } catch {
    ElMessage.error(t('plugin.toggle_failed'))
  } finally {
    // Always resync so the switch reflects the backend's view, even if the
    // call failed half-way and we can't be sure which side of the toggle
    // actually took effect.
    await loadPlugins()
  }
}

async function handleDeletePlugin(id: string) {
  try {
    await ElMessageBox.confirm(t('plugin.uninstall_confirm'), t('plugin.uninstall'), { type: 'warning' })
  } catch {
    return
  }
  try {
    await deletePlugin(id)
    ElMessage.success(t('plugin.uninstall_success'))
    await loadPlugins()
  } catch {
    ElMessage.error(t('plugin.uninstall_failed'))
  }
}

async function openPluginConfig(plugin: PluginItem) {
  configPluginId.value = plugin.id
  try {
    const res = await getPluginConfig(plugin.id)
    pluginConfigSchema.value = res.data.schema || null
    pluginConfigValues.value = res.data.config || {}
  } catch {
    // A failed fetch must not surface as "no config" — that would let the
    // user save {} back and wipe real config on the server.
    ElMessage.error(t('plugin.config_load_failed'))
    pluginConfigSchema.value = null
    pluginConfigValues.value = {}
    return
  }
  pluginConfigVisible.value = true
}

async function savePluginConfig() {
  // Guard: the "no_config" placeholder leaves pluginConfigValues empty.
  // Posting {} back would wipe any legitimately-managed config for a plugin
  // that has no schema, so refuse to save instead of overwriting.
  if (!pluginConfigSchema.value) return
  savingConfig.value = true
  try {
    await updatePluginConfig(configPluginId.value, { config: pluginConfigValues.value })
    ElMessage.success(t('plugin.config_saved'))
    pluginConfigVisible.value = false
  } catch {
    ElMessage.error(t('plugin.config_save_failed'))
  } finally {
    savingConfig.value = false
  }
}

function onUploadChange(file: UploadFile) {
  uploadFile.value = file.raw || null
}

// el-dialog preserves its child state across closes; reset the form here so
// reopening doesn't show the previous repo URL or leave the 1-slot upload
// occupied by the last file.
function resetInstallForm() {
  installForm.value = { repo_url: '' }
  uploadFile.value = null
  installTab.value = 'github'
}

async function handleInstall() {
  installing.value = true
  try {
    if (installTab.value === 'github') {
      const repoUrl = installForm.value.repo_url?.trim()
      if (!repoUrl) {
        ElMessage.error(t('plugin.repo_url_required'))
        installing.value = false
        return
      }
      await installFromGithub({ repo_url: repoUrl })
    } else {
      if (!uploadFile.value) {
        ElMessage.error(t('plugin.file_required'))
        installing.value = false
        return
      }
      await installFromUpload(uploadFile.value)
    }
    installDialogVisible.value = false
    ElMessage.success(t('plugin.install_success'))
    await loadPlugins()
  } catch {
    ElMessage.error(t('plugin.install_failed'))
  } finally {
    installing.value = false
  }
}

async function toggleMcp(server: McpServerItem) {
  try {
    await toggleMcpServer(server.id, !server.enabled)
    ElMessage.success(t('plugin.mcp_toggle_success'))
  } catch {
    ElMessage.error(t('plugin.mcp_toggle_failed'))
  } finally {
    await loadMcpServers()
  }
}

function openMcpCreate() {
  mcpEditMode.value = false
  mcpEditId.value = null
  mcpForm.value = { name: '', description: '' }
  mcpConfigJson.value = '{}'
  mcpDialogVisible.value = true
}

async function openMcpEdit(server: McpServerItem) {
  try {
    const res = await getMcpServerConfig(server.id)
    mcpEditMode.value = true
    mcpEditId.value = server.id
    mcpForm.value = { name: server.name, description: server.description || '' }
    mcpConfigJson.value = JSON.stringify(res.data?.config ?? {}, null, 2)
    mcpDialogVisible.value = true
  } catch {
    // Abort opening the editor — a lossy fallback built from list fields
    // would silently overwrite the real config if the user hits Save. Use
    // the load-specific key so the toast isn't misleading (the user never
    // tried to save anything).
    ElMessage.error(t('plugin.mcp_config_load_failed'))
  }
}

async function saveMcpForm() {
  if (!mcpForm.value.name?.trim()) {
    ElMessage.error(t('plugin.mcp_name_required'))
    return
  }
  savingMcp.value = true
  let config: any
  try {
    config = JSON.parse(mcpConfigJson.value)
  } catch {
    ElMessage.error(t('plugin.mcp_invalid_json'))
    savingMcp.value = false
    return
  }
  // Backend expects a JSON object; reject arrays, null, and primitives up
  // front so the user sees the same error as the catch branch instead of a
  // 400 from the server.
  if (config === null || typeof config !== 'object' || Array.isArray(config)) {
    ElMessage.error(t('plugin.mcp_invalid_json'))
    savingMcp.value = false
    return
  }
  try {
    if (mcpEditMode.value && mcpEditId.value) {
      // Don't send `name` on edit — the backend uses the path param as the
      // canonical key and silently drops any rename in the body. Submitting
      // it would falsely advertise a feature that isn't wired up.
      await updateMcpServerConfig(mcpEditId.value, { description: mcpForm.value.description, config })
    } else {
      await createMcpServer({ name: mcpForm.value.name, description: mcpForm.value.description, config })
    }
    mcpDialogVisible.value = false
    ElMessage.success(t('plugin.mcp_save_success'))
    await loadMcpServers()
  } catch {
    ElMessage.error(t('plugin.mcp_save_failed'))
  } finally {
    savingMcp.value = false
  }
}

async function handleDeleteMcp(id: string) {
  try {
    await ElMessageBox.confirm(t('plugin.mcp_delete_confirm'), t('plugin.mcp_delete'), { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteMcpServer(id)
    ElMessage.success(t('plugin.mcp_delete_success'))
    await loadMcpServers()
  } catch {
    ElMessage.error(t('plugin.mcp_delete_failed'))
  }
}

async function loadSkills() {
  try {
    const res = await getSkills()
    skills.value = Array.isArray(res.data) ? res.data : []
    skillsError.value = null
  } catch (e: any) {
    skills.value = []
    skillsError.value = e?.message || t('plugin.skills_load_failed')
    ElMessage.error(skillsError.value!)
  }
}

async function toggleSkillItem(skill: any) {
  try {
    await apiToggleSkill(skill.id, !skill.enabled)
    ElMessage.success(t('plugin.skills_toggle_success'))
  } catch {
    ElMessage.error(t('plugin.skills_toggle_error'))
  } finally {
    await loadSkills()
  }
}

async function refreshSkillList() {
  try {
    await apiRefreshSkills()
    ElMessage.success(t('plugin.skills_refresh_success'))
    await loadSkills()
  } catch {
    ElMessage.error(t('plugin.skills_refresh_error'))
  }
}

function onSkillUploadChange(file: UploadFile) {
  skillUploadFile.value = file.raw || null
}

async function handleSkillUpload() {
  if (!skillUploadFile.value) {
    ElMessage.error(t('plugin.skills_upload_no_file'))
    return
  }
  uploadingSkill.value = true
  try {
    await apiUploadSkill(skillUploadFile.value)
    skillsUploadVisible.value = false
    ElMessage.success(t('plugin.skills_upload_success'))
    await loadSkills()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || ''
    ElMessage.error(`${t('plugin.skills_upload_error')}${msg ? ': ' + msg : ''}`)
  } finally {
    uploadingSkill.value = false
    skillUploadFile.value = null
    if (skillsUploadRef.value) {
      skillsUploadRef.value.clearFiles()
    }
  }
}

onMounted(() => {
  loadPlugins()
  loadMcpServers()
  loadSkills()
})
</script>
