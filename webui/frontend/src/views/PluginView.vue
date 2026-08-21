<template>
  <div>
    <!-- Title -->
    <div class="flex items-center mb-6">
      <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('plugin.title') }}</h3>
    </div>

    <!-- Custom Tabs -->
    <div class="flex flex-wrap gap-x-4 mb-4 border-b border-gray-200 dark:border-gray-700">
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
        :class="activeTab === 'pluginStore' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'"
        @click="activeTab = 'pluginStore'"
      >
        {{ $t('pluginStore.title') }}
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
      <button
        type="button"
        class="px-3 py-2 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
        :class="activeTab === 'scope' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'"
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
          class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          @click="openInstallDialog"
        >
          <span class="mr-1">+</span>
          <span>{{ $t('plugin.install_add') }}</span>
        </button>
        <button
          type="button"
          class="inline-flex shrink-0 items-center whitespace-nowrap px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          :disabled="refreshingPlugins"
          @click="refreshPlugins"
        >
          <IconRefresh class="w-4 h-4 mr-1" :class="{ 'animate-spin': refreshingPlugins }" />
          <span>{{ $t('common.refresh') }}</span>
        </button>
        <div class="relative w-full sm:ml-auto sm:w-56">
          <input
            v-model="pluginsSearchTerm"
            type="text"
            :placeholder="$t('plugin.search_placeholder')"
            :aria-label="$t('plugin.search_placeholder')"
            class="w-full border border-gray-300 dark:border-gray-600 rounded-lg pl-9 pr-3 py-1.5 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
          />
          <IconSearch class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
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
          <IconPuzzle class="w-16 h-16 text-gray-400 mx-auto mb-4" />
          <p class="text-gray-500">{{ $t('plugin.no_plugins') }}</p>
        </div>
      </div>

      <div v-else-if="filteredPlugins.length === 0" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconSearch class="w-8 h-8 text-gray-400 mx-auto mb-2 opacity-50" />
          <p class="text-sm text-gray-400 dark:text-gray-500">{{ $t('plugin.no_search_results') }}</p>
        </div>
      </div>

      <div v-else class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
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
          class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
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
          <IconServer class="w-16 h-16 text-gray-400 mx-auto mb-4" />
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
      <div class="flex flex-wrap items-center gap-2 mb-4">
        <button
          type="button"
          class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors mr-2"
          @click="openSkillsUploadDialog"
        >
          <IconUpload class="w-4 h-4 mr-1" />
          <span>{{ $t('plugin.skills_upload') }}</span>
        </button>
        <button
          type="button"
          class="inline-flex shrink-0 items-center whitespace-nowrap px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
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
          <IconLightbulb class="w-16 h-16 text-gray-400 mx-auto mb-4" />
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
            <div class="text-xs font-mono text-gray-400 dark:text-gray-500 break-all mb-3">{{ skill.path }}</div>
            <div class="flex items-center justify-between gap-3">
              <div class="text-xs text-gray-400 dark:text-gray-500">{{ formatBytes(skill.size_bytes) }}</div>
              <div class="flex items-center justify-end space-x-3">
              <button
                type="button"
                class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800 transition-colors"
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
          <h4 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">{{ $t('plugin.scope_mcp_section') }}</h4>
          <div v-if="scopeMcpServers.length === 0" class="text-xs text-gray-400 dark:text-gray-500">-</div>
          <div v-for="mcp in scopeMcpServers" :key="mcp.id" class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 mb-3">
            <div class="flex items-center justify-between mb-2">
              <span class="text-sm font-medium text-gray-800 dark:text-gray-200">{{ mcp.name }}</span>
              <div class="flex items-center space-x-0.5 flex-shrink-0">
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-l-md border transition-colors"
                  :class="scopeEditMcp[mcp.id]?.mode === 'global' ? 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 border-green-300 dark:border-green-700' : 'bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
                  @click="onScopeModeChange(mcp.id, 'mcp', 'global')"
                >{{ $t('plugin.scope_global') }}</button>
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs border-t border-b transition-colors"
                  :class="scopeEditMcp[mcp.id]?.mode === 'allow' ? 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 border-blue-300 dark:border-blue-700' : 'bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
                  @click="onScopeModeChange(mcp.id, 'mcp', 'allow')"
                >{{ $t('plugin.scope_mode_allow') }}</button>
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-r-md border transition-colors"
                  :class="scopeEditMcp[mcp.id]?.mode === 'deny' ? 'bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300 border-red-300 dark:border-red-700' : 'bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
                  @click="onScopeModeChange(mcp.id, 'mcp', 'deny')"
                >{{ $t('plugin.scope_mode_deny') }}</button>
              </div>
            </div>
            <div v-if="scopeEditMcp[mcp.id]?.mode !== 'global'" class="mt-2 pt-2 border-t border-gray-100 dark:border-gray-800">
              <p class="text-xs text-gray-400 dark:text-gray-500 mb-1.5">
                {{ scopeEditMcp[mcp.id]?.mode === 'allow' ? $t('plugin.scope_mode_allow_hint') : $t('plugin.scope_mode_deny_hint') }}
              </p>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-0.5">
                <div v-for="s in scopeSessions" :key="s.id" class="flex items-center justify-between py-0.5">
                  <span class="text-xs text-gray-600 dark:text-gray-400 truncate mr-2">{{ s.title ? `${s.title} | ${s.id}` : s.id }}</span>
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
          <h4 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">{{ $t('plugin.scope_skills_section') }}</h4>
          <div v-if="scopeSkills.length === 0" class="text-xs text-gray-400 dark:text-gray-500">-</div>
          <div v-for="skill in scopeSkills" :key="skill.name" class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 mb-3">
            <div class="flex items-center justify-between mb-2">
              <span class="text-sm font-medium text-gray-800 dark:text-gray-200">{{ skill.name }}</span>
              <div class="flex items-center space-x-0.5 flex-shrink-0">
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-l-md border transition-colors"
                  :class="scopeEditSkill[skill.name]?.mode === 'global' ? 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 border-green-300 dark:border-green-700' : 'bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
                  @click="onScopeModeChange(skill.name, 'skill', 'global')"
                >{{ $t('plugin.scope_global') }}</button>
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs border-t border-b transition-colors"
                  :class="scopeEditSkill[skill.name]?.mode === 'allow' ? 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 border-blue-300 dark:border-blue-700' : 'bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
                  @click="onScopeModeChange(skill.name, 'skill', 'allow')"
                >{{ $t('plugin.scope_mode_allow') }}</button>
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-r-md border transition-colors"
                  :class="scopeEditSkill[skill.name]?.mode === 'deny' ? 'bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300 border-red-300 dark:border-red-700' : 'bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
                  @click="onScopeModeChange(skill.name, 'skill', 'deny')"
                >{{ $t('plugin.scope_mode_deny') }}</button>
              </div>
            </div>
            <div v-if="scopeEditSkill[skill.name]?.mode !== 'global'" class="mt-2 pt-2 border-t border-gray-100 dark:border-gray-800">
              <p class="text-xs text-gray-400 dark:text-gray-500 mb-1.5">
                {{ scopeEditSkill[skill.name]?.mode === 'allow' ? $t('plugin.scope_mode_allow_hint') : $t('plugin.scope_mode_deny_hint') }}
              </p>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-0.5">
                <div v-for="s in scopeSessions" :key="s.id" class="flex items-center justify-between py-0.5">
                  <span class="text-xs text-gray-600 dark:text-gray-400 truncate mr-2">{{ s.title ? `${s.title} | ${s.id}` : s.id }}</span>
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
          class="inline-flex shrink-0 items-center whitespace-nowrap px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          @click="openSourceManage"
        >
          <IconCog class="w-4 h-4 mr-1" />
          <span>{{ $t('pluginStore.sources') }}</span>
        </button>
        <button
          v-if="currentStoreSource"
          type="button"
          class="inline-flex shrink-0 items-center whitespace-nowrap px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          :disabled="storeLoading"
          @click="() => fetchStorePlugins(true)"
        >
          <IconRefresh class="w-4 h-4 mr-1" :class="{ 'animate-spin': storeLoading }" />
          <span>{{ $t('common.refresh') }}</span>
        </button>
        <span v-if="currentStoreSource" class="w-full text-sm text-gray-500 dark:text-gray-400 sm:w-auto sm:ml-1">
          {{ $t('pluginStore.current_source') }}: <span class="font-medium text-gray-700 dark:text-gray-300">{{ currentStoreSource.name }}</span>
        </span>
        <div v-if="currentStoreSource && !storeLoading && storePlugins.length > 0" class="flex w-full flex-col gap-3 sm:ml-auto sm:w-auto sm:flex-row sm:flex-wrap sm:items-center sm:justify-end">
          <label class="flex w-full items-center justify-between gap-2 text-sm text-gray-600 dark:text-gray-300 sm:w-auto sm:justify-start">
            <span>{{ $t('pluginStore.category') }}</span>
            <div class="w-32 shrink-0 plugin-store-select">
              <CustomSelect v-model="storeCategory" :options="storeCategoryOptions" />
            </div>
          </label>
          <label class="flex w-full items-center justify-between gap-2 text-sm text-gray-600 dark:text-gray-300 sm:w-auto sm:justify-start">
            <span>{{ $t('pluginStore.sort') }}</span>
            <div class="w-32 shrink-0 plugin-store-select">
              <CustomSelect v-model="storeSort" :options="storeSortOptions" />
            </div>
          </label>
          <div class="relative w-full sm:w-56">
            <input
              v-model="storeSearchTerm"
              type="text"
              :placeholder="$t('plugin.search_placeholder')"
              :aria-label="$t('plugin.search_placeholder')"
              class="w-full border border-gray-300 dark:border-gray-600 rounded-lg pl-9 pr-3 py-1.5 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
            />
            <IconSearch class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          </div>
        </div>
      </div>

      <div v-if="storeInstallTask?.status === 'installing'" class="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-200">
        <IconSpinner class="h-4 w-4 animate-spin shrink-0" />
        <span class="min-w-0 flex-1 truncate">{{ storeInstallTarget?.name || storeInstallTask.repo_url }} · {{ storeInstallStageLabel }}</span>
        <button type="button" class="font-medium hover:underline" @click="storeInstallVisible = true">{{ $t('pluginStore.install_view_progress') }}</button>
        <button type="button" class="font-medium text-red-600 hover:underline disabled:opacity-50 dark:text-red-400" :disabled="storeInstallTask.stage === 'loading'" @click="cancelStoreInstall">{{ $t('pluginStore.install_cancel') }}</button>
      </div>

      <!-- Plugin Store Error -->
      <div v-if="storeError" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconInfo class="w-16 h-16 text-red-400 mx-auto mb-4" />
          <p class="text-red-500">{{ storeError }}</p>
          <button
            type="button"
            class="mt-3 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            @click="() => fetchStorePlugins()"
          >
            {{ $t('common.refresh') }}
          </button>
        </div>
      </div>

      <!-- No Source Configured -->
      <div v-else-if="!currentStoreSource" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconPackage class="w-16 h-16 text-gray-400 mx-auto mb-4" />
          <p class="text-gray-500 mb-3">{{ $t('pluginStore.no_sources') }}</p>
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
          <IconBox class="w-16 h-16 text-gray-400 mx-auto mb-4" />
          <p class="text-gray-500">{{ $t('pluginStore.no_plugins') }}</p>
        </div>
      </div>

      <!-- No Search Results -->
      <div v-else-if="filteredStorePlugins.length === 0" class="flex justify-center items-center py-12">
        <div class="text-center">
          <IconSearch class="w-8 h-8 text-gray-400 mx-auto mb-2 opacity-50" />
          <p class="text-sm text-gray-400 dark:text-gray-500">{{ $t('plugin.no_search_results') }}</p>
        </div>
      </div>

      <!-- Plugin Cards Grid -->
      <div v-else class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
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
          :installed="item.installed"
          :installing="storeInstallTarget?.id === item.id && storeInstallTask?.status === 'installing'"
          :has-update="item.installed && pluginUpdates.has(item.id)"
          :latest-version="pluginUpdates.get(item.id)?.latest_version ?? null"
          :updating="updatingPlugins.has(item.id)"
          @install="handleStoreInstall(item)"
          @update="handleStoreUpdate(item)"
          @details="openPluginDetails(item)"
        />
      </div>

      <div v-if="filteredStorePlugins.length > STORE_PAGE_SIZE" class="mt-6 flex items-center justify-center gap-3">
        <button
          type="button"
          class="px-3 py-1.5 text-sm font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
          :disabled="storePage === 1"
          @click="storePage--"
        >
          {{ $t('pluginStore.pagination_previous') }}
        </button>
        <span class="text-sm text-gray-500 dark:text-gray-400">
          {{ $t('pluginStore.pagination_page', { page: storePage, total: storeTotalPages }) }}
        </span>
        <button
          type="button"
          class="px-3 py-1.5 text-sm font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
          :disabled="storePage === storeTotalPages"
          @click="storePage++"
        >
          {{ $t('pluginStore.pagination_next') }}
        </button>
      </div>

      <!-- Plugin Sources Management Modal -->
      <Modal v-model="sourceManageVisible" content-class="max-w-lg">
        <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
          <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('pluginStore.source_manage') }}</h3>
            <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="sourceManageVisible = false">
              <IconClose class="w-6 h-6" />
            </button>
          </div>
          <div class="px-6 py-5 flex-1 overflow-y-auto space-y-4">
            <p class="text-sm text-gray-500 dark:text-gray-400">{{ $t('pluginStore.source_manage_desc') }}</p>

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
                  <div class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ src.name }}</div>
                  <div class="text-xs text-gray-500 dark:text-gray-400 truncate">{{ src.url }}</div>
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
            <div v-else class="text-center py-4 text-sm text-gray-400 dark:text-gray-500">
              {{ $t('pluginStore.no_sources') }}
            </div>

            <!-- Add New Source Form -->
            <div class="border-t border-gray-200 dark:border-gray-700 pt-4">
              <div class="mb-3">
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{{ $t('pluginStore.source_name') }}</label>
                <input
                  v-model="newSourceName"
                  type="text"
                  :placeholder="$t('pluginStore.source_name_placeholder')"
                  class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                >
              </div>
              <div class="mb-3">
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{{ $t('pluginStore.source_url') }}</label>
                <input
                  v-model="newSourceUrl"
                  type="text"
                  :placeholder="$t('pluginStore.source_url_placeholder')"
                  class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                >
              </div>
            </div>
          </div>
          <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
            <button
              type="button"
              class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
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
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('pluginStore.install_details_title') }}</h3>
          <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="storeInstallVisible = false"><IconClose class="w-6 h-6" /></button>
        </div>
        <div class="px-6 py-5 space-y-4 overflow-y-auto">
          <div class="flex min-w-0 items-start gap-3">
            <img v-if="storeInstallIcon" :src="storeInstallIcon" :alt="''" class="h-12 w-12 shrink-0 object-contain" />
            <div class="min-w-0">
              <p class="truncate text-base font-semibold text-gray-900 dark:text-gray-100">{{ storePluginName(storeInstallTarget) }}</p>
              <p v-if="storeInstallTarget.version || storeInstallTarget.author" class="mt-1 text-xs text-gray-500 dark:text-gray-400">v{{ storeInstallTarget.version }}<span v-if="storeInstallTarget.version && storeInstallTarget.author"> · </span>{{ storeInstallTarget.author }}</p>
            </div>
          </div>
          <p v-if="storeInstallTarget.description" class="whitespace-pre-wrap text-sm leading-6 text-gray-600 dark:text-gray-300">{{ localize(storeInstallTarget, 'description', storeInstallTarget.description) }}</p>
          <div v-if="storeInstallTarget.tags?.length" class="flex flex-wrap gap-1.5">
            <span v-for="tag in storeInstallTarget.tags" :key="tag" class="inline-block rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">{{ tag }}</span>
          </div>
          <dl class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            <div><dt class="text-gray-500 dark:text-gray-400">{{ $t('plugin.plugin_id') }}</dt><dd class="mt-1 font-mono break-all text-gray-900 dark:text-gray-100">{{ storeInstallTarget.id }}</dd></div>
            <div v-if="storeInstallRepo" class="sm:col-span-2"><dt class="text-gray-500 dark:text-gray-400">{{ $t('plugin.repo_url') }}</dt><dd class="mt-1 break-all"><a :href="storeInstallRepo" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:text-blue-700 hover:underline dark:text-blue-400 dark:hover:text-blue-300">{{ storeInstallRepo }}</a></dd></div>
          </dl>
          <div v-if="storeInstallTask" class="rounded-md border border-gray-200 p-3 text-sm dark:border-gray-700">
            <div class="flex items-center gap-2 text-gray-700 dark:text-gray-200"><IconSpinner v-if="storeInstallTask.status === 'installing'" class="h-4 w-4 animate-spin text-blue-600" /><span>{{ storeInstallStageLabel }}</span></div>
            <p v-if="storeInstallTask.error" class="mt-2 break-words text-red-600 dark:text-red-400">{{ storeInstallTask.error }}</p>
          </div>
          <label v-else class="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer"><input v-model="storeInstallSilent" type="checkbox" class="mt-0.5 rounded border-gray-300 dark:border-gray-600" /><span>{{ $t('pluginStore.install_silent') }}</span></label>
        </div>
        <div class="flex justify-end gap-3 border-t border-gray-200 px-6 py-4 dark:border-gray-700">
          <button v-if="storeInstallTask?.status === 'installing'" type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="storeInstallVisible = false">{{ $t('plugin.close') }}</button>
          <button v-else-if="storeInstallTask" type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors" @click="storeInstallVisible = false">{{ $t('plugin.close') }}</button>
          <template v-else>
            <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="storeInstallVisible = false">{{ $t('plugin.cancel') }}</button>
            <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors" @click="startStoreInstall">{{ $t('pluginStore.install') }}</button>
          </template>
          <button v-if="storeInstallTask?.status === 'installing'" type="button" class="px-4 py-2 border border-red-300 text-red-600 rounded-lg hover:bg-red-50 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-900/30 transition-colors disabled:opacity-50" :disabled="storeInstallTask.stage === 'loading'" @click="cancelStoreInstall">{{ $t('pluginStore.install_cancel') }}</button>
        </div>
      </div>
    </Modal>

    <!-- Install Plugin Dialog -->
    <Modal v-model="installDialogVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('plugin.install_add') }}</h3>
          <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="installDialogVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="flex border-b border-gray-200 dark:border-gray-700 px-6">
          <button
            type="button"
            class="px-4 py-3 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
            :class="installTab === 'github' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'"
            @click="installTab = 'github'"
          >
            GitHub
          </button>
          <button
            type="button"
            class="px-4 py-3 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
            :class="installTab === 'upload' ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'"
            @click="installTab = 'upload'"
          >
            {{ $t('plugin.upload_zip') }}
          </button>
        </div>
        <div class="px-6 py-5 flex-1 overflow-y-auto">
          <div v-show="installTab === 'github'">
            <div class="mb-4">
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('plugin.repo_url') }}</label>
              <input
                v-model="installForm.repo_url"
                type="text"
                placeholder="https://github.com/owner/repo"
                class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
              >
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                <span>{{ $t('plugin.install_gh_proxy_label') }}</span>
                <span class="text-xs font-normal text-gray-400 dark:text-gray-500 ml-1">{{ $t('plugin.install_optional') }}</span>
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
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('plugin.install_upload_label') }}</label>
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
          <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="installDialogVisible = false">{{ $t('plugin.cancel') }}</button>
          <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="installing" @click="handleInstall">{{ $t('plugin.install') }}</button>
        </div>
      </div>
    </Modal>

    <!-- Update Plugin Dialog -->
    <Modal v-model="updateDialogVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('plugin.update') }}</h3>
          <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="updateDialogVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-5 flex-1 overflow-y-auto">
          <p class="text-sm text-gray-600 dark:text-gray-300 mb-4">
            {{ $t('plugin.update_confirm', { name: updateTargetPlugin?.name || updateTargetPlugin?.id }) }}
          </p>
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              <span>{{ $t('plugin.install_gh_proxy_label') }}</span>
              <span class="text-xs font-normal text-gray-400 dark:text-gray-500 ml-1">{{ $t('plugin.install_optional') }}</span>
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
          <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="updateDialogVisible = false">{{ $t('plugin.cancel') }}</button>
          <button type="button" class="px-4 py-2 ml-2 bg-green-600 dark:bg-green-700 text-white rounded-lg hover:bg-green-700 dark:hover:bg-green-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="updatingPlugins.has(updateTargetPlugin?.id ?? '')" @click="confirmUpdate">{{ $t('plugin.update') }}</button>
        </div>
      </div>
    </Modal>

    <!-- Plugin Config Dialog -->
    <Modal v-model="pluginDetailsVisible" content-class="max-w-4xl">
      <div v-if="selectedPlugin" class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col overflow-hidden" style="max-height: 90vh;">
        <div class="flex items-start justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <div class="min-w-0 pr-4">
            <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('plugin.details_title') }}</h3>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400 break-words">
              {{ localize(selectedPlugin, 'display_name', selectedPlugin.name || selectedPlugin.id) }}
            </p>
          </div>
          <button type="button" class="flex-shrink-0 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" :aria-label="$t('plugin.close')" @click="pluginDetailsVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-5 flex-1 min-h-0 overflow-y-auto space-y-5">
          <p v-if="localize(selectedPlugin, 'description', selectedPlugin.description)" class="whitespace-pre-wrap text-sm leading-6 text-gray-600 dark:text-gray-300">
            {{ localize(selectedPlugin, 'description', selectedPlugin.description) }}
          </p>
          <p v-else class="text-sm text-gray-400 dark:text-gray-500">{{ $t('plugin.no_description') }}</p>

          <dl class="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 text-sm">
            <div>
              <dt class="text-gray-500 dark:text-gray-400">{{ $t('plugin.plugin_id') }}</dt>
              <dd class="mt-1 font-mono break-all text-gray-900 dark:text-gray-100">{{ selectedPlugin.id }}</dd>
            </div>
            <div v-if="selectedPlugin.version">
              <dt class="text-gray-500 dark:text-gray-400">{{ $t('plugin.version') }}</dt>
              <dd class="mt-1 text-gray-900 dark:text-gray-100">v{{ selectedPlugin.version }}</dd>
            </div>
            <div v-if="selectedPlugin.author">
              <dt class="text-gray-500 dark:text-gray-400">{{ $t('plugin.author') }}</dt>
              <dd class="mt-1 text-gray-900 dark:text-gray-100">{{ selectedPlugin.author }}</dd>
            </div>
            <div v-if="pluginDetailsRepo">
              <dt class="text-gray-500 dark:text-gray-400">{{ $t('plugin.repo_url') }}</dt>
              <dd class="mt-1 break-all">
                <a :href="pluginDetailsRepo" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:text-blue-700 hover:underline dark:text-blue-400 dark:hover:text-blue-300">
                  {{ pluginDetailsRepo }}
                </a>
              </dd>
            </div>
            <div v-if="'category' in selectedPlugin && selectedPlugin.category">
              <dt class="text-gray-500 dark:text-gray-400">{{ $t('plugin.category') }}</dt>
              <dd class="mt-1 text-gray-900 dark:text-gray-100">{{ storeCategoryName(selectedPlugin) }}</dd>
            </div>
            <div v-if="'core_version' in selectedPlugin && selectedPlugin.core_version">
              <dt class="text-gray-500 dark:text-gray-400">{{ $t('plugin.core_version') }}</dt>
              <dd class="mt-1 text-gray-900 dark:text-gray-100">{{ selectedPlugin.core_version }}</dd>
            </div>
          </dl>

          <div v-if="selectedPlugin.tags?.length">
            <p class="text-sm text-gray-500 dark:text-gray-400">{{ $t('plugin.tags') }}</p>
            <div class="mt-2 flex flex-wrap gap-1.5">
              <span v-for="tag in selectedPlugin.tags" :key="tag" class="inline-block rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">{{ tag }}</span>
            </div>
          </div>

          <section v-if="pluginReadmeLoading || pluginReadme" class="border-t border-gray-200 pt-5 dark:border-gray-700">
            <h4 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ $t('plugin.readme_title') }}</h4>
            <div v-if="pluginReadmeLoading" class="mt-3 text-sm text-gray-500 dark:text-gray-400">{{ $t('common.loading') }}</div>
            <article v-else class="plugin-readme mt-3 text-sm leading-6 text-gray-700 dark:text-gray-300" v-html="renderMarkdown(pluginReadme!)" />
          </section>
        </div>
      </div>
    </Modal>

    <Modal v-model="pluginConfigVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <div>
            <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('plugin.config_modal_title') }}</h3>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ configPluginName }}</p>
          </div>
          <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="pluginConfigVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-4 flex-1 overflow-y-auto">
          <div v-if="configLoading" class="flex justify-center items-center py-12">
            <IconSpinner class="animate-spin h-6 w-6 text-blue-600 dark:text-blue-400" />
          </div>
          <div v-else-if="pluginConfigSchema">
            <ConfigForm ref="configFormRef" v-model="pluginConfigValues" :schema="pluginConfigSchema" />
          </div>
          <div v-else class="text-center py-8 text-gray-400">
            {{ $t('plugin.no_config') }}
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="pluginConfigVisible = false">{{ $t('plugin.cancel') }}</button>
          <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="!pluginConfigSchema || savingConfig" @click="savePluginConfig">{{ $t('plugin.save') }}</button>
        </div>
      </div>
    </Modal>

    <!-- Skills Upload Dialog -->
    <Modal v-model="skillsUploadVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('plugin.skills_upload') }}</h3>
          <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="skillsUploadVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-5 flex-1 overflow-y-auto">
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('plugin.skills_upload_label') }}</label>
          <FileDropzone
            ref="skillsDropzoneRef"
            v-model="skillUploadFile"
            accept=".zip"
            :title-fallback="$t('plugin.upload_hint')"
            :reselect-fallback="$t('plugin.upload_hint')"
          />
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="skillsUploadVisible = false">{{ $t('plugin.cancel') }}</button>
          <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="uploadingSkill" @click="handleSkillUpload">{{ $t('plugin.skills_upload_btn') }}</button>
        </div>
      </div>
    </Modal>

    <!-- MCP Config Dialog -->
    <Modal v-model="mcpDialogVisible" content-class="max-w-4xl">
      <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 95vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ mcpEditMode ? $t('plugin.mcp_edit') : $t('plugin.mcp_add') }}</h3>
          <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="mcpDialogVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-4 flex-1 overflow-y-auto space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('plugin.mcp_name') }}</label>
            <input
              v-model="mcpForm.name"
              type="text"
              class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
            >
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('plugin.mcp_description') }}</label>
            <textarea
              v-model="mcpForm.description"
              rows="2"
              class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors resize-none"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('plugin.mcp_config') }}</label>
            <MonacoEditor v-model="mcpConfigJson" language="json" height="300px" />
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="mcpDialogVisible = false">{{ $t('plugin.cancel') }}</button>
          <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="savingMcp" @click="saveMcpForm">{{ $t('plugin.save') }}</button>
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
        <label class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
          <input type="checkbox" v-model="uninstallDeleteConfig" class="rounded border-gray-300 dark:border-gray-600" />
          {{ t('plugin.delete_config') }}
        </label>
        <label class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
          <input type="checkbox" v-model="uninstallDeleteData" class="rounded border-gray-300 dark:border-gray-600" />
          {{ t('plugin.delete_data') }}
        </label>
      </div>
    </ConfirmModal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { useLocalized } from '@/composables/useLocalized'
import { notify } from '@/composables/useNotification'
import { useTheme } from '@/composables/useTheme'
import Modal from '@/components/common/Modal.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
import FileDropzone from '@/components/common/FileDropzone.vue'
import AlertHint from '@/components/common/AlertHint.vue'

import {
  getPlugins, getPluginConfig, getPluginReadme, updatePluginConfig,
  togglePlugin as apiTogglePlugin, deletePlugin,
  installFromGithub, installFromUpload, startGithubInstallTask, getActivePluginInstallTask,
  getPluginInstallTask, cancelPluginInstallTask,
  reloadPlugin as apiReloadPlugin,
  checkPluginUpdates, updatePlugin as apiUpdatePlugin,
} from '@/api/plugin'
import {
  getMcpServers, getMcpServerConfig, createMcpServer, updateMcpServerConfig,
  deleteMcpServer, toggleMcpServer,
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
import type { PluginItem, McpServerItem, PluginStoreSource, PluginStoreItem, PluginUpdateCheckItem, PluginInstallTask } from '@/types'
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
const updatingPlugins = ref(new Set<string>())
const updateDialogVisible = ref(false)
const updateTargetPlugin = ref<PluginItem | null>(null)
const pluginDetailsVisible = ref(false)
const selectedPlugin = ref<PluginItem | PluginStoreItem | null>(null)
const pluginReadme = ref<string | null>(null)
const pluginReadmeLoading = ref(false)
let pluginReadmeRequest = 0
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
  const request = ++pluginReadmeRequest
  selectedPlugin.value = plugin
  pluginDetailsVisible.value = true
  pluginReadme.value = null
  const installedPlugin = plugins.value.find(item => item.id === plugin.id)
  if (!installedPlugin) {
    pluginReadmeLoading.value = false
    return
  }

  pluginReadmeLoading.value = true
  try {
    const res = await getPluginReadme(installedPlugin.id)
    if (request === pluginReadmeRequest) pluginReadme.value = res.data.readme
  } catch {
    // README is optional and must not prevent opening plugin details.
  } finally {
    if (request === pluginReadmeRequest) pluginReadmeLoading.value = false
  }
}

function renderMarkdown(text: string): string {
  const sanitized = DOMPurify.sanitize(marked.parse(text, { async: false }) as string)
  const parsedDocument = new DOMParser().parseFromString(sanitized, 'text/html')
  parsedDocument.querySelectorAll('a').forEach(link => {
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
  })
  return parsedDocument.body.innerHTML
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
    const map = new Map<string, PluginUpdateCheckItem>()
    for (const item of res.data) {
      if (item.has_update) {
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

async function handleUpdatePlugin(plugin: PluginItem) {
  updateTargetPlugin.value = plugin
  updateDialogVisible.value = true
}

function resolveGhProxy(): string | undefined {
  if (proxyStrategy.value === 'specific') return selectedProxyUrl.value
  if (proxyStrategy.value === 'auto') return 'auto'
  return undefined
}

async function confirmUpdate() {
  const plugin = updateTargetPlugin.value
  if (!plugin) return
  updateDialogVisible.value = false
  updatingPlugins.value.add(plugin.id)
  try {
    await apiUpdatePlugin(plugin.id, { gh_proxy: resolveGhProxy() })
    pluginUpdates.value.delete(plugin.id)
    notify(t('plugin.update_success'), 'success')
    await loadPlugins()
  } catch {
    notify(t('plugin.update_failed'), 'error')
  } finally {
    updatingPlugins.value.delete(plugin.id)
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
  if (pluginPollTimer) {
    clearInterval(pluginPollTimer)
    pluginPollTimer = null
  }
  stopStoreInstallPolling()
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
  if (!pluginConfigSchema.value) return
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
      await installFromGithub({ repo_url: repoUrl, gh_proxy: ghProxy })
    } else {
      if (!uploadFile.value) {
        notify(t('plugin.file_required'), 'error')
        installing.value = false
        return
      }
      await installFromUpload(uploadFile.value)
      uploadFile.value = null
    }
    installDialogVisible.value = false
    notify(t('plugin.install_success'), 'success')
    await loadPlugins()
  } catch (e: any) {
    if (e?.response?.status === 409) {
      notify(t('plugin.install_already_installed'), 'error')
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
    mcpForm.value = { name: res.data?.name || server.name, description: res.data?.description || server.description || '' }
    mcpConfigJson.value = JSON.stringify(res.data?.config ?? {}, null, 2)
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
const storeInstallTask = ref<PluginInstallTask | null>(null)
const storeInstallSilent = ref(false)
let storeInstallPollTimer: ReturnType<typeof setInterval> | null = null
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
  if (!q) return plugins.value
  return plugins.value.filter(p => {
    const name = (localize(p, 'display_name', p.name) || '').toLowerCase()
    const desc = (localize(p, 'description', p.description) || '').toLowerCase()
    const author = (p.author || '').toLowerCase()
    const id = p.id.toLowerCase()
    const tags = (p.tags || []).join(' ').toLowerCase()
    return name.includes(q) || desc.includes(q) || author.includes(q) || id.includes(q) || tags.includes(q)
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
    if (storeInstallTask.value && !storeInstallTarget.value) {
      storeInstallTarget.value = storePlugins.value.find(item => item.repo === storeInstallTask.value?.repo_url) || null
    }
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
  if (item.installed) return
  storeInstallTarget.value = item
  storeInstallTask.value = null
  storeInstallSilent.value = false
  storeInstallVisible.value = true
}

const storeInstallStageLabel = computed(() => {
  const stage = storeInstallTask.value?.stage
  if (!stage) return ''
  const labels: Record<PluginInstallTask['stage'], string> = {
    downloading: t('pluginStore.install_stage_downloading'),
    installing_dependencies: t('pluginStore.install_stage_dependencies'),
    loading: t('pluginStore.install_stage_loading'),
    completed: t('pluginStore.install_stage_completed'),
    failed: t('pluginStore.install_stage_failed'),
    cancelled: t('pluginStore.install_stage_cancelled'),
  }
  return labels[stage]
})

function resolveStoreInstallProxy(): string | null {
  if (proxyStrategy.value === 'specific') return selectedProxyUrl.value
  return proxyStrategy.value === 'auto' ? 'auto' : null
}

async function startStoreInstall() {
  const item = storeInstallTarget.value
  if (!item?.repo) {
    notify(t('plugin.install_failed'), 'error')
    return
  }
  try {
    const response = await startGithubInstallTask({ repo_url: item.repo, gh_proxy: resolveStoreInstallProxy() })
    storeInstallTask.value = response.data
    startStoreInstallPolling()
    if (storeInstallSilent.value) storeInstallVisible.value = false
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    notify(detail ? `${t('pluginStore.install_failed')}: ${detail}` : t('pluginStore.install_failed'), 'error')
  }
}

function stopStoreInstallPolling() {
  if (storeInstallPollTimer) {
    clearInterval(storeInstallPollTimer)
    storeInstallPollTimer = null
  }
}

function startStoreInstallPolling() {
  if (!storeInstallTask.value || storeInstallPollTimer) return
  storeInstallPollTimer = setInterval(() => { void refreshStoreInstallTask() }, 1000)
  void refreshStoreInstallTask()
}

async function refreshStoreInstallTask() {
  const task = storeInstallTask.value
  if (!task) return
  try {
    const response = await getPluginInstallTask(task.task_id)
    storeInstallTask.value = response.data
    if (response.data.status === 'installing') return
    stopStoreInstallPolling()
    if (response.data.status === 'completed') {
      await loadPlugins()
      await fetchStorePlugins()
      if (!storeInstallSilent.value) notify(t('pluginStore.install_success'), 'success')
    } else if (response.data.status === 'cancelled') {
      if (!storeInstallSilent.value) notify(t('pluginStore.install_cancelled'), 'success')
    } else if (!storeInstallSilent.value) {
      notify(t('pluginStore.install_failed'), 'error')
    }
  } catch {
    stopStoreInstallPolling()
  }
}

async function cancelStoreInstall() {
  const task = storeInstallTask.value
  if (!task || task.status !== 'installing') return
  try {
    const response = await cancelPluginInstallTask(task.task_id)
    storeInstallTask.value = response.data
    await refreshStoreInstallTask()
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    notify(detail ? `${t('pluginStore.install_failed')}: ${detail}` : t('pluginStore.install_failed'), 'error')
  }
}

async function handleStoreUpdate(item: PluginStoreItem) {
  const plugin = plugins.value.find(p => p.id === item.id)
  if (!plugin) return
  await handleUpdatePlugin(plugin)
}

onMounted(async () => {
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
  getActivePluginInstallTask().then(response => {
    const task = response.data
    if (!task) return
    storeInstallTask.value = task
    const matchingItem = storePlugins.value.find(item => item.repo === task.repo_url)
    if (matchingItem) storeInstallTarget.value = matchingItem
    startStoreInstallPolling()
  }).catch(() => {})
  // Auto-check for plugin updates on page load (silent: no notification if none)
  handleCheckUpdates(true)
})
</script>

<style>
.plugin-readme h1,
.plugin-readme h2,
.plugin-readme h3 {
  margin: 1em 0 0.5em;
  font-weight: 600;
}

.plugin-readme h1 { font-size: 1.25em; }
.plugin-readme h2 { font-size: 1.125em; }
.plugin-readme h3 { font-size: 1em; }

.plugin-readme p,
.plugin-readme ul,
.plugin-readme ol,
.plugin-readme pre {
  margin: 0.75em 0;
}

.plugin-readme ul { list-style: disc; padding-left: 1.5em; }
.plugin-readme ol { list-style: decimal; padding-left: 1.5em; }
.plugin-readme pre { overflow-x: auto; padding: 0.75em; border-radius: 0.375rem; background: rgb(243 244 246); color: rgb(31 41 55); }
.plugin-readme code { padding: 0.125em 0.25em; border-radius: 0.25rem; background: rgb(243 244 246); font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.plugin-readme pre code { padding: 0; background: transparent; }
.plugin-readme a { color: rgb(37 99 235); text-decoration: underline; }
.plugin-readme blockquote { margin: 0.75em 0; border-left: 3px solid rgb(209 213 219); padding-left: 0.75em; color: rgb(75 85 99); }
.plugin-readme hr { margin: 1.25em 0; border-color: rgb(229 231 235); }
.plugin-readme table { display: block; width: max-content; max-width: 100%; overflow-x: auto; border-collapse: collapse; }
.plugin-readme th,
.plugin-readme td { border: 1px solid rgb(229 231 235); padding: 0.5em 0.75em; text-align: left; }
.plugin-readme th { background: rgb(249 250 251); font-weight: 600; }
.plugin-readme img { max-width: 100%; height: auto; }

.dark .plugin-readme pre { background: rgb(31 41 55); color: rgb(229 231 235); }
.dark .plugin-readme code { background: rgb(31 41 55); }
.dark .plugin-readme pre code { background: transparent; }
.dark .plugin-readme a { color: rgb(96 165 250); }
.dark .plugin-readme blockquote { border-color: rgb(75 85 99); color: rgb(156 163 175); }
.dark .plugin-readme hr { border-color: rgb(55 65 81); }
.dark .plugin-readme th,
.dark .plugin-readme td { border-color: rgb(55 65 81); }
.dark .plugin-readme th { background: rgb(31 41 55); }

.plugin-store-select .custom-select-trigger {
  min-height: 34px;
  padding: 6px 12px;
}
</style>
