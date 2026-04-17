<template>
  <div>
    <el-tabs v-model="activeTab">
      <!-- Plugins Tab -->
      <el-tab-pane :label="$t('plugin.plugins')" name="plugins">
        <div class="flex items-center justify-between mb-4">
          <div></div>
          <el-button size="small" type="primary" @click="installDialogVisible = true">
            + {{ $t('plugin.install_add') }}
          </el-button>
        </div>

        <div v-if="pluginsError" class="text-center py-12 text-red-500">
          <el-icon :size="48"><SetUp /></el-icon>
          <p class="mt-2 text-sm">{{ pluginsError }}</p>
        </div>
        <div v-else-if="plugins.length === 0" class="text-center py-12 text-gray-400">
          <el-icon :size="48"><SetUp /></el-icon>
          <p class="mt-2 text-sm">{{ $t('plugin.no_plugins') }}</p>
        </div>

        <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <div
            v-for="plugin in displayedPlugins"
            :key="plugin.id"
            class="glass-card rounded-lg p-4 flex flex-col"
          >
            <div class="flex items-start justify-between mb-3">
              <div>
                <div class="text-base font-semibold text-gray-900 dark:text-gray-100">{{ plugin.name || plugin.id }}</div>
                <div v-if="plugin.version || plugin.author" class="mt-1 text-xs text-gray-500">
                  {{ plugin.version ? `v${plugin.version}` : '' }}{{ plugin.version && plugin.author ? ' · ' : '' }}{{ plugin.author || '' }}
                </div>
              </div>
              <div class="flex items-center gap-2">
                <a v-if="plugin.safeRepo" :href="plugin.safeRepo" target="_blank" rel="noopener noreferrer" class="text-xs text-blue-600 hover:text-blue-700">
                  {{ $t('plugin.repo_link') }}
                </a>
                <el-switch
                  :model-value="plugin.enabled"
                  size="small"
                  @change="togglePlugin(plugin)"
                />
              </div>
            </div>
            <p v-if="plugin.description" class="text-sm text-gray-600 dark:text-gray-300 line-clamp-3 mb-3">
              {{ plugin.description }}
            </p>
            <div class="mt-auto">
              <div class="text-xs font-mono text-gray-400 mb-3 break-all">{{ plugin.id }}</div>
              <div class="flex justify-end gap-3">
                <el-button size="small" @click="openPluginConfig(plugin)">{{ $t('plugin.configure') }}</el-button>
                <el-button size="small" type="danger" @click="handleDeletePlugin(plugin.id)">{{ $t('plugin.uninstall') }}</el-button>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- MCP Tab -->
      <el-tab-pane :label="$t('plugin.mcp_servers')" name="mcp">
        <div class="flex items-center justify-between mb-4">
          <div></div>
          <el-button size="small" type="primary" @click="openMcpCreate">
            + {{ $t('plugin.mcp_add') }}
          </el-button>
        </div>

        <div v-if="mcpServersError" class="text-center py-12 text-red-500">
          <el-icon :size="48"><Platform /></el-icon>
          <p class="mt-2 text-sm">{{ mcpServersError }}</p>
        </div>
        <div v-else-if="mcpServers.length === 0" class="text-center py-12 text-gray-400">
          <el-icon :size="48"><Platform /></el-icon>
          <p class="mt-2 text-sm">{{ $t('plugin.no_mcp_servers') }}</p>
        </div>

        <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <div
            v-for="server in mcpServers"
            :key="server.id"
            class="glass-card rounded-lg p-4 flex flex-col"
          >
            <div class="flex items-start justify-between mb-3">
              <div>
                <div class="text-base font-semibold text-gray-900 dark:text-gray-100">{{ server.name || server.id }}</div>
                <el-tag v-if="server.type" size="small" class="mt-1">{{ server.type }}</el-tag>
                <div class="text-xs text-gray-500 mt-1">{{ server.id }}</div>
              </div>
              <el-switch
                :model-value="server.enabled"
                size="small"
                @change="toggleMcp(server)"
              />
            </div>
            <p v-if="server.description" class="text-sm text-gray-600 dark:text-gray-300 mb-3">
              {{ server.description }}
            </p>
            <div class="text-xs text-gray-500 mt-auto mb-3">
              {{ $t('plugin.mcp_tools_label') }}: {{ server.tools_count }}
            </div>
            <div class="flex justify-end gap-3">
              <el-button size="small" @click="openMcpEdit(server)">{{ $t('plugin.mcp_edit') }}</el-button>
              <el-button size="small" type="danger" @click="handleDeleteMcp(server.id)">{{ $t('plugin.mcp_delete') }}</el-button>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

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
import { SetUp, Platform, UploadFilled } from '@element-plus/icons-vue'
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
  plugins.value.map(p => ({ ...p, safeRepo: safeRepoUrl((p as any).repo) })),
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

onMounted(() => {
  loadPlugins()
  loadMcpServers()
})
</script>
