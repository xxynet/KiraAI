<template>
  <div>
    <!-- Title -->
    <div class="flex items-center mb-6">
      <h3 class="text-lg font-semibold text-theme-strong">{{ $t('plugin.title') }}</h3>
    </div>

    <div v-if="!taskQueueDismissed && (pluginTasks.length || taskQueueLoadError)" class="relative mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-900/20">
      <button
        type="button"
        class="absolute right-3 top-3 rounded p-1 text-theme-faint text-theme-faint-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 disabled:opacity-50"
        :aria-label="$t('plugin.task_queue_close')"
        :title="$t('plugin.task_queue_close')"
        :disabled="clearingPluginTasks"
        @click="dismissTaskQueue"
      >
        <IconSpinner v-if="clearingPluginTasks" class="h-4 w-4 animate-spin" />
        <IconClose v-else class="h-4 w-4" />
      </button>
      <div class="flex flex-wrap items-center gap-3 pr-8 text-sm">
        <span class="font-medium text-theme-strong">{{ $t('plugin.task_queue_title') }}</span>
        <span class="text-theme-supporting" role="status">{{ $t('plugin.task_queue_summary', taskQueueSummary) }}</span>
        <button type="button" class="text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400" :disabled="refreshingPluginTasks" @click="refreshPluginTasks">{{ $t('common.refresh') }}</button>
        <button v-if="retryablePluginTasks.length" type="button" class="text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400" :disabled="enqueueingUpdates" @click="retryFailedTasks">{{ $t('plugin.update_retry_failed') }}</button>
      </div>
      <p v-if="taskQueueLoadError" class="mt-2 text-sm text-red-600 dark:text-red-400">{{ $t('plugin.task_queue_status_failed') }}</p>
      <p v-if="pluginOperationsBusy" class="mt-2 text-xs text-theme-subtle">{{ $t('plugin.task_queue_busy') }}</p>
      <details v-if="pluginTasks.length" class="mt-3" :open="pluginOperationsBusy">
        <summary class="cursor-pointer text-sm text-theme-body">{{ $t('plugin.task_queue_details') }}</summary>
        <ul class="mt-2 max-h-64 space-y-2 overflow-y-auto">
          <li v-for="task in pluginTasks" :key="task.task_id" class="rounded-md bg-white p-3 text-sm dark:bg-gray-900">
            <div class="flex items-center gap-2">
              <IconSpinner v-if="task.status === 'running'" class="h-4 w-4 shrink-0 animate-spin text-blue-600" />
              <span class="min-w-0 flex-1 break-words text-theme-strong">{{ $t('plugin.task_operation_' + task.operation) }} · {{ pluginTaskName(task) }}</span>
              <span class="shrink-0 text-theme-subtle">{{ taskStageLabel(task.stage) }}</span>
              <button v-if="storeTaskItem(task)" type="button" class="shrink-0 text-blue-600 hover:underline dark:text-blue-400" @click="viewStoreInstallTask(task)">{{ $t('pluginStore.install_view_progress') }}</button>
              <button v-if="task.status === 'queued' || (task.status === 'running' && task.operation === 'install' && task.stage !== 'loading')" type="button" class="shrink-0 text-red-600 hover:underline dark:text-red-400" @click="cancelQueuedTask(task)">{{ $t('plugin.cancel') }}</button>
              <button v-if="retryablePluginTasks.some(item => item.task_id === task.task_id)" type="button" class="shrink-0 text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400" :disabled="enqueueingUpdates" @click="retryPluginTasks([task])">{{ $t('plugin.update_retry') }}</button>
            </div>
            <p v-if="task.error" class="mt-1 break-words text-red-600 dark:text-red-400">{{ task.error }}</p>
            <p v-if="task.status === 'failed' && task.source === 'upload'" class="mt-1 text-theme-subtle">{{ $t('plugin.task_upload_retry') }}</p>
            <p v-for="(warning, index) in task.warnings" :key="index" class="mt-1 break-words text-amber-700 dark:text-amber-400">{{ warning }}</p>
          </li>
        </ul>
      </details>
    </div>

    <!-- Custom Tabs -->
    <div class="flex flex-wrap gap-x-4 mb-4 border-b border-gray-200 dark:border-gray-700">
      <button
        type="button"
        class="px-3 py-2 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
        :class="activeTab === 'plugins' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-theme-subtle text-theme-subtle-hover hover:border-gray-300 dark:hover:border-gray-600'"
        @click="activeTab = 'plugins'"
      >
        {{ $t('plugin.plugins') }}
      </button>
      <button
        type="button"
        class="px-3 py-2 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
        :class="activeTab === 'pluginStore' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-theme-subtle text-theme-subtle-hover hover:border-gray-300 dark:hover:border-gray-600'"
        @click="activeTab = 'pluginStore'"
      >
        {{ $t('pluginStore.title') }}
      </button>
      <button
        type="button"
        class="px-3 py-2 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
        :class="activeTab === 'mcp' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-theme-subtle text-theme-subtle-hover hover:border-gray-300 dark:hover:border-gray-600'"
        @click="activeTab = 'mcp'"
      >
        {{ $t('plugin.tab_mcp') }}
      </button>
      <button
        type="button"
        class="px-3 py-2 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
        :class="activeTab === 'skills' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-theme-subtle text-theme-subtle-hover hover:border-gray-300 dark:hover:border-gray-600'"
        @click="activeTab = 'skills'"
      >
        {{ $t('plugin.skills') }}
      </button>
      <button
        type="button"
        class="px-3 py-2 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
        :class="activeTab === 'scope' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-theme-subtle text-theme-subtle-hover hover:border-gray-300 dark:hover:border-gray-600'"
        @click="activeTab = 'scope'"
      >
        {{ $t('plugin.scope') }}
      </button>
    </div>

    <!-- Plugins Tab Content -->
    <div v-show="activeTab === 'plugins'">
      <div class="flex flex-wrap items-center gap-2 mb-4">
        <button
          type="button"
          class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-theme-body bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          :disabled="installing"
          @click="openInstallDialog"
        >
          <span class="mr-1">+</span>
          <span>{{ $t('plugin.install_add') }}</span>
        </button>
        <button
          type="button"
          class="inline-flex shrink-0 items-center whitespace-nowrap px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-theme-body bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          :disabled="refreshingPlugins"
          @click="refreshPlugins"
        >
          <IconRefresh class="w-4 h-4 mr-1" :class="{ 'animate-spin': refreshingPlugins }" />
          <span>{{ $t('common.refresh') }}</span>
        </button>
        <button
          v-if="availableUpdateItems.length"
          type="button"
          class="inline-flex items-center rounded-md border border-green-300 px-3 py-1.5 text-xs font-medium text-green-600 hover:bg-green-50 disabled:opacity-50 dark:border-green-600 dark:text-green-400 dark:hover:bg-green-900/30"
          :disabled="enqueueingUpdates"
          @click="openBatchUpdate"
        >
          {{ $t('plugin.update_batch', { count: availableUpdateItems.length }) }}
        </button>
        <div class="relative w-full sm:ml-auto sm:w-56">
          <UiInput
            v-model="pluginsSearchTerm"
            type="text"
            :placeholder="$t('plugin.search_placeholder')"
            :aria-label="$t('plugin.search_placeholder')"
            class="w-full rounded-lg pl-9 pr-3 py-1.5 text-sm transition-colors"
          />
          <IconSearch class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-theme-faint" />
        </div>
      </div>

      <div v-if="pluginsError" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconPuzzle class="w-16 h-16 text-red-400 mx-auto mb-4" />
          <p class="text-red-500">{{ pluginsError }}</p>
        </div>
      </div>

      <div v-else-if="plugins.length === 0" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconPuzzle class="w-16 h-16 text-theme-faint mx-auto mb-4" />
          <p class="text-theme-subtle">{{ $t('plugin.no_plugins') }}</p>
        </div>
      </div>

      <div v-else-if="filteredPlugins.length === 0" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconSearch class="w-8 h-8 text-theme-faint mx-auto mb-2 opacity-50" />
          <p class="text-sm text-theme-faint">{{ $t('plugin.no_search_results') }}</p>
        </div>
      </div>

      <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <PluginCard
          v-for="plugin in filteredPlugins"
          :key="plugin.id"
          mode="installed"
          :id="plugin.id"
          :name="localize(plugin, 'display_name', plugin.name)"
          :version="plugin.version"
          :author="plugin.author"
          :description="localize(plugin, 'description', plugin.description)"
          :repo="plugin.repo"
          :enabled="plugin.enabled"
          :builtin="plugin.builtin"
          :uninstallable="plugin.uninstallable"
          :tags="plugin.tags"
          :core-version="plugin.core_version"
          :error="plugin.error"
          :status="plugin.status"
          :icon="plugin.icon"
          :icon-dark="plugin.icon_dark"
          :reloading="reloadingPlugins.has(plugin.id)"
          :has-update="pluginUpdates.has(plugin.id)"
          :latest-version="pluginUpdates.get(plugin.id)?.latest_version ?? null"
          :updating="updatingPlugins.has(plugin.id)"
          :queued="queuedPlugins.has(plugin.id)"
          :operations-busy="pluginOperationsBusy"
          @toggle="togglePlugin(plugin)"
          @configure="openPluginConfig(plugin)"
          @uninstall="handleDeletePlugin(plugin.id)"
          @reload="handleReloadPlugin(plugin)"
          @update="handleUpdatePlugin(plugin)"
          @details="openPluginDetails(plugin)"
        />
      </div>
    </div>

    <!-- MCP Tab Content -->
    <div v-show="activeTab === 'mcp'">
      <div class="flex flex-wrap items-center gap-2 mb-4">
        <button
          type="button"
          class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-theme-body bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          @click="openMcpCreate"
        >
          <span class="mr-1">+</span>
          <span>{{ $t('plugin.mcp_add') }}</span>
        </button>
      </div>

      <div v-if="mcpServersError" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconInfoCircle class="w-16 h-16 text-red-400 mx-auto mb-4" />
          <p class="text-red-500">{{ mcpServersError }}</p>
        </div>
      </div>

      <div v-else-if="mcpServers.length === 0" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconServer class="w-16 h-16 text-theme-faint mx-auto mb-4" />
          <p class="text-theme-subtle">{{ $t('plugin.no_mcp_servers') }}</p>
        </div>
      </div>

      <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <div
          v-for="server in mcpServers"
          :key="server.id"
          class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 flex flex-col cursor-pointer transition-shadow hover:shadow-md"
          @click="openMcpTools(server)"
        >
          <div class="flex items-start justify-between mb-3">
            <div>
              <div class="text-base font-semibold text-theme-high">{{ server.name || server.id }}</div>
              <div
                v-if="server.type"
                class="mt-1 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
              >
                {{ server.type }}
              </div>
            </div>
            <button
              type="button"
              class="ml-2 relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none"
              :class="server.enabled ? 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500' : 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600'"
              :aria-pressed="server.enabled ? 'true' : 'false'"
              @click.stop="toggleMcp(server)"
            >
              <span
                class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
                :class="server.enabled ? 'translate-x-4' : 'translate-x-0'"
              />
            </button>
          </div>
          <p v-if="server.description" class="text-sm text-theme-supporting line-clamp-3 mb-3">
            {{ server.description }}
          </p>
          <div class="mt-2 text-xs text-theme-subtle">
            {{ $t('plugin.mcp_tools_label') }}: {{ server.tools_count }}
          </div>
          <div class="mt-4 flex items-center justify-end space-x-3 mt-auto">
            <button
              type="button"
              class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-theme-body hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-800 transition-colors"
              @click.stop="openMcpEdit(server)"
            >
              {{ $t('plugin.mcp_edit') }}
            </button>
            <button
              type="button"
              class="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30 transition-colors"
              @click.stop="handleDeleteMcp(server.id)"
            >
              {{ $t('plugin.mcp_delete') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Skills Tab Content -->
    <div v-show="activeTab === 'skills'">
      <div class="flex flex-wrap items-center gap-2 mb-4">
        <button
          type="button"
          class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-theme-body bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors mr-2"
          @click="openSkillsUploadDialog"
        >
          <IconUpload class="w-4 h-4 mr-1" />
          <span>{{ $t('plugin.skills_upload') }}</span>
        </button>
        <button
          type="button"
          class="inline-flex shrink-0 items-center whitespace-nowrap px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-theme-body bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          @click="refreshSkillList"
        >
          <IconRefresh class="w-4 h-4 mr-1" />
          <span>{{ $t('common.refresh') }}</span>
        </button>
      </div>

      <div v-if="skillsError" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconLightbulb class="w-16 h-16 text-red-400 mx-auto mb-4" />
          <p class="text-red-500">{{ skillsError }}</p>
        </div>
      </div>

      <div v-else-if="skills.length === 0" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconLightbulb class="w-16 h-16 text-theme-faint mx-auto mb-4" />
          <p class="text-theme-subtle">{{ $t('plugin.no_skills') }}</p>
        </div>
      </div>

      <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <div
          v-for="skill in skills"
          :key="skill.id"
          class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 flex flex-col"
        >
          <div class="flex items-start justify-between mb-3">
            <div>
              <div class="text-base font-semibold text-theme-high">{{ skill.name || skill.id }}</div>
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
          <p v-if="skill.description" class="text-sm text-theme-supporting line-clamp-3 mb-3">
            {{ skill.description }}
          </p>
          <div class="mt-auto">
            <div class="text-xs font-mono text-theme-faint break-all mb-3">{{ skill.path }}</div>
            <div class="flex items-center justify-between gap-3">
              <div class="text-xs text-theme-faint">{{ formatBytes(skill.size_bytes) }}</div>
              <div class="flex items-center justify-end space-x-3">
              <button
                type="button"
                class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-theme-body hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-800 transition-colors"
                :title="$t('plugin.skills_export')"
                @click="handleExportSkill(skill)"
              >
                <IconDownload class="w-3.5 h-3.5 inline-block mr-1" />{{ $t('plugin.skills_export') }}
              </button>
              <button
                type="button"
                class="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30 transition-colors"
                :title="$t('plugin.skills_delete')"
                @click="handleDeleteSkill(skill)"
              >
                <IconTrash class="w-3.5 h-3.5 inline-block mr-1" />{{ $t('plugin.skills_delete') }}
              </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Scope Tab Content -->
    <div v-show="activeTab === 'scope'">
      <!-- Warning hint -->
      <AlertHint type="warning">{{ $t('plugin.scope_warning') }}</AlertHint>

      <!-- Loading -->
      <div v-if="scopeLoading" class="flex justify-center items-center py-12">
        <IconSpinner class="w-8 h-8 text-blue-500 animate-spin" />
      </div>

      <!-- Error -->
      <div v-else-if="scopeError" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconInfoCircle class="w-16 h-16 text-red-400 mx-auto mb-4" />
          <p class="text-red-500">{{ scopeError }}</p>
        </div>
      </div>

      <template v-else>
        <!-- MCP Servers section -->
        <div class="mb-6">
          <h4 class="text-sm font-semibold text-theme-body mb-3">{{ $t('plugin.scope_mcp_section') }}</h4>
          <div v-if="scopeMcpServers.length === 0" class="text-xs text-theme-faint">-</div>
          <div v-for="mcp in scopeMcpServers" :key="mcp.id" class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 mb-3">
            <div class="flex items-center justify-between mb-2">
              <span class="text-sm font-medium text-theme-strong">{{ mcp.name }}</span>
              <div class="flex items-center space-x-0.5 flex-shrink-0">
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-l-md border transition-colors"
                  :class="scopeEditMcp[mcp.id]?.mode === 'global' ? 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 border-green-300 dark:border-green-700' : 'bg-white dark:bg-gray-800 text-theme-subtle border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
                  @click="onScopeModeChange(mcp.id, 'mcp', 'global')"
                >{{ $t('plugin.scope_global') }}</button>
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs border-t border-b transition-colors"
                  :class="scopeEditMcp[mcp.id]?.mode === 'allow' ? 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 border-blue-300 dark:border-blue-700' : 'bg-white dark:bg-gray-800 text-theme-subtle border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
                  @click="onScopeModeChange(mcp.id, 'mcp', 'allow')"
                >{{ $t('plugin.scope_mode_allow') }}</button>
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-r-md border transition-colors"
                  :class="scopeEditMcp[mcp.id]?.mode === 'deny' ? 'bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300 border-red-300 dark:border-red-700' : 'bg-white dark:bg-gray-800 text-theme-subtle border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
                  @click="onScopeModeChange(mcp.id, 'mcp', 'deny')"
                >{{ $t('plugin.scope_mode_deny') }}</button>
              </div>
            </div>
            <div v-if="scopeEditMcp[mcp.id]?.mode !== 'global'" class="mt-2 pt-2 border-t border-gray-100 dark:border-gray-800">
              <p class="text-xs text-theme-faint mb-1.5">
                {{ scopeEditMcp[mcp.id]?.mode === 'allow' ? $t('plugin.scope_mode_allow_hint') : $t('plugin.scope_mode_deny_hint') }}
              </p>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-0.5">
                <div v-for="s in scopeSessions" :key="s.id" class="flex items-center justify-between py-0.5">
                  <span class="text-xs text-theme-supporting truncate mr-2">{{ s.title ? `${s.title} | ${s.id}` : s.id }}</span>
                  <button
                    type="button"
                    class="ml-2 relative inline-flex h-4 w-7 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none"
                    :class="scopeEditMcp[mcp.id]?.sessions.has(s.id) ? 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500' : 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600'"
                    @click="onScopeSessionToggle(mcp.id, 'mcp', s.id)"
                  >
                    <span
                      class="pointer-events-none inline-block h-3 w-3 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
                      :class="scopeEditMcp[mcp.id]?.sessions.has(s.id) ? 'translate-x-3.5' : 'translate-x-0'"
                    />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Skills section -->
        <div class="mb-6">
          <h4 class="text-sm font-semibold text-theme-body mb-3">{{ $t('plugin.scope_skills_section') }}</h4>
          <div v-if="scopeSkills.length === 0" class="text-xs text-theme-faint">-</div>
          <div v-for="skill in scopeSkills" :key="skill.name" class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 mb-3">
            <div class="flex items-center justify-between mb-2">
              <span class="text-sm font-medium text-theme-strong">{{ skill.name }}</span>
              <div class="flex items-center space-x-0.5 flex-shrink-0">
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-l-md border transition-colors"
                  :class="scopeEditSkill[skill.name]?.mode === 'global' ? 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 border-green-300 dark:border-green-700' : 'bg-white dark:bg-gray-800 text-theme-subtle border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
                  @click="onScopeModeChange(skill.name, 'skill', 'global')"
                >{{ $t('plugin.scope_global') }}</button>
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs border-t border-b transition-colors"
                  :class="scopeEditSkill[skill.name]?.mode === 'allow' ? 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 border-blue-300 dark:border-blue-700' : 'bg-white dark:bg-gray-800 text-theme-subtle border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
                  @click="onScopeModeChange(skill.name, 'skill', 'allow')"
                >{{ $t('plugin.scope_mode_allow') }}</button>
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-r-md border transition-colors"
                  :class="scopeEditSkill[skill.name]?.mode === 'deny' ? 'bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300 border-red-300 dark:border-red-700' : 'bg-white dark:bg-gray-800 text-theme-subtle border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
                  @click="onScopeModeChange(skill.name, 'skill', 'deny')"
                >{{ $t('plugin.scope_mode_deny') }}</button>
              </div>
            </div>
            <div v-if="scopeEditSkill[skill.name]?.mode !== 'global'" class="mt-2 pt-2 border-t border-gray-100 dark:border-gray-800">
              <p class="text-xs text-theme-faint mb-1.5">
                {{ scopeEditSkill[skill.name]?.mode === 'allow' ? $t('plugin.scope_mode_allow_hint') : $t('plugin.scope_mode_deny_hint') }}
              </p>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-0.5">
                <div v-for="s in scopeSessions" :key="s.id" class="flex items-center justify-between py-0.5">
                  <span class="text-xs text-theme-supporting truncate mr-2">{{ s.title ? `${s.title} | ${s.id}` : s.id }}</span>
                  <button
                    type="button"
                    class="ml-2 relative inline-flex h-4 w-7 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none"
                    :class="scopeEditSkill[skill.name]?.sessions.has(s.id) ? 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500' : 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600'"
                    @click="onScopeSessionToggle(skill.name, 'skill', s.id)"
                  >
                    <span
                      class="pointer-events-none inline-block h-3 w-3 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
                      :class="scopeEditSkill[skill.name]?.sessions.has(s.id) ? 'translate-x-3.5' : 'translate-x-0'"
                    />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Save button -->
        <div class="flex justify-end">
          <button
            type="button"
            class="px-5 py-2 bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 text-white rounded-lg text-sm font-medium transition-colors"
            :disabled="savingScope"
            @click="saveScope"
          >
            {{ $t('plugin.save') }}
          </button>
        </div>
      </template>
    </div>

    <!-- Plugin Store Tab Content -->
    <div v-show="activeTab === 'pluginStore'">
      <!-- Plugin Sources Button -->
      <div class="flex flex-wrap items-center gap-2 mb-4">
        <button
          type="button"
          class="inline-flex shrink-0 items-center whitespace-nowrap px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-theme-body bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          @click="openSourceManage"
        >
          <IconCog class="w-4 h-4 mr-1" />
          <span>{{ $t('pluginStore.sources') }}</span>
        </button>
        <button
          v-if="currentStoreSource"
          type="button"
          class="inline-flex shrink-0 items-center whitespace-nowrap px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-theme-body bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          :disabled="storeLoading"
          @click="() => fetchStorePlugins(true)"
        >
          <IconRefresh class="w-4 h-4 mr-1" :class="{ 'animate-spin': storeLoading }" />
          <span>{{ $t('common.refresh') }}</span>
        </button>
        <span v-if="currentStoreSource" class="w-full text-sm text-theme-subtle sm:w-auto sm:ml-1">
          {{ $t('pluginStore.current_source') }}: <span class="font-medium text-theme-body">{{ currentStoreSource.name }}</span>
        </span>
        <div v-if="currentStoreSource && !storeLoading && storePlugins.length > 0" class="flex w-full flex-col gap-3 sm:ml-auto sm:w-auto sm:flex-row sm:flex-wrap sm:items-center sm:justify-end">
          <label class="flex w-full items-center justify-between gap-2 text-sm text-theme-supporting sm:w-auto sm:justify-start">
            <span>{{ $t('pluginStore.category') }}</span>
            <div class="w-32 shrink-0 plugin-store-select">
              <CustomSelect v-model="storeCategory" :options="storeCategoryOptions" />
            </div>
          </label>
          <label class="flex w-full items-center justify-between gap-2 text-sm text-theme-supporting sm:w-auto sm:justify-start">
            <span>{{ $t('pluginStore.sort') }}</span>
            <div class="w-32 shrink-0 plugin-store-select">
              <CustomSelect v-model="storeSort" :options="storeSortOptions" />
            </div>
          </label>
          <div class="relative w-full sm:w-56">
            <UiInput
              v-model="storeSearchTerm"
              type="text"
              :placeholder="$t('plugin.search_placeholder')"
              :aria-label="$t('plugin.search_placeholder')"
              class="w-full rounded-lg pl-9 pr-3 py-1.5 text-sm transition-colors"
            />
            <IconSearch class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-theme-faint" />
          </div>
        </div>
      </div>

      <!-- Plugin Store Error -->
      <div v-if="storeError" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconInfo class="w-16 h-16 text-red-400 mx-auto mb-4" />
          <p class="text-red-500">{{ storeError }}</p>
          <button
            type="button"
            class="mt-3 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            @click="() => fetchStorePlugins()"
          >
            {{ $t('common.refresh') }}
          </button>
        </div>
      </div>

      <!-- No Source Configured -->
      <div v-else-if="!currentStoreSource" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconPackage class="w-16 h-16 text-theme-faint mx-auto mb-4" />
          <p class="text-theme-subtle mb-3">{{ $t('pluginStore.no_sources') }}</p>
          <button
            type="button"
            class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors"
            @click="openSourceManage"
          >
            {{ $t('pluginStore.add_source') }}
          </button>
        </div>
      </div>

      <!-- Loading -->
      <div v-else-if="storeLoading" class="flex justify-center items-center py-12">
        <IconSpinner class="animate-spin h-8 w-8 text-blue-600 dark:text-blue-400" />
      </div>

      <!-- No Plugins Available -->
      <div v-else-if="storePlugins.length === 0" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconBox class="w-16 h-16 text-theme-faint mx-auto mb-4" />
          <p class="text-theme-subtle">{{ $t('pluginStore.no_plugins') }}</p>
        </div>
      </div>

      <!-- No Search Results -->
      <div v-else-if="filteredStorePlugins.length === 0" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconSearch class="w-8 h-8 text-theme-faint mx-auto mb-2 opacity-50" />
          <p class="text-sm text-theme-faint">{{ $t('plugin.no_search_results') }}</p>
        </div>
      </div>

      <!-- Plugin Cards Grid -->
      <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <PluginCard
          v-for="item in paginatedStorePlugins"
          :key="item.id"
          mode="store"
          :id="item.id"
          :name="localize(item, 'display_name', item.name)"
          :version="item.version"
          :author="item.author"
          :description="localize(item, 'description', item.description)"
          :repo="item.repo"
          :icon="item.icon"
          :icon-dark="item.icon_dark"
          :tags="item.tags"
          :core-version="item.core_version"
          :installed="item.installed"
          :installing="pendingStoreInstall(item)"
          :has-update="item.installed && pluginUpdates.has(item.id)"
          :latest-version="pluginUpdates.get(item.id)?.latest_version ?? null"
          :updating="updatingPlugins.has(item.id)"
          :queued="queuedPlugins.has(item.id)"
          :operations-busy="pluginOperationsBusy"
          @install="handleStoreInstall(item)"
          @update="handleStoreUpdate(item)"
          @details="openPluginDetails(item)"
        />
      </div>

      <nav v-if="filteredStorePlugins.length > STORE_PAGE_SIZE" :aria-label="$t('pluginStore.pagination_label')" class="mt-6 flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          class="px-3 py-1.5 text-sm font-medium rounded-md border border-gray-300 text-theme-body hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:hover:bg-gray-800"
          :disabled="storePage === 1"
          @click="storePage--"
        >
          {{ $t('pluginStore.pagination_previous') }}
        </button>
        <template v-for="page in storePageNumbers" :key="page">
          <button
            v-if="typeof page === 'number'"
            type="button"
            class="min-w-8 px-2 py-1.5 text-sm font-medium rounded-md border transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
            :class="page === storePage
              ? 'border-blue-600 bg-blue-600 text-white dark:border-blue-500 dark:bg-blue-500'
              : 'border-gray-300 text-theme-body hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-800'"
            :aria-label="$t('pluginStore.pagination_page', { page })"
            :aria-current="page === storePage ? 'page' : undefined"
            @click="storePage = page"
          >
            {{ page }}
          </button>
          <span v-else class="px-1 text-sm text-theme-subtle" aria-hidden="true">…</span>
        </template>
        <button
          type="button"
          class="px-3 py-1.5 text-sm font-medium rounded-md border border-gray-300 text-theme-body hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:hover:bg-gray-800"
          :disabled="storePage === storeTotalPages"
          @click="storePage++"
        >
          {{ $t('pluginStore.pagination_next') }}
        </button>
      </nav>

      <!-- Plugin Sources Management Modal -->
      <Modal v-model="sourceManageVisible" content-class="max-w-lg">
        <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
          <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <h3 class="text-lg font-semibold text-theme-strong">{{ $t('pluginStore.source_manage') }}</h3>
            <button type="button" class="text-theme-faint text-theme-faint-hover" @click="sourceManageVisible = false">
              <IconClose class="w-6 h-6" />
            </button>
          </div>
          <div class="px-6 py-5 flex-1 overflow-y-auto space-y-4">
            <p class="text-sm text-theme-subtle">{{ $t('pluginStore.source_manage_desc') }}</p>

            <!-- Existing Sources List -->
            <div v-if="pluginSources.length > 0" class="space-y-2">
              <div
                v-for="src in pluginSources"
                :key="src.id"
                class="flex items-center justify-between p-3 rounded-lg border transition-colors"
                :class="currentStoreSource && currentStoreSource.id === src.id
                  ? 'border-blue-300 bg-blue-50 dark:border-blue-700 dark:bg-blue-900/20'
                  : 'border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800'"
              >
                <div class="flex-1 min-w-0 mr-3">
                  <div class="text-sm font-medium text-theme-high">{{ src.name }}</div>
                  <div class="text-xs text-theme-subtle truncate">{{ src.url }}</div>
                </div>
                <div class="flex items-center space-x-2">
                  <button
                    v-if="!currentStoreSource || currentStoreSource.id !== src.id"
                    type="button"
                    class="px-2.5 py-1 text-xs font-medium rounded-md border border-blue-300 text-blue-600 hover:bg-blue-50 dark:border-blue-600 dark:text-blue-400 dark:hover:bg-blue-900/30 transition-colors"
                    @click="switchToSource(src)"
                  >
                    {{ $t('pluginStore.switch_source') }}
                  </button>
                  <span
                    v-else
                    class="px-2.5 py-1 text-xs font-medium rounded-md bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
                  >
                    {{ $t('pluginStore.current_source') }}
                  </span>
                  <button
                    type="button"
                    class="px-2.5 py-1 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30 transition-colors"
                    @click="removeSource(pluginSources.indexOf(src))"
                  >
                    {{ $t('pluginStore.remove_source') }}
                  </button>
                </div>
              </div>
            </div>
            <div v-else class="text-center py-4 text-sm text-theme-faint">
              {{ $t('pluginStore.no_sources') }}
            </div>

            <!-- Add New Source Form -->
            <div class="border-t border-gray-200 dark:border-gray-700 pt-4">
              <div class="mb-3">
                <label class="block text-sm font-medium text-theme-body mb-1">{{ $t('pluginStore.source_name') }}</label>
                <UiInput
                  v-model="newSourceName"
                  type="text"
                  :placeholder="$t('pluginStore.source_name_placeholder')"
                  class="w-full rounded-lg px-3 py-2 transition-colors"
                />
              </div>
              <div class="mb-3">
                <label class="block text-sm font-medium text-theme-body mb-1">{{ $t('pluginStore.source_url') }}</label>
                <UiInput
                  v-model="newSourceUrl"
                  type="text"
                  :placeholder="$t('pluginStore.source_url_placeholder')"
                  class="w-full rounded-lg px-3 py-2 transition-colors"
                />
              </div>
            </div>
          </div>
          <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
            <button
              type="button"
              class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              @click="sourceManageVisible = false"
            >
              {{ $t('pluginStore.cancel') }}
            </button>
            <button
              type="button"
              class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="!newSourceName.trim() || !newSourceUrl.trim()"
              @click="addNewSource"
            >
              {{ $t('pluginStore.add_source') }}
            </button>
          </div>
        </div>
      </Modal>
    </div>

    <Modal v-model="storeInstallVisible" content-class="max-w-lg">
      <div v-if="storeInstallTarget" class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex items-start justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-theme-strong">{{ $t('pluginStore.install_details_title') }}</h3>
          <button type="button" class="text-theme-faint text-theme-faint-hover" @click="storeInstallVisible = false"><IconClose class="w-6 h-6" /></button>
        </div>
        <div class="px-6 py-5 space-y-4 overflow-y-auto">
          <div class="flex min-w-0 items-start gap-3">
            <div v-if="storeInstallIcon" class="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-[10px]">
              <img :src="storeInstallIcon" :alt="''" class="h-full w-full object-contain" />
            </div>
            <div class="min-w-0">
              <p class="truncate text-base font-semibold text-theme-high">{{ storePluginName(storeInstallTarget) }}</p>
              <p v-if="storeInstallTarget.version || storeInstallTarget.author" class="mt-1 text-xs text-theme-subtle">v{{ storeInstallTarget.version }}<span v-if="storeInstallTarget.version && storeInstallTarget.author"> · </span>{{ storeInstallTarget.author }}</p>
            </div>
          </div>
          <p v-if="storeInstallTarget.description" class="whitespace-pre-wrap text-sm leading-6 text-theme-supporting">{{ localize(storeInstallTarget, 'description', storeInstallTarget.description) }}</p>
          <div v-if="storeInstallTarget.tags?.length" class="flex flex-wrap gap-1.5">
            <span v-for="tag in storeInstallTarget.tags" :key="tag" class="inline-block rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">{{ tag }}</span>
          </div>
          <dl class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            <div><dt class="text-theme-subtle">{{ $t('plugin.plugin_id') }}</dt><dd class="mt-1 font-mono break-all text-theme-high">{{ storeInstallTarget.id }}</dd></div>
            <div v-if="storeInstallRepo" class="sm:col-span-2"><dt class="text-theme-subtle">{{ $t('plugin.repo_url') }}</dt><dd class="mt-1 break-all"><a :href="storeInstallRepo" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:text-blue-700 hover:underline dark:text-blue-400 dark:hover:text-blue-300">{{ storeInstallRepo }}</a></dd></div>
          </dl>
          <div v-if="storeInstallTask" class="rounded-md border border-gray-200 p-3 text-sm dark:border-gray-700">
            <div class="flex items-center gap-2 text-theme-body"><IconSpinner v-if="storeInstallTask.status === 'running'" class="h-4 w-4 animate-spin text-blue-600" /><span>{{ storeInstallStageLabel }}</span></div>
            <p v-if="storeInstallTask.error" class="mt-2 break-words text-red-600 dark:text-red-400">{{ storeInstallTask.error }}</p>
          </div>
        </div>
        <div class="flex justify-end gap-3 border-t border-gray-200 px-6 py-4 dark:border-gray-700">
          <template v-if="storeInstallPending">
            <button type="button" class="px-4 py-2 border border-red-300 text-red-600 rounded-lg hover:bg-red-50 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-900/30 transition-colors disabled:opacity-50" :disabled="storeInstallTask?.stage === 'loading'" @click="cancelStoreInstall">{{ $t('pluginStore.install_cancel') }}</button>
            <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors" @click="storeInstallVisible = false">{{ $t('pluginStore.install_silent') }}</button>
          </template>
          <button v-else-if="storeInstallTask" type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors" @click="storeInstallVisible = false">{{ $t('plugin.close') }}</button>
          <template v-else>
            <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="storeInstallVisible = false">{{ $t('plugin.cancel') }}</button>
            <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors" :disabled="installing" @click="startStoreInstall">{{ $t('pluginStore.install') }}</button>
          </template>
        </div>
      </div>
    </Modal>

    <!-- Install Plugin Dialog -->
    <Modal v-model="installDialogVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-theme-strong">{{ $t('plugin.install_add') }}</h3>
          <button type="button" class="text-theme-faint text-theme-faint-hover" @click="installDialogVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="flex border-b border-gray-200 dark:border-gray-700 px-6">
          <button
            type="button"
            class="px-4 py-3 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
            :class="installTab === 'github' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-theme-subtle text-theme-subtle-hover hover:border-gray-300 dark:hover:border-gray-600'"
            @click="installTab = 'github'"
          >
            GitHub
          </button>
          <button
            type="button"
            class="px-4 py-3 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
            :class="installTab === 'upload' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-theme-subtle text-theme-subtle-hover hover:border-gray-300 dark:hover:border-gray-600'"
            @click="installTab = 'upload'"
          >
            {{ $t('plugin.upload_zip') }}
          </button>
        </div>
        <div class="px-6 py-5 flex-1 overflow-y-auto">
          <div v-show="installTab === 'github'">
            <div class="mb-4">
              <label class="block text-sm font-medium text-theme-body mb-2">{{ $t('plugin.repo_url') }}</label>
              <UiInput
                v-model="installForm.repo_url"
                type="text"
                placeholder="https://github.com/owner/repo"
                class="w-full rounded-lg px-3 py-2 transition-colors"
              />
            </div>
            <div>
              <label class="block text-sm font-medium text-theme-body mb-2">
                <span>{{ $t('plugin.install_gh_proxy_label') }}</span>
                <span class="text-xs font-normal text-theme-faint ml-1">{{ $t('plugin.install_optional') }}</span>
              </label>
              <CustomSelect
                v-model="proxyStrategy"
                :options="proxyStrategyOptions"
                :placeholder="$t('plugin.proxy_strategy_auto')"
              />
            </div>
            <div v-if="proxyStrategy === 'specific'" class="mt-3">
              <CustomSelect
                v-model="selectedProxyUrl"
                :options="proxySelectOptions"
                :placeholder="$t('plugin.proxy_select_placeholder')"
              />
            </div>
          </div>
          <div v-show="installTab === 'upload'">
            <label class="block text-sm font-medium text-theme-body mb-2">{{ $t('plugin.install_upload_label') }}</label>
            <FileDropzone
              ref="installDropzoneRef"
              v-model="uploadFile"
              accept=".zip"
              :title-fallback="$t('plugin.upload_hint')"
              :reselect-fallback="$t('plugin.upload_hint')"
            />
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="installDialogVisible = false">{{ $t('plugin.cancel') }}</button>
          <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="installing" @click="handleInstall">{{ $t('plugin.install') }}</button>
        </div>
      </div>
    </Modal>

    <!-- Update Plugin Dialog -->
    <Modal v-model="updateDialogVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-theme-strong">{{ $t('plugin.update') }}</h3>
          <button type="button" class="text-theme-faint text-theme-faint-hover" @click="updateDialogVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-5 flex-1 overflow-y-auto">
          <p class="text-sm text-theme-supporting mb-4">
            {{ selectedUpdateItems.length === 1 ? $t('plugin.update_confirm', { name: updateItemName(selectedUpdateItems[0]!) }) : $t('plugin.update_batch_confirm', { count: selectedUpdateItems.length }) }}
          </p>
          <ul class="mb-4 max-h-40 space-y-2 overflow-y-auto text-sm text-theme-body">
            <li v-for="item in updateTargetItems" :key="item.plugin_id">
              <label class="flex cursor-pointer items-start gap-2">
                <input
                  v-model="selectedUpdatePluginIds"
                  type="checkbox"
                  :value="item.plugin_id"
                  :disabled="enqueueingUpdates"
                  class="ui-checkbox mt-0.5"
                />
                <span class="min-w-0 break-words">{{ updateItemName(item) }}</span>
              </label>
            </li>
          </ul>
          <div class="mb-4">
            <label class="block text-sm font-medium text-theme-body mb-2">
              <span>{{ $t('plugin.install_gh_proxy_label') }}</span>
              <span class="text-xs font-normal text-theme-faint ml-1">{{ $t('plugin.install_optional') }}</span>
            </label>
            <CustomSelect
              v-model="proxyStrategy"
              :options="proxyStrategyOptions"
              :placeholder="$t('plugin.proxy_strategy_auto')"
            />
          </div>
          <div v-if="proxyStrategy === 'specific'">
            <CustomSelect
              v-model="selectedProxyUrl"
              :options="proxySelectOptions"
              :placeholder="$t('plugin.proxy_select_placeholder')"
            />
          </div>
        </div>
        <div class="flex justify-end px-6 py-4 border-t border-gray-200 dark:border-gray-700">
          <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="updateDialogVisible = false">{{ $t('plugin.cancel') }}</button>
          <button type="button" class="px-4 py-2 ml-2 bg-green-600 dark:bg-green-700 text-white rounded-lg hover:bg-green-700 dark:hover:bg-green-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="enqueueingUpdates || !selectedUpdateItems.length" @click="confirmUpdate">{{ $t('plugin.update') }}</button>
        </div>
      </div>
    </Modal>

    <!-- Plugin Details Dialog -->
    <Modal v-model="pluginDetailsVisible" content-class="max-w-4xl">
      <div v-if="selectedPlugin" class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col overflow-hidden" style="max-height: 90vh;">
        <div class="flex items-start justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <div class="min-w-0 pr-4">
            <h3 class="text-lg font-semibold text-theme-strong">{{ $t('plugin.details_title') }}</h3>
            <p class="mt-1 text-sm text-theme-subtle break-words">
              {{ localize(selectedPlugin, 'display_name', selectedPlugin.name || selectedPlugin.id) }}
            </p>
          </div>
          <button type="button" class="flex-shrink-0 text-theme-faint text-theme-faint-hover" :aria-label="$t('plugin.close')" @click="pluginDetailsVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-5 flex-1 min-h-0 overflow-y-auto space-y-5">
          <p v-if="localize(selectedPlugin, 'description', selectedPlugin.description)" class="whitespace-pre-wrap text-sm leading-6 text-theme-supporting">
            {{ localize(selectedPlugin, 'description', selectedPlugin.description) }}
          </p>
          <p v-else class="text-sm text-theme-faint">{{ $t('plugin.no_description') }}</p>

          <dl class="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 text-sm">
            <div>
              <dt class="text-theme-subtle">{{ $t('plugin.plugin_id') }}</dt>
              <dd class="mt-1 font-mono break-all text-theme-high">{{ selectedPlugin.id }}</dd>
            </div>
            <div v-if="selectedPlugin.version">
              <dt class="text-theme-subtle">{{ $t('plugin.version') }}</dt>
              <dd class="mt-1 text-theme-high">v{{ selectedPlugin.version }}</dd>
            </div>
            <div v-if="selectedPlugin.author">
              <dt class="text-theme-subtle">{{ $t('plugin.author') }}</dt>
              <dd class="mt-1 text-theme-high">{{ selectedPlugin.author }}</dd>
            </div>
            <div v-if="pluginDetailsRepo">
              <dt class="text-theme-subtle">{{ $t('plugin.repo_url') }}</dt>
              <dd class="mt-1 break-all">
                <a :href="pluginDetailsRepo" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:text-blue-700 hover:underline dark:text-blue-400 dark:hover:text-blue-300">
                  {{ pluginDetailsRepo }}
                </a>
              </dd>
            </div>
            <div v-if="'category' in selectedPlugin && selectedPlugin.category">
              <dt class="text-theme-subtle">{{ $t('plugin.category') }}</dt>
              <dd class="mt-1 text-theme-high">{{ storeCategoryName(selectedPlugin) }}</dd>
            </div>
            <div v-if="'core_version' in selectedPlugin && selectedPlugin.core_version">
              <dt class="text-theme-subtle">{{ $t('plugin.core_version') }}</dt>
              <dd class="mt-1 text-theme-high">{{ selectedPlugin.core_version }}</dd>
            </div>
          </dl>

          <div v-if="selectedPlugin.tags?.length">
            <p class="text-sm text-theme-subtle">{{ $t('plugin.tags') }}</p>
            <div class="mt-2 flex flex-wrap gap-1.5">
              <span v-for="tag in selectedPlugin.tags" :key="tag" class="inline-block rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">{{ tag }}</span>
            </div>
          </div>

          <div>
            <div role="tablist" :aria-label="$t('plugin.details_title')" class="flex gap-4 border-b border-gray-200 dark:border-gray-700" @keydown="onPluginDetailsTabKeydown">
              <button
                v-for="tab in pluginDetailsTabs"
                :id="`plugin-details-tab-${tab}`"
                :key="tab"
                type="button"
                role="tab"
                :aria-selected="pluginDetailsTab === tab"
                :aria-controls="`plugin-details-panel-${tab}`"
                :tabindex="pluginDetailsTab === tab ? 0 : -1"
                class="px-3 py-2 text-sm font-medium border-b-2 transition-colors duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
                :class="pluginDetailsTab === tab ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-theme-subtle text-theme-subtle-hover hover:border-gray-300 dark:hover:border-gray-600'"
                @click="pluginDetailsTab = tab"
              >
                {{ $t(tab === 'readme' ? 'plugin.readme_title' : 'plugin.components_title') }}
              </button>
            </div>
            <div v-show="pluginDetailsTab === 'readme'" id="plugin-details-panel-readme" role="tabpanel" aria-labelledby="plugin-details-tab-readme" tabindex="0" class="pt-4">
              <PluginReadme v-if="pluginReadmeLoading || pluginReadme" :readme="pluginReadme" :loading="pluginReadmeLoading" :repo-url="pluginDetailsRepo" />
              <p v-else class="text-sm text-theme-subtle">{{ $t('plugin.no_readme') }}</p>
            </div>
            <div v-show="pluginDetailsTab === 'components'" id="plugin-details-panel-components" role="tabpanel" aria-labelledby="plugin-details-tab-components" tabindex="0" class="pt-4">
              <p v-if="pluginComponentsLoading" class="text-sm text-theme-subtle">{{ $t('plugin.status_loading') }}</p>
              <div v-else-if="pluginComponentsError" class="flex items-center gap-3 text-sm">
                <p class="text-red-600 dark:text-red-400">{{ $t('plugin.components_load_error') }}</p>
                <button type="button" class="text-blue-600 dark:text-blue-400 hover:underline" @click="loadPluginComponents(selectedPlugin.id, pluginDetailsRequest)">{{ $t('plugin.components_retry') }}</button>
              </div>
              <p v-else-if="!selectedPluginInstalled" class="text-sm text-theme-subtle">{{ $t('plugin.components_not_installed') }}</p>
              <PluginComponents v-else :components="pluginComponents" />
            </div>
          </div>
        </div>
      </div>
    </Modal>

    <Modal v-model="pluginConfigVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <div>
            <h3 class="text-lg font-semibold text-theme-strong">{{ $t('plugin.config_modal_title') }}</h3>
            <p class="mt-1 text-sm text-theme-subtle">{{ configPluginName }}</p>
          </div>
          <button type="button" class="text-theme-faint text-theme-faint-hover" @click="pluginConfigVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-4 flex-1 overflow-y-auto">
          <div v-if="configLoading" class="flex justify-center items-center py-12">
            <IconSpinner class="animate-spin h-6 w-6 text-blue-600 dark:text-blue-400" />
          </div>
          <div v-else-if="hasPluginConfigFields">
            <ConfigForm ref="configFormRef" v-model="pluginConfigValues" :schema="pluginConfigSchema" />
          </div>
          <div v-else class="text-center py-8 text-theme-faint">
            <CircleCheck class="mx-auto mb-3 h-10 w-10" />
            <p>{{ $t('plugin.no_config') }}</p>
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="pluginConfigVisible = false">{{ $t('plugin.cancel') }}</button>
          <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="!hasPluginConfigFields || savingConfig" @click="savePluginConfig">{{ $t('plugin.save') }}</button>
        </div>
      </div>
    </Modal>

    <!-- Skills Upload Dialog -->
    <Modal v-model="skillsUploadVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-theme-strong">{{ $t('plugin.skills_upload') }}</h3>
          <button type="button" class="text-theme-faint text-theme-faint-hover" @click="skillsUploadVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-5 flex-1 overflow-y-auto">
          <label class="block text-sm font-medium text-theme-body mb-2">{{ $t('plugin.skills_upload_label') }}</label>
          <FileDropzone
            ref="skillsDropzoneRef"
            v-model="skillUploadFile"
            accept=".zip"
            :title-fallback="$t('plugin.upload_hint')"
            :reselect-fallback="$t('plugin.upload_hint')"
          />
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="skillsUploadVisible = false">{{ $t('plugin.cancel') }}</button>
          <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="uploadingSkill" @click="handleSkillUpload">{{ $t('plugin.skills_upload_btn') }}</button>
        </div>
      </div>
    </Modal>

    <!-- MCP Config Dialog -->
    <Modal v-model="mcpDialogVisible" content-class="max-w-4xl">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col modal-card" style="max-height: 95vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-theme-strong">{{ mcpEditMode ? $t('plugin.mcp_edit') : $t('plugin.mcp_add') }}</h3>
          <button type="button" class="text-theme-faint text-theme-faint-hover" @click="mcpDialogVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-4 flex-1 overflow-y-auto space-y-4">
          <div>
            <label class="block text-sm font-medium text-theme-body mb-2">{{ $t('plugin.mcp_name') }}</label>
            <UiInput
              v-model="mcpForm.name"
              type="text"
              class="w-full rounded-lg px-3 py-2 transition-colors"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-theme-body mb-2">{{ $t('plugin.mcp_description') }}</label>
            <UiTextarea
              v-model="mcpForm.description"
              rows="2"
              class="w-full rounded-lg px-3 py-2 transition-colors resize-none"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-theme-body mb-2">{{ $t('plugin.mcp_template') }}</label>
            <CustomSelect
              :model-value="mcpTemplate"
              :options="mcpTemplateOptions"
              @update:model-value="onMcpTemplateChange"
            />
            <p class="mt-1 text-xs text-theme-faint">{{ $t('plugin.mcp_template_hint') }}</p>
          </div>
          <div>
            <label class="block text-sm font-medium text-theme-body mb-2">{{ $t('plugin.mcp_config') }}</label>
            <MonacoEditor v-model="mcpConfigJson" language="json" height="300px" />
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="mcpDialogVisible = false">{{ $t('plugin.cancel') }}</button>
          <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="savingMcp" @click="saveMcpForm">{{ $t('plugin.save') }}</button>
        </div>
      </div>
    </Modal>

    <!-- MCP Tools Dialog -->
    <Modal v-model="mcpToolsDialogVisible" content-class="max-w-2xl">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col modal-card" style="max-height: 80vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-theme-strong">{{ $t('plugin.mcp_tools_title', { name: selectedMcpServer?.name || selectedMcpServer?.id || '' }) }}</h3>
          <button type="button" class="text-theme-faint text-theme-faint-hover" @click="mcpToolsDialogVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-4 flex-1 overflow-y-auto">
          <div v-if="mcpToolsLoading" class="flex justify-center py-8">
            <IconSpinner class="w-6 h-6 animate-spin text-theme-faint" />
          </div>
          <p v-else-if="mcpToolsError" class="text-sm text-red-500">{{ mcpToolsError }}</p>
          <p v-else-if="mcpTools.length === 0" class="py-4 text-center text-sm text-theme-subtle">{{ $t('plugin.mcp_tools_empty') }}</p>
          <div v-else class="space-y-3">
            <p class="text-xs text-theme-faint">{{ $t('plugin.mcp_tool_toggle_hint') }}</p>
            <div v-for="tool in mcpTools" :key="tool.name" class="rounded-lg border border-gray-200 p-3 dark:border-gray-700">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <code class="text-sm font-medium text-theme-high">{{ tool.name }}</code>
                  <p v-if="tool.description" class="mt-1 text-sm text-theme-supporting whitespace-pre-wrap">{{ tool.description }}</p>
                </div>
                <button
                  type="button"
                  class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none"
                  :class="tool.enabled ? 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500' : 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600'"
                  :aria-pressed="tool.enabled ? 'true' : 'false'"
                  :aria-label="$t('plugin.mcp_tool_toggle_label', { name: tool.name })"
                  @click="toggleMcpToolItem(tool)"
                >
                  <span
                    class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
                    :class="tool.enabled ? 'translate-x-4' : 'translate-x-0'"
                  />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Modal>

    <!-- Confirm Modal -->
    <ConfirmModal
      ref="confirmModalRef"
      :title="confirmTitle"
      :message="confirmMessage"
      :cancel-text="t('plugin.cancel')"
      :confirm-text="confirmButtonText"
      @confirm="onConfirmAction"
      @cancel="onCancelAction"
    >
      <div v-if="isUninstallConfirm" class="px-6 pb-2 space-y-2">
        <label class="flex items-center gap-2 text-sm text-theme-body cursor-pointer">
          <input type="checkbox" v-model="uninstallDeleteConfig" class="ui-checkbox" />
          {{ t('plugin.delete_config') }}
        </label>
        <label class="flex items-center gap-2 text-sm text-theme-body cursor-pointer">
          <input type="checkbox" v-model="uninstallDeleteData" class="ui-checkbox" />
          {{ t('plugin.delete_data') }}
        </label>
      </div>
    </ConfirmModal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleCheck } from '@element-plus/icons-vue'
import { useLocalized } from '@/composables/useLocalized'
import { notify } from '@/composables/useNotification'
import { useTheme } from '@/composables/useTheme'
import Modal from '@/components/common/Modal.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
import FileDropzone from '@/components/common/FileDropzone.vue'
import AlertHint from '@/components/common/AlertHint.vue'
import PluginReadme from '@/components/common/PluginReadme.vue'
import PluginComponents from '@/components/common/PluginComponents.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiTextarea from '@/components/ui/UiTextarea.vue'

import {
  getPlugins, getPluginConfig, getPluginReadme, getPluginComponents, updatePluginConfig,
  togglePlugin as apiTogglePlugin, deletePlugin,
  enqueueGithubInstall, enqueueUploadInstall, retryPluginTask,
  reloadPlugin as apiReloadPlugin,
  checkPluginUpdates, enqueueTaskUpdates, getPluginTasks, cancelPluginTask, clearFinishedPluginTasks,
} from '@/api/plugin'
import {
  getMcpServers, getMcpServerConfig, getMcpServerTools, createMcpServer, updateMcpServerConfig,
  deleteMcpServer, toggleMcpServer, toggleMcpTool,
} from '@/api/mcp'
import {
  getSkills, toggleSkill as apiToggleSkill, refreshSkills as apiRefreshSkills, uploadSkill as apiUploadSkill,
  exportSkill as apiExportSkill, deleteSkill as apiDeleteSkill,
} from '@/api/skills'
import { getScope, updateScope } from '@/api/scope'
import MonacoEditor from '@/components/common/MonacoEditor.vue'
import ConfigForm from '@/components/common/ConfigForm.vue'
import CustomSelect from '@/components/common/CustomSelect.vue'
import PluginCard from '@/components/common/PluginCard.vue'
import {
  IconPuzzle, IconInfoCircle, IconServer, IconUpload, IconRefresh,
  IconLightbulb, IconCog, IconSpinner, IconInfo, IconPackage, IconBox, IconClose, IconSearch, IconDownload, IconTrash,
} from '@/components/icons'
import type { PluginComponent, PluginItem, McpServerItem, McpToolItem, PluginStoreSource, PluginStoreItem, PluginUpdateCheckItem, PluginTask, PluginUpdateQueueItem } from '@/types'
import { getSources, addSource as apiAddSource, deleteSource as apiDeleteSource, setCurrentSource as apiSetCurrentSource, fetchPluginsFromSource } from '@/api/pluginStore'

const { t } = useI18n()
const { localize } = useLocalized()
const { isDark } = useTheme()
const activeTab = ref('plugins')

// Plugins
const plugins = ref<PluginItem[]>([])
const installDialogVisible = ref(false)
const installTab = ref('github')
const installForm = ref({ repo_url: '' })
const uploadFile = ref<File | null>(null)
const installDropzoneRef = ref<InstanceType<typeof FileDropzone> | null>(null)
const installing = ref(false)
const reloadingPlugins = ref(new Set<string>())
const refreshingPlugins = ref(false)
const pluginUpdates = ref<Map<string, PluginUpdateCheckItem>>(new Map())
const checkingUpdates = ref(false)
const pluginTasks = ref<PluginTask[]>([])
const submittingUpdateIds = ref(new Set<string>())
const updatingPlugins = computed(() => new Set([
  ...submittingUpdateIds.value,
  ...pluginTasks.value.filter(task => task.operation === 'update' && task.plugin_id && ['queued', 'running'].includes(task.status)).map(task => task.plugin_id!),
]))
const queuedPlugins = computed(() => new Set(pluginTasks.value.filter(task => task.status === 'queued' && task.plugin_id).map(task => task.plugin_id!)))
const pluginOperationsBusy = computed(() =>
  installing.value || pluginTasks.value.some(task => ['queued', 'running'].includes(task.status)),
)
const availableUpdateItems = computed<PluginUpdateQueueItem[]>(() =>
  plugins.value.filter(plugin => !plugin.builtin && plugin.repo && pluginUpdates.value.has(plugin.id) && !updatingPlugins.value.has(plugin.id))
    .map(plugin => ({ plugin_id: plugin.id, commit_sha: pluginUpdates.value.get(plugin.id)?.commit_sha ?? null })),
)
const latestPluginTasks = computed(() => {
  const latest = new Map<string, PluginTask>()
  for (const task of pluginTasks.value) {
    const target = task.operation === 'update' ? task.plugin_id : task.repo_url || task.task_id
    latest.set(`${task.operation}:${target}`, task)
  }
  return [...latest.values()]
})
const retryablePluginTasks = computed(() => latestPluginTasks.value.filter(task =>
  task.status === 'failed' && task.source !== 'upload' && !hasPendingTask(task),
))
const taskQueueSummary = computed(() => ({
  queued: pluginTasks.value.filter(task => task.status === 'queued').length,
  running: pluginTasks.value.filter(task => task.status === 'running').length,
  completed: pluginTasks.value.filter(task => task.status === 'completed').length,
  failed: pluginTasks.value.filter(task => task.status === 'failed').length,
  cancelled: pluginTasks.value.filter(task => task.status === 'cancelled').length,
}))
const enqueueingUpdates = ref(false)
const refreshingPluginTasks = ref(false)
const taskQueueLoadError = ref(false)
const taskQueueDismissed = ref(false)
const clearingPluginTasks = ref(false)
const updateDialogVisible = ref(false)
const updateTargetItems = ref<PluginUpdateQueueItem[]>([])
const selectedUpdatePluginIds = ref<string[]>([])
const selectedUpdateItems = computed(() =>
  updateTargetItems.value.filter(item => selectedUpdatePluginIds.value.includes(item.plugin_id)),
)
let taskPollTimer: ReturnType<typeof setTimeout> | null = null
let taskPollFailures = 0
let taskQueueRevision = 0
let taskQueueMounted = true
const pluginDetailsTabs = ['readme', 'components'] as const
const pluginDetailsTab = ref<typeof pluginDetailsTabs[number]>('readme')
const pluginComponents = ref<PluginComponent[]>([])
const pluginComponentsLoading = ref(false)
const pluginComponentsError = ref(false)
const selectedPluginInstalled = computed(() => plugins.value.some(item => item.id === selectedPlugin.value?.id))
const pluginDetailsVisible = ref(false)
const selectedPlugin = ref<PluginItem | PluginStoreItem | null>(null)
const pluginReadme = ref<string | null>(null)
const pluginReadmeLoading = ref(false)
let pluginDetailsRequest = 0
const pluginDetailsRepo = computed(() => {
  const repo = selectedPlugin.value?.repo
  if (!repo) return null
  try {
    const url = new URL(repo)
    return ['http:', 'https:'].includes(url.protocol) ? url.toString() : null
  } catch {
    return null
  }
})

// Proxy strategy
const GH_PROXY_LIST = [
  'https://gh-proxy.com/',
  'https://gh-proxy.org/',
  'https://hk.gh-proxy.org/',
  'https://cdn.gh-proxy.org/',
  'https://edgeone.gh-proxy.org/',
]
const proxyStrategy = ref<'auto' | 'none' | 'specific'>('auto')
const selectedProxyUrl = ref(GH_PROXY_LIST[0])

const proxyStrategyOptions = computed(() => [
  { value: 'auto', label: t('plugin.proxy_strategy_auto') },
  { value: 'none', label: t('plugin.proxy_strategy_none') },
  { value: 'specific', label: t('plugin.proxy_strategy_specific') },
])

const proxySelectOptions = computed(() =>
  GH_PROXY_LIST.map(url => ({ value: url, label: url }))
)

// Plugin Config
const pluginConfigVisible = ref(false)
const pluginConfigSchema = ref<any>(null)
const pluginConfigValues = ref<Record<string, any>>({})
const configPluginId = ref('')
const configPluginName = ref('')
const configFormRef = ref<InstanceType<typeof ConfigForm> | null>(null)
const configLoading = ref(false)
const savingConfig = ref(false)
const hasPluginConfigFields = computed(() =>
  !!pluginConfigSchema.value && Object.keys(pluginConfigSchema.value).length > 0
)

// MCP
const mcpServers = ref<McpServerItem[]>([])
const mcpDialogVisible = ref(false)
const mcpEditMode = ref(false)
const mcpEditId = ref<string | null>(null)
const mcpForm = ref({ name: '', description: '' })
const mcpConfigJson = ref('{}')
type McpTemplate = 'stdio' | 'sse' | 'streamable_http'
const mcpTemplates: Record<McpTemplate, Record<string, unknown>> = {
  stdio: { type: 'stdio', command: '', args: [], env: {} },
  sse: { type: 'sse', url: '', headers: {} },
  streamable_http: { type: 'streamable_http', url: '', headers: {} },
}
const mcpTemplate = ref<McpTemplate>('stdio')
const mcpToolsDialogVisible = ref(false)
const selectedMcpServer = ref<McpServerItem | null>(null)
const mcpTools = ref<McpToolItem[]>([])
const mcpToolsLoading = ref(false)
const mcpToolsError = ref<string | null>(null)
const mcpTemplateOptions = computed(() => [
  { value: 'stdio', label: t('plugin.mcp_template_stdio') },
  { value: 'sse', label: t('plugin.mcp_template_sse') },
  { value: 'streamable_http', label: t('plugin.mcp_template_streamable_http') },
])
const savingMcp = ref(false)

// Skills
const skills = ref<any[]>([])
const skillsError = ref<string | null>(null)
const skillsUploadVisible = ref(false)
const skillUploadFile = ref<File | null>(null)
const uploadingSkill = ref(false)
const skillsDropzoneRef = ref<InstanceType<typeof FileDropzone> | null>(null)

// Scope state
const scopeLoading = ref(false)
const scopeError = ref<string | null>(null)
const scopeSessions = ref<{ id: string; adapter: string; type: string; session_id: string; title: string }[]>([])
const scopeMcpServers = ref<{ id: string; name: string; enabled: boolean }[]>([])
const scopeSkills = ref<{ name: string; enabled: boolean }[]>([])
const mcpScopes = ref<Record<string, any>>({})
const skillScopes = ref<Record<string, any>>({})
// Per-resource edit state: { resourceId: { mode: 'global'|'allow'|'deny', sessions: Set<string> } }
const scopeEditMcp = ref<Record<string, { mode: string; sessions: Set<string> }>>({})
const scopeEditSkill = ref<Record<string, { mode: string; sessions: Set<string> }>>({})
const savingScope = ref(false)

// Confirm modal state
const confirmModalRef = ref<InstanceType<typeof ConfirmModal> | null>(null)
const confirmTitle = ref('')
const confirmMessage = ref('')
const confirmButtonText = ref('')
let pendingConfirmAction: (() => void) | null = null
const isUninstallConfirm = ref(false)
const uninstallDeleteConfig = ref(false)
const uninstallDeleteData = ref(false)

function openConfirm(title: string, message: string, buttonText: string, action: () => void) {
  confirmTitle.value = title
  confirmMessage.value = message
  confirmButtonText.value = buttonText
  pendingConfirmAction = action
  confirmModalRef.value?.open()
}

async function openPluginDetails(plugin: PluginItem | PluginStoreItem) {
  const request = ++pluginDetailsRequest
  pluginDetailsTab.value = 'readme'
  pluginComponents.value = []
  pluginComponentsError.value = false
  pluginComponentsLoading.value = false
  selectedPlugin.value = plugin
  pluginDetailsVisible.value = true
  pluginReadme.value = null
  const installedPlugin = plugins.value.find(item => item.id === plugin.id)
  if (!installedPlugin) {
    pluginReadmeLoading.value = false
    return
  }

  const componentsRequest = loadPluginComponents(installedPlugin.id, request)
  pluginReadmeLoading.value = true
  try {
    const res = await getPluginReadme(installedPlugin.id)
    if (request === pluginDetailsRequest) pluginReadme.value = res.data.readme
  } catch {
    // README is optional and must not prevent opening plugin details.
  } finally {
    if (request === pluginDetailsRequest) pluginReadmeLoading.value = false
  }
  await componentsRequest
}

async function loadPluginComponents(pluginId: string, request: number) {
  pluginComponentsLoading.value = true
  pluginComponentsError.value = false
  try {
    const res = await getPluginComponents(pluginId)
    if (request === pluginDetailsRequest) pluginComponents.value = res.data
  } catch {
    if (request === pluginDetailsRequest) pluginComponentsError.value = true
  } finally {
    if (request === pluginDetailsRequest) pluginComponentsLoading.value = false
  }
}

function onPluginDetailsTabKeydown(event: KeyboardEvent) {
  const index = pluginDetailsTabs.indexOf(pluginDetailsTab.value)
  let nextIndex: number
  switch (event.key) {
    case 'ArrowLeft': nextIndex = (index + pluginDetailsTabs.length - 1) % pluginDetailsTabs.length; break
    case 'ArrowRight': nextIndex = (index + 1) % pluginDetailsTabs.length; break
    case 'Home': nextIndex = 0; break
    case 'End': nextIndex = pluginDetailsTabs.length - 1; break
    default: return
  }
  event.preventDefault()
  pluginDetailsTab.value = pluginDetailsTabs[nextIndex]!
  document.getElementById(`plugin-details-tab-${pluginDetailsTab.value}`)?.focus()
}

function onConfirmAction() {
  pendingConfirmAction?.()
  pendingConfirmAction = null
  isUninstallConfirm.value = false
  uninstallDeleteConfig.value = false
  uninstallDeleteData.value = false
}

function onCancelAction() {
  pendingConfirmAction = null
  isUninstallConfirm.value = false
  uninstallDeleteConfig.value = false
  uninstallDeleteData.value = false
}

// Error flags so the UI can distinguish "no data" from "fetch failed"
const pluginsError = ref<string | null>(null)
const mcpServersError = ref<string | null>(null)

async function loadPlugins(): Promise<boolean> {
  try {
    const res = await getPlugins()
    plugins.value = Array.isArray(res.data) ? res.data : []
    const installedIds = new Set(plugins.value.map(plugin => plugin.id))
    for (const item of storePlugins.value) {
      item.installed = installedIds.has(item.id)
    }
    pluginsError.value = null
    return true
  } catch (e: any) {
    plugins.value = []
    pluginsError.value = e?.message || t('plugin.load_failed')
    notify(pluginsError.value!, 'error')
    return false
  }
}

async function refreshPlugins() {
  refreshingPlugins.value = true
  try {
    if (await loadPlugins()) {
      notify(t('plugin.refresh_success'), 'success')
    }
  } finally {
    refreshingPlugins.value = false
  }
}

async function handleCheckUpdates(silent = false) {
  checkingUpdates.value = true
  try {
    const res = await checkPluginUpdates()
    const installedIds = new Set(plugins.value.map(plugin => plugin.id))
    const map = new Map<string, PluginUpdateCheckItem>()
    for (const item of res.data) {
      if (item.has_update && installedIds.has(item.plugin_id)) {
        map.set(item.plugin_id, item)
      }
    }
    pluginUpdates.value = map
    if (!silent) {
      if (map.size > 0) {
        notify(t('plugin.updates_found', { count: map.size }), 'success')
      } else {
        notify(t('plugin.no_updates'), 'success')
      }
    }
  } catch {
    if (!silent) {
      notify(t('plugin.update_check_failed'), 'error')
    }
  } finally {
    checkingUpdates.value = false
  }
}

function updateItemName(item: PluginUpdateQueueItem): string {
  const plugin = plugins.value.find(plugin => plugin.id === item.plugin_id)
  return plugin ? localize(plugin, 'display_name', plugin.name || plugin.id) : item.plugin_id
}

function pluginTaskName(task: PluginTask): string {
  const plugin = plugins.value.find(plugin => plugin.id === task.plugin_id)
  if (plugin) return localize(plugin, 'display_name', plugin.name || plugin.id)
  const storeItem = storeTaskItem(task)
  return storeItem ? storePluginName(storeItem) : task.name
}

function openUpdateDialog(items: PluginUpdateQueueItem[]) {
  updateTargetItems.value = items
  selectedUpdatePluginIds.value = items.map(item => item.plugin_id)
  updateDialogVisible.value = items.length > 0
}

async function handleUpdatePlugin(plugin: PluginItem, commitSha?: string | null) {
  if (updatingPlugins.value.has(plugin.id)) return
  openUpdateDialog([{
    plugin_id: plugin.id,
    commit_sha: commitSha === undefined ? pluginUpdates.value.get(plugin.id)?.commit_sha ?? null : commitSha,
  }])
}

function openBatchUpdate() {
  openUpdateDialog([...availableUpdateItems.value])
}

function hasPendingTask(task: PluginTask): boolean {
  return pluginTasks.value.some(item => ['queued', 'running'].includes(item.status) && item.operation === task.operation
    && (task.operation === 'update' ? item.plugin_id === task.plugin_id : item.repo_url === task.repo_url))
}

async function retryPluginTasks(tasks: PluginTask[]) {
  if (enqueueingUpdates.value) return
  enqueueingUpdates.value = true
  try {
    for (const task of tasks) {
      const response = await retryPluginTask(task.task_id)
      acceptPluginTasks([response.data])
    }
  } catch {
    notify(t('plugin.task_enqueue_failed'), 'error')
  } finally {
    enqueueingUpdates.value = false
    scheduleTaskPoll(0)
  }
}

function retryFailedTasks() {
  void retryPluginTasks(retryablePluginTasks.value)
}

function acceptPluginTasks(tasks: PluginTask[]) {
  taskQueueDismissed.value = false
  taskQueueRevision += 1
  const merged = new Map(pluginTasks.value.map(task => [task.task_id, task]))
  for (const task of tasks) merged.set(task.task_id, task)
  pluginTasks.value = [...merged.values()]
  scheduleTaskPoll(0)
}

function resolveGhProxy(): string | undefined {
  if (proxyStrategy.value === 'specific') return selectedProxyUrl.value
  if (proxyStrategy.value === 'auto') return 'auto'
  return undefined
}

async function confirmUpdate() {
  if (enqueueingUpdates.value || !selectedUpdateItems.value.length) return
  const items = selectedUpdateItems.value.map(item => ({ ...item, gh_proxy: resolveGhProxy() }))
  enqueueingUpdates.value = true
  submittingUpdateIds.value = new Set(items.map(item => item.plugin_id))
  try {
    const response = await enqueueTaskUpdates(items)
    acceptPluginTasks(response.data)
    updateDialogVisible.value = false
    notify(t('plugin.update_queued', { count: response.data.length }), 'success')
  } catch {
    notify(t('plugin.update_enqueue_failed'), 'error')
  } finally {
    submittingUpdateIds.value.clear()
    enqueueingUpdates.value = false
    scheduleTaskPoll(0)
  }
}

function taskStageLabel(stage: PluginTask['stage']): string {
  if (['queued', 'completed', 'failed', 'cancelled'].includes(stage)) {
    return t('plugin.task_stage_' + stage)
  }
  if (stage === 'extracting') return t('plugin.task_stage_extracting')
  return t('pluginStore.install_stage_' + (stage === 'installing_dependencies' ? 'dependencies' : stage))
}

function scheduleTaskPoll(delay = 1500) {
  if (!taskQueueMounted) return
  if (taskPollTimer) clearTimeout(taskPollTimer)
  taskPollTimer = setTimeout(() => {
    taskPollTimer = null
    void refreshPluginTasks()
  }, delay)
}

async function dismissTaskQueue() {
  if (clearingPluginTasks.value) return
  clearingPluginTasks.value = true
  const revision = ++taskQueueRevision
  try {
    const response = await clearFinishedPluginTasks()
    if (!taskQueueMounted) return
    if (revision !== taskQueueRevision) return
    pluginTasks.value = response.data
    taskQueueLoadError.value = false
    taskQueueDismissed.value = !response.data.some(task => ['queued', 'running'].includes(task.status))
  } catch {
    if (taskQueueMounted) notify(t('plugin.task_queue_clear_failed'), 'error')
  } finally {
    clearingPluginTasks.value = false
    scheduleTaskPoll(0)
  }
}

async function refreshPluginTasks() {
  if (!taskQueueMounted) return
  if (refreshingPluginTasks.value || clearingPluginTasks.value) {
    scheduleTaskPoll()
    return
  }
  refreshingPluginTasks.value = true
  try {
    const revision = taskQueueRevision
    const response = await getPluginTasks()
    if (!taskQueueMounted) return
    if (revision !== taskQueueRevision) {
      scheduleTaskPoll(0)
      return
    }
    const previous = new Map(pluginTasks.value.map(task => [task.task_id, task.status]))
    const activeTasks = pluginTasks.value.filter(task => ['queued', 'running'].includes(task.status))
    const wasActive = activeTasks.length > 0
    const lostTasks = activeTasks.some(task => !response.data.some(item => item.task_id === task.task_id))
    pluginTasks.value = response.data
    taskQueueLoadError.value = false
    taskPollFailures = 0
    if (response.data.some(task => ['completed', 'failed'].includes(task.status) && previous.has(task.task_id) && previous.get(task.task_id) !== task.status)) {
      await loadPlugins()
      for (const task of response.data.filter(task => task.status === 'completed')) {
        if (task.operation === 'update' && task.plugin_id && pluginUpdates.value.get(task.plugin_id)?.commit_sha === task.commit_sha) {
          pluginUpdates.value.delete(task.plugin_id)
        }
      }
    }
    if (response.data.some(task => ['queued', 'running'].includes(task.status))) {
      scheduleTaskPoll()
    } else if (wasActive) {
      void handleCheckUpdates(true)
      if (activeTab.value === 'pluginStore') void fetchStorePlugins()
      notify(t(lostTasks ? 'plugin.task_queue_reset' : 'plugin.task_queue_finished'), lostTasks ? 'error' : 'success')
    }
  } catch {
    taskQueueLoadError.value = true
    taskPollFailures += 1
    scheduleTaskPoll(Math.min(30000, 1500 * 2 ** Math.min(taskPollFailures, 5)))
  } finally {
    refreshingPluginTasks.value = false
  }
}

async function cancelQueuedTask(task: PluginTask) {
  try {
    const response = await cancelPluginTask(task.task_id)
    taskQueueRevision += 1
    pluginTasks.value = pluginTasks.value.map(item => item.task_id === task.task_id ? response.data : item)
  } catch {
    notify(t('plugin.task_cancel_failed'), 'error')
  } finally {
    scheduleTaskPoll(0)
  }
}

// Auto-poll while any enabled plugin is in a transient state
const hasTransientPlugins = computed(() =>
  plugins.value.some(p => p.enabled && ['installing', 'loading'].includes(p.status || ''))
)
let pluginPollTimer: ReturnType<typeof setInterval> | null = null

watch(hasTransientPlugins, (hasTransient) => {
  if (hasTransient && !pluginPollTimer) {
    pluginPollTimer = setInterval(async () => {
      try {
        const res = await getPlugins()
        plugins.value = Array.isArray(res.data) ? res.data : plugins.value
      } catch { /* keep stale data during poll */ }
    }, 5000)
  } else if (!hasTransient && pluginPollTimer) {
    clearInterval(pluginPollTimer)
    pluginPollTimer = null
  }
})

onUnmounted(() => {
  taskQueueMounted = false
  if (taskPollTimer) clearTimeout(taskPollTimer)
  if (pluginPollTimer) {
    clearInterval(pluginPollTimer)
    pluginPollTimer = null
  }
})

async function loadMcpServers() {
  try {
    const res = await getMcpServers()
    mcpServers.value = Array.isArray(res.data) ? res.data : []
    mcpServersError.value = null
  } catch (e: any) {
    mcpServers.value = []
    mcpServersError.value = e?.message || t('plugin.mcp_load_failed')
    notify(mcpServersError.value!, 'error')
  }
}

async function togglePlugin(plugin: PluginItem) {
  try {
    await apiTogglePlugin(plugin.id, !plugin.enabled)
    notify(t('plugin.toggle_success'), 'success')
  } catch {
    notify(t('plugin.toggle_failed'), 'error')
  } finally {
    // Always resync so the switch reflects the backend's view, even if the
    // call failed half-way and we can't be sure which side of the toggle
    // actually took effect.
    await loadPlugins()
  }
}

function handleDeletePlugin(id: string) {
  isUninstallConfirm.value = true
  uninstallDeleteConfig.value = false
  uninstallDeleteData.value = false
  openConfirm(
    t('plugin.uninstall'),
    t('plugin.uninstall_confirm'),
    t('plugin.uninstall'),
    async () => {
      try {
        await deletePlugin(id, {
          deleteConfig: uninstallDeleteConfig.value,
          deleteData: uninstallDeleteData.value,
        })
        plugins.value = plugins.value.filter(plugin => plugin.id !== id)
        pluginUpdates.value.delete(id)
        for (const item of storePlugins.value) {
          if (item.id === id) item.installed = false
        }
        notify(t('plugin.uninstall_success'), 'success')
        await loadPlugins()
      } catch {
        notify(t('plugin.uninstall_failed'), 'error')
      }
    }
  )
}

async function handleReloadPlugin(plugin: PluginItem) {
  reloadingPlugins.value.add(plugin.id)
  try {
    const res = await apiReloadPlugin(plugin.id)
    if (res.data.reloaded) {
      notify(t('plugin.reload_success'), 'success')
    } else {
      notify(t('plugin.reload_failed') + ': ' + (res.data.error || ''), 'error')
    }
    await loadPlugins()
  } catch {
    notify(t('plugin.reload_failed'), 'error')
  } finally {
    reloadingPlugins.value.delete(plugin.id)
  }
}

async function openPluginConfig(plugin: PluginItem) {
  configPluginId.value = plugin.id
  configPluginName.value = localize(plugin, 'display_name', plugin.name || plugin.id)
  pluginConfigSchema.value = null
  pluginConfigValues.value = {}
  configLoading.value = true
  pluginConfigVisible.value = true
  try {
    const res = await getPluginConfig(plugin.id)
    pluginConfigSchema.value = res.data.schema || null
    pluginConfigValues.value = res.data.config || {}
  } catch {
    notify(t('plugin.config_load_failed'), 'error')
    pluginConfigVisible.value = false
    pluginConfigSchema.value = null
    pluginConfigValues.value = {}
  } finally {
    configLoading.value = false
  }
}

async function savePluginConfig() {
  // Guard: the "no_config" placeholder leaves pluginConfigValues empty.
  // Posting {} back would wipe any legitimately-managed config for a plugin
  // that has no schema, so refuse to save instead of overwriting.
  if (!hasPluginConfigFields.value) return
  const validateRes = configFormRef.value?.validate()
  if (validateRes && !validateRes.valid) {
    notify(validateRes.message!, 'error')
    return
  }
  savingConfig.value = true
  try {
    await updatePluginConfig(configPluginId.value, { config: pluginConfigValues.value })
    notify(t('plugin.config_saved'), 'success')
    pluginConfigVisible.value = false
  } catch {
    notify(t('plugin.config_save_failed'), 'error')
  } finally {
    savingConfig.value = false
  }
}

// Upload file is now bound directly via v-model on FileDropzone

// Modal preserves its child state across closes; reset the form before
// opening so the user never sees stale data.
function resetInstallForm() {
  installForm.value = { repo_url: '' }
  uploadFile.value = null
  installDropzoneRef.value?.reset()
  installTab.value = 'github'
  proxyStrategy.value = 'auto'
  selectedProxyUrl.value = GH_PROXY_LIST[0]
}

function openInstallDialog() {
  resetInstallForm()
  installDialogVisible.value = true
}

function openSkillsUploadDialog() {
  skillUploadFile.value = null
  skillsDropzoneRef.value?.reset()
  skillsUploadVisible.value = true
}

async function handleInstall() {
  installing.value = true
  try {
    if (installTab.value === 'github') {
      const repoUrl = installForm.value.repo_url?.trim()
      if (!repoUrl) {
        notify(t('plugin.repo_url_required'), 'error')
        installing.value = false
        return
      }
      const ghProxy = proxyStrategy.value === 'specific'
        ? selectedProxyUrl.value
        : proxyStrategy.value === 'auto'
          ? 'auto'
          : null
      const response = await enqueueGithubInstall({ repo_url: repoUrl, gh_proxy: ghProxy })
      acceptPluginTasks([response.data])
    } else {
      if (!uploadFile.value) {
        notify(t('plugin.file_required'), 'error')
        installing.value = false
        return
      }
      const response = await enqueueUploadInstall(uploadFile.value)
      acceptPluginTasks([response.data])
      uploadFile.value = null
    }
    installDialogVisible.value = false
    notify(t('plugin.task_queued'), 'success')
  } catch (e: any) {
    if (e?.response?.status === 409) {
      notify(e?.response?.data?.detail || t('plugin.install_failed'), 'error')
    } else {
      notify(t('plugin.install_failed'), 'error')
    }
  } finally {
    installing.value = false
  }
}

async function toggleMcp(server: McpServerItem) {
  try {
    await toggleMcpServer(server.id, !server.enabled)
    notify(t('plugin.mcp_toggle_success'), 'success')
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    notify(detail ? `${t('plugin.mcp_toggle_failed')}: ${detail}` : t('plugin.mcp_toggle_failed'), 'error')
  } finally {
    await loadMcpServers()
  }
}

async function openMcpTools(server: McpServerItem) {
  selectedMcpServer.value = server
  mcpTools.value = []
  mcpToolsError.value = null
  mcpToolsDialogVisible.value = true
  mcpToolsLoading.value = true

  try {
    const res = await getMcpServerTools(server.id)
    if (selectedMcpServer.value?.id === server.id) {
      mcpTools.value = Array.isArray(res.data) ? res.data : []
    }
  } catch (e: any) {
    if (selectedMcpServer.value?.id === server.id) {
      const detail = e?.response?.data?.detail
      mcpToolsError.value = detail ? `${t('plugin.mcp_tools_load_failed')}: ${detail}` : t('plugin.mcp_tools_load_failed')
    }
  } finally {
    if (selectedMcpServer.value?.id === server.id) {
      mcpToolsLoading.value = false
    }
  }
}

const mcpToolPending = ref<Set<string>>(new Set())

async function toggleMcpToolItem(tool: McpToolItem) {
  if (!selectedMcpServer.value || mcpToolPending.value.has(tool.name)) return
  const serverId = selectedMcpServer.value.id
  const previous = tool.enabled
  tool.enabled = !previous
  mcpToolPending.value.add(tool.name)
  try {
    await toggleMcpTool(serverId, tool.name, !previous)
  } catch (e: any) {
    tool.enabled = previous
    const detail = e?.response?.data?.detail
    notify(detail ? `${t('plugin.mcp_tool_toggle_failed')}: ${detail}` : t('plugin.mcp_tool_toggle_failed'), 'error')
  } finally {
    mcpToolPending.value.delete(tool.name)
  }
}

function openMcpCreate() {
  mcpEditMode.value = false
  mcpEditId.value = null
  mcpForm.value = { name: '', description: '' }
  mcpTemplate.value = 'stdio'
  applyMcpTemplate()
  mcpDialogVisible.value = true
}

function getMcpTemplate(config: Record<string, unknown>): McpTemplate {
  if (config.type === 'sse' || config.type === 'streamable_http' || config.type === 'stdio') {
    return config.type
  }
  if (typeof config.url === 'string') {
    return config.url.endsWith('/sse') ? 'sse' : 'streamable_http'
  }
  return 'stdio'
}

function applyMcpTemplate() {
  mcpConfigJson.value = JSON.stringify(mcpTemplates[mcpTemplate.value], null, 2)
}

function onMcpTemplateChange(template: string) {
  if (template !== 'stdio' && template !== 'sse' && template !== 'streamable_http') return
  mcpTemplate.value = template
  applyMcpTemplate()
}

async function openMcpEdit(server: McpServerItem) {
  try {
    const res = await getMcpServerConfig(server.id)
    const config = res.data?.config ?? {}
    mcpEditMode.value = true
    mcpEditId.value = server.id
    mcpForm.value = { name: res.data?.name || server.name, description: res.data?.description || server.description || '' }
    mcpTemplate.value = getMcpTemplate(config)
    mcpConfigJson.value = JSON.stringify(config, null, 2)
    mcpDialogVisible.value = true
  } catch (e: any) {
    // Abort opening the editor — a lossy fallback built from list fields
    // would silently overwrite the real config if the user hits Save. Use
    // the load-specific key so the toast isn't misleading (the user never
    // tried to save anything).
    const detail = e?.response?.data?.detail
    notify(detail ? `${t('plugin.mcp_config_load_failed')}: ${detail}` : t('plugin.mcp_config_load_failed'), 'error')
  }
}

let mcpSaving = false

async function saveMcpForm() {
  if (mcpSaving) return
  if (!mcpForm.value.name?.trim()) {
    notify(t('plugin.mcp_name_required'), 'error')
    return
  }
  mcpSaving = true
  savingMcp.value = true
  let config: any
  try {
    config = JSON.parse(mcpConfigJson.value)
  } catch {
    notify(t('plugin.mcp_invalid_json'), 'error')
    savingMcp.value = false
    mcpSaving = false
    return
  }
  // Backend expects a JSON object; reject arrays, null, and primitives up
  // front so the user sees the same error as the catch branch instead of a
  // 400 from the server.
  if (config === null || typeof config !== 'object' || Array.isArray(config)) {
    notify(t('plugin.mcp_invalid_json'), 'error')
    savingMcp.value = false
    mcpSaving = false
    return
  }
  try {
    if (mcpEditMode.value && mcpEditId.value) {
      await updateMcpServerConfig(mcpEditId.value, { name: mcpForm.value.name, description: mcpForm.value.description, config })
    } else {
      await createMcpServer({ name: mcpForm.value.name, description: mcpForm.value.description, config })
    }
    mcpDialogVisible.value = false
    notify(t('plugin.mcp_save_success'), 'success')
    await loadMcpServers()
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    notify(detail ? `${t('plugin.mcp_save_failed')}: ${detail}` : t('plugin.mcp_save_failed'), 'error')
  } finally {
    savingMcp.value = false
    mcpSaving = false
  }
}

function handleDeleteMcp(id: string) {
  openConfirm(
    t('plugin.mcp_delete'),
    t('plugin.mcp_delete_confirm'),
    t('plugin.mcp_delete'),
    async () => {
      try {
        await deleteMcpServer(id)
        notify(t('plugin.mcp_delete_success'), 'success')
        await loadMcpServers()
      } catch (e: any) {
        const detail = e?.response?.data?.detail
        notify(detail ? `${t('plugin.mcp_delete_failed')}: ${detail}` : t('plugin.mcp_delete_failed'), 'error')
      }
    }
  )
}

async function loadSkills() {
  try {
    const res = await getSkills()
    skills.value = Array.isArray(res.data) ? res.data : []
    skillsError.value = null
  } catch (e: any) {
    skills.value = []
    skillsError.value = e?.message || t('plugin.skills_load_failed')
    notify(skillsError.value!, 'error')
  }
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 2)} ${units[index]}`
}

async function handleExportSkill(skill: any) {
  try {
    const response = await apiExportSkill(skill.id)
    const blobUrl = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = `${skill.id}.zip`
    link.click()
    URL.revokeObjectURL(blobUrl)
    notify(t('plugin.skills_export_success'), 'success')
  } catch {
    notify(t('plugin.skills_export_error'), 'error')
  }
}

function handleDeleteSkill(skill: any) {
  openConfirm(
    t('plugin.skills_delete'),
    t('plugin.skills_delete_confirm', { name: skill.name || skill.id }),
    t('plugin.skills_delete'),
    async () => {
      try {
        await apiDeleteSkill(skill.id)
        notify(t('plugin.skills_delete_success'), 'success')
        await loadSkills()
        await loadScope()
      } catch (e: any) {
        const detail = e?.response?.data?.detail
        notify(detail ? `${t('plugin.skills_delete_error')}: ${detail}` : t('plugin.skills_delete_error'), 'error')
      }
    },
  )
}

async function toggleSkillItem(skill: any) {
  try {
    await apiToggleSkill(skill.id, !skill.enabled)
    notify(t('plugin.skills_toggle_success'), 'success')
  } catch {
    notify(t('plugin.skills_toggle_error'), 'error')
  } finally {
    await loadSkills()
  }
}

async function refreshSkillList() {
  try {
    await apiRefreshSkills()
    notify(t('plugin.skills_refresh_success'), 'success')
    await loadSkills()
  } catch {
    notify(t('plugin.skills_refresh_error'), 'error')
  }
}

// Skill upload file is now bound directly via v-model on FileDropzone

async function handleSkillUpload() {
  if (!skillUploadFile.value) {
    notify(t('plugin.skills_upload_no_file'), 'error')
    return
  }
  uploadingSkill.value = true
  try {
    await apiUploadSkill(skillUploadFile.value)
    skillsUploadVisible.value = false
    notify(t('plugin.skills_upload_success'), 'success')
    await loadSkills()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || ''
    notify(`${t('plugin.skills_upload_error')}${msg ? ': ' + msg : ''}`, 'error')
  } finally {
    uploadingSkill.value = false
    skillUploadFile.value = null
    skillsDropzoneRef.value?.reset()
  }
}

// Scope
async function loadScope() {
  scopeLoading.value = true
  scopeError.value = null
  try {
    const res = await getScope()
    const data = res.data
    scopeSessions.value = Array.isArray(data.sessions) ? data.sessions : []
    scopeMcpServers.value = Array.isArray(data.mcp_servers) ? data.mcp_servers : []
    scopeSkills.value = Array.isArray(data.skills) ? data.skills : []
    mcpScopes.value = data.mcp_scopes || {}
    skillScopes.value = data.skill_scopes || {}
    initScopeEditState()
  } catch (e: any) {
    scopeError.value = t('plugin.scope_load_failed')
  } finally {
    scopeLoading.value = false
  }
}

function initScopeEditState() {
  const mcpState: Record<string, { mode: string; sessions: Set<string> }> = {}
  for (const mcp of scopeMcpServers.value) {
    const entry = mcpScopes.value[mcp.id]
    if (!entry) {
      mcpState[mcp.id] = { mode: 'global', sessions: new Set() }
    } else if ('allow' in entry) {
      mcpState[mcp.id] = { mode: 'allow', sessions: new Set((entry as any).allow) }
    } else if ('deny' in entry) {
      mcpState[mcp.id] = { mode: 'deny', sessions: new Set((entry as any).deny) }
    } else {
      mcpState[mcp.id] = { mode: 'global', sessions: new Set() }
    }
  }
  scopeEditMcp.value = mcpState

  const skillState: Record<string, { mode: string; sessions: Set<string> }> = {}
  for (const skill of scopeSkills.value) {
    const entry = skillScopes.value[skill.name]
    if (!entry) {
      skillState[skill.name] = { mode: 'global', sessions: new Set() }
    } else if ('allow' in entry) {
      skillState[skill.name] = { mode: 'allow', sessions: new Set((entry as any).allow) }
    } else if ('deny' in entry) {
      skillState[skill.name] = { mode: 'deny', sessions: new Set((entry as any).deny) }
    } else {
      skillState[skill.name] = { mode: 'global', sessions: new Set() }
    }
  }
  scopeEditSkill.value = skillState
}

function onScopeModeChange(resourceId: string, type: 'mcp' | 'skill', newMode: string) {
  const state = type === 'mcp' ? scopeEditMcp : scopeEditSkill
  if (state.value[resourceId]) {
    state.value[resourceId].mode = newMode
    if (newMode === 'global') {
      state.value[resourceId].sessions = new Set()
    }
  }
}

function onScopeSessionToggle(resourceId: string, type: 'mcp' | 'skill', sessionId: string) {
  const state = type === 'mcp' ? scopeEditMcp : scopeEditSkill
  if (!state.value[resourceId]) return
  const sessions = state.value[resourceId].sessions
  if (sessions.has(sessionId)) {
    sessions.delete(sessionId)
  } else {
    sessions.add(sessionId)
  }
}

async function saveScope() {
  savingScope.value = true
  try {
    const newMcpScopes: Record<string, any> = {}
    for (const [serverId, state] of Object.entries(scopeEditMcp.value)) {
      if (state.mode !== 'global' && state.sessions.size > 0) {
        newMcpScopes[serverId] = { [state.mode]: Array.from(state.sessions) }
      }
    }

    const newSkillScopes: Record<string, any> = {}
    for (const [skillName, state] of Object.entries(scopeEditSkill.value)) {
      if (state.mode !== 'global' && state.sessions.size > 0) {
        newSkillScopes[skillName] = { [state.mode]: Array.from(state.sessions) }
      }
    }

    await updateScope({ mcp_scopes: newMcpScopes, skill_scopes: newSkillScopes })
    notify(t('plugin.scope_save_success'), 'success')
    await loadScope()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || ''
    notify(`${t('plugin.scope_save_failed')}${msg ? ': ' + msg : ''}`, 'error')
  } finally {
    savingScope.value = false
  }
}

const pluginsSearchTerm = ref('')

// Plugin Store
const pluginSources = ref<PluginStoreSource[]>([])
const currentStoreSource = ref<PluginStoreSource | null>(null)
const storePlugins = ref<PluginStoreItem[]>([])
const storeLoading = ref(false)
const storeError = ref<string | null>(null)
const storeInstallVisible = ref(false)
const storeInstallTarget = ref<PluginStoreItem | null>(null)
const storeInstallTaskId = ref<string | null>(null)
const storeInstallTask = computed(() => pluginTasks.value.find(task => task.task_id === storeInstallTaskId.value) || null)
const storeInstallPending = computed(() => !!storeInstallTask.value && ['queued', 'running'].includes(storeInstallTask.value.status))
const storeInstallStageLabel = computed(() => {
  const stage = storeInstallTask.value?.stage
  if (!stage) return ''
  if (stage === 'extracting') return taskStageLabel(stage)
  return t('pluginStore.install_stage_' + (stage === 'installing_dependencies' ? 'dependencies' : stage))
})

function storeTaskItem(task: PluginTask): PluginStoreItem | undefined {
  if (task.operation !== 'install' || !task.repo_url) return undefined
  const candidates = storeInstallTarget.value ? [storeInstallTarget.value, ...storePlugins.value] : storePlugins.value
  return candidates.find(item => item.repo?.trim().replace(/\/+$/, '') === task.repo_url)
}

function viewStoreInstallTask(task: PluginTask) {
  const item = storeTaskItem(task)
  if (!item) return
  storeInstallTarget.value = item
  storeInstallTaskId.value = task.task_id
  storeInstallVisible.value = true
}

async function cancelStoreInstall() {
  const task = storeInstallTask.value
  if (task) await cancelQueuedTask(task)
}

function pendingStoreInstall(item: PluginStoreItem): boolean {
  const repo = item.repo?.trim().replace(/\/+$/, '')
  return pluginTasks.value.some(task => task.operation === 'install' && task.repo_url === repo
    && ['queued', 'running'].includes(task.status))
}

const storeInstallIcon = computed(() => {
  const item = storeInstallTarget.value
  return isDark.value ? item?.icon_dark || item?.icon : item?.icon || null
})
const storeInstallRepo = computed(() => {
  const repo = storeInstallTarget.value?.repo
  if (!repo) return null
  try {
    const url = new URL(repo)
    return ['http:', 'https:'].includes(url.protocol) ? url.toString() : null
  } catch {
    return null
  }
})
const sourceManageVisible = ref(false)
const newSourceName = ref('')
const newSourceUrl = ref('')
const storeSearchTerm = ref('')
const storeCategory = ref('all')
const storeSort = ref('stars')
const STORE_PAGE_SIZE = 12
const storePage = ref(1)

const storeCategoryOptions = computed(() => {
  const categories = new Map<string, PluginStoreItem>()
  for (const item of storePlugins.value) {
    const category = item.category?.trim()
    if (category && !categories.has(category)) categories.set(category, item)
  }
  return [
    { value: 'all', label: t('pluginStore.all_categories') },
    ...Array.from(categories.entries())
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([category, item]) => ({ value: category, label: storeCategoryName(item) })),
  ]
})

const storeSortOptions = computed(() => [
  { value: 'stars', label: t('pluginStore.sort_most_starred') },
  { value: 'updated', label: t('pluginStore.sort_recently_updated') },
  { value: 'name', label: t('pluginStore.sort_name') },
])

const filteredPlugins = computed(() => {
  const q = pluginsSearchTerm.value.trim().toLowerCase()
  const filtered = !q
    ? [...plugins.value]
    : plugins.value.filter(p => {
        const name = (localize(p, 'display_name', p.name) || '').toLowerCase()
        const desc = (localize(p, 'description', p.description) || '').toLowerCase()
        const author = (p.author || '').toLowerCase()
        const id = p.id.toLowerCase()
        const tags = (p.tags || []).join(' ').toLowerCase()
        return name.includes(q) || desc.includes(q) || author.includes(q) || id.includes(q) || tags.includes(q)
      })

  // Built-in plugins stay grouped ahead of user plugins; each group is ordered by name.
  return filtered.sort((a, b) => {
    const builtinDiff = Number(Boolean(b.builtin)) - Number(Boolean(a.builtin))
    if (builtinDiff !== 0) return builtinDiff
    return storePluginName(a).localeCompare(storePluginName(b)) || a.id.localeCompare(b.id)
  })
})

const filteredStorePlugins = computed(() => {
  const q = storeSearchTerm.value.trim().toLowerCase()
  const filtered = storePlugins.value.filter(item => {
    if (storeCategory.value !== 'all' && item.category?.trim() !== storeCategory.value) return false
    if (!q) return true
    const name = (localize(item, 'display_name', item.name) || '').toLowerCase()
    const desc = (localize(item, 'description', item.description) || '').toLowerCase()
    const author = (item.author || '').toLowerCase()
    const id = item.id.toLowerCase()
    const tags = (item.tags || []).join(' ').toLowerCase()
    return name.includes(q) || desc.includes(q) || author.includes(q) || id.includes(q) || tags.includes(q)
  })

  return [...filtered].sort((a, b) => {
    if (storeSort.value === 'name') {
      return storePluginName(a).localeCompare(storePluginName(b)) || a.id.localeCompare(b.id)
    }

    const valueA = storeSort.value === 'stars' ? Number(a.stars || 0) : storePluginUpdatedAt(a)
    const valueB = storeSort.value === 'stars' ? Number(b.stars || 0) : storePluginUpdatedAt(b)
    return valueB - valueA || storePluginName(a).localeCompare(storePluginName(b)) || a.id.localeCompare(b.id)
  })
})

const storeTotalPages = computed(() => Math.max(1, Math.ceil(filteredStorePlugins.value.length / STORE_PAGE_SIZE)))

const storePageNumbers = computed<(number | string)[]>(() => {
  const total = storeTotalPages.value
  const current = storePage.value
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1)
  if (current <= 4) return [1, 2, 3, 4, 5, 'end-ellipsis', total]
  if (current >= total - 3) {
    return [1, 'start-ellipsis', total - 4, total - 3, total - 2, total - 1, total]
  }
  return [1, 'start-ellipsis', current - 1, current, current + 1, 'end-ellipsis', total]
})

const paginatedStorePlugins = computed(() => {
  const start = (storePage.value - 1) * STORE_PAGE_SIZE
  return filteredStorePlugins.value.slice(start, start + STORE_PAGE_SIZE)
})

watch([storeSearchTerm, storeCategory, storeSort], () => {
  storePage.value = 1
})

watch(storeTotalPages, totalPages => {
  if (storePage.value > totalPages) storePage.value = totalPages
})

function storePluginName(item: PluginStoreItem): string {
  return localize(item, 'display_name', item.name || item.id)
}

function storeCategoryName(item: {
  category?: string | null
  category_name?: string | null
  category_locales?: Record<string, Record<string, string>>
}): string {
  const category = item.category?.trim() || ''
  return localize(
    { name: item.category_name || category, locales: item.category_locales },
    'name',
    category,
  )
}

function storePluginUpdatedAt(item: PluginStoreItem): number {
  const value = item.updated_at
  const normalizeTimestamp = (timestamp: number) => timestamp < 100_000_000_000 ? timestamp * 1000 : timestamp
  if (typeof value === 'number') return Number.isFinite(value) ? normalizeTimestamp(value) : 0
  if (!value) return 0
  const numericValue = Number(value)
  if (Number.isFinite(numericValue)) return normalizeTimestamp(numericValue)
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? 0 : timestamp
}

function isCurrentSource(src: PluginStoreSource): boolean {
  return currentStoreSource.value?.id === src.id
}

async function loadSourcesFromBackend() {
  try {
    const sources = await getSources()
    pluginSources.value = sources
    const current = sources.find(s => s.is_current) || null
    currentStoreSource.value = current
  } catch {
    pluginSources.value = []
    currentStoreSource.value = null
  }
}

async function openSourceManage() {
  await loadSourcesFromBackend()
  newSourceName.value = ''
  newSourceUrl.value = ''
  sourceManageVisible.value = true
}

async function addNewSource() {
  const name = newSourceName.value.trim()
  const url = newSourceUrl.value.trim()
  if (!name || !url) return
  try {
    const created = await apiAddSource(name, url)
    pluginSources.value.push(created)
    // If this is the first source, auto-select it
    if (!currentStoreSource.value) {
      await switchToSource(created)
    }
    newSourceName.value = ''
    newSourceUrl.value = ''
    notify(t('pluginStore.source_added'), 'success')
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || ''
    notify(`${t('pluginStore.source_add_error')}${msg ? ': ' + msg : ''}`, 'error')
  }
}

async function removeSource(idx: number) {
  const removed = pluginSources.value[idx]
  try {
    await apiDeleteSource(removed.id)
    pluginSources.value.splice(idx, 1)
    if (removed && isCurrentSource(removed)) {
      const next = pluginSources.value.length > 0 ? pluginSources.value[0] : null
      if (next) {
        await apiSetCurrentSource(next.id)
        currentStoreSource.value = next
        await fetchStorePlugins()
      } else {
        currentStoreSource.value = null
        storePlugins.value = []
      }
    }
    notify(t('pluginStore.source_removed'), 'success')
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || ''
    notify(`${t('pluginStore.source_remove_error')}${msg ? ': ' + msg : ''}`, 'error')
  }
}

async function switchToSource(src: PluginStoreSource) {
  try {
    await apiSetCurrentSource(src.id)
    currentStoreSource.value = src
    // Mark the is_current flag locally
    pluginSources.value.forEach(s => { s.is_current = s.id === src.id })
    sourceManageVisible.value = false
    notify(`${t('pluginStore.source_switched')}: ${src.name}`, 'success')
    await fetchStorePlugins()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || ''
    notify(`${t('pluginStore.source_switch_error')}${msg ? ': ' + msg : ''}`, 'error')
  }
}

async function fetchStorePlugins(forceRefresh: boolean = false) {
  if (!currentStoreSource.value) return
  storeLoading.value = true
  storeError.value = null
  try {
    const { items, usedCacheFallback, cacheFallbackStatus } = await fetchPluginsFromSource(currentStoreSource.value.id, forceRefresh)
    // Mark already-installed plugins
    const installedIds = new Set(plugins.value.map(p => p.id))
    storePlugins.value = items.map(item => ({
      ...item,
      installed: installedIds.has(item.id),
    }))

    storePage.value = 1
    if (storeCategory.value !== 'all' && !storePlugins.value.some(item => item.category?.trim() === storeCategory.value)) {
      storeCategory.value = 'all'
    }
    if (usedCacheFallback) {
      const errorMessage = cacheFallbackStatus === null
        ? ''
        : t('pluginStore.request_failed_status', { status: cacheFallbackStatus })
      notify(`${t('pluginStore.cache_fallback_warning')}${errorMessage ? ` ${errorMessage}` : ''}`, 'error')
    } else if (forceRefresh) {
      notify(t('pluginStore.refresh_success'), 'success')
    }
  } catch (e: any) {
    storePlugins.value = []
    storeError.value = e?.message || t('pluginStore.fetch_failed')
  } finally {
    storeLoading.value = false
  }
}

function handleStoreInstall(item: PluginStoreItem) {
  if (item.installed || pendingStoreInstall(item)) return
  storeInstallTarget.value = item
  storeInstallTaskId.value = null
  storeInstallVisible.value = true
}

async function startStoreInstall() {
  const item = storeInstallTarget.value
  if (!item?.repo || installing.value || storeInstallTaskId.value) return
  installing.value = true
  try {
    const response = await enqueueGithubInstall({
      repo_url: item.repo,
      display_name: storePluginName(item),
      gh_proxy: resolveGhProxy(),
      commit_sha: item.commit_sha,
    })
    acceptPluginTasks([response.data])
    storeInstallTaskId.value = response.data.task_id
    notify(t('plugin.task_queued'), 'success')
  } catch (e: any) {
    notify(e?.response?.data?.detail || t('pluginStore.install_failed'), 'error')
  } finally {
    installing.value = false
  }
}

async function handleStoreUpdate(item: PluginStoreItem) {
  const plugin = plugins.value.find(p => p.id === item.id)
  if (!plugin) return
  await handleUpdatePlugin(plugin, item.commit_sha)
}

onMounted(async () => {
  void refreshPluginTasks()
  await loadPlugins()
  loadMcpServers()
  loadSkills()
  loadScope()
  // Plugin Store: load saved sources and current source from backend
  loadSourcesFromBackend().then(() => {
    if (currentStoreSource.value) {
      fetchStorePlugins()
    }
  })
  // Auto-check for plugin updates on page load (silent: no notification if none)
  handleCheckUpdates(true)
})
</script>

<style>
.plugin-store-select .custom-select-trigger {
  min-height: 34px;
  padding: 6px 12px;
}
</style>
