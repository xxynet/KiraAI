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
          @click="openInstallDialog"
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
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" />
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
          @click="openSkillsUploadDialog"
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
    <Modal v-model="installDialogVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('plugin.install_add') }}</h3>
          <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="installDialogVisible = false">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
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
              <input
                v-model="installForm.gh_proxy"
                type="text"
                placeholder="https://ghproxy.com/"
                class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
              >
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

    <!-- Plugin Config Dialog -->
    <Modal v-model="pluginConfigVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <div>
            <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('plugin.config_modal_title') }}</h3>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ configPluginName }}</p>
          </div>
          <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="pluginConfigVisible = false">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div class="px-6 py-4 flex-1 overflow-y-auto">
          <div v-if="configLoading" class="flex justify-center items-center py-12">
            <svg class="animate-spin h-6 w-6 text-blue-600 dark:text-blue-400" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          </div>
          <div v-else-if="pluginConfigSchema">
            <ConfigForm v-model="pluginConfigValues" :schema="pluginConfigSchema" />
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
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
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
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
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
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { notify } from '@/composables/useNotification'
import Modal from '@/components/common/Modal.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
import FileDropzone from '@/components/common/FileDropzone.vue'

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
const installForm = ref({ repo_url: '', gh_proxy: '' })
const uploadFile = ref<File | null>(null)
const installDropzoneRef = ref<InstanceType<typeof FileDropzone> | null>(null)
const installing = ref(false)

// Plugin Config
const pluginConfigVisible = ref(false)
const pluginConfigSchema = ref<any>(null)
const pluginConfigValues = ref<Record<string, any>>({})
const configPluginId = ref('')
const configPluginName = ref('')
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

// Confirm modal state
const confirmModalRef = ref<InstanceType<typeof ConfirmModal> | null>(null)
const confirmTitle = ref('')
const confirmMessage = ref('')
const confirmButtonText = ref('')
let pendingConfirmAction: (() => void) | null = null

function openConfirm(title: string, message: string, buttonText: string, action: () => void) {
  confirmTitle.value = title
  confirmMessage.value = message
  confirmButtonText.value = buttonText
  pendingConfirmAction = action
  confirmModalRef.value?.open()
}

function onConfirmAction() {
  pendingConfirmAction?.()
  pendingConfirmAction = null
}

function onCancelAction() {
  pendingConfirmAction = null
}

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
    notify(pluginsError.value!, 'error')
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
  openConfirm(
    t('plugin.uninstall'),
    t('plugin.uninstall_confirm'),
    t('plugin.uninstall'),
    async () => {
      try {
        await deletePlugin(id)
        notify(t('plugin.uninstall_success'), 'success')
        await loadPlugins()
      } catch {
        notify(t('plugin.uninstall_failed'), 'error')
      }
    }
  )
}

async function openPluginConfig(plugin: PluginItem) {
  configPluginId.value = plugin.id
  configPluginName.value = plugin.name || plugin.id
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
  installForm.value = { repo_url: '', gh_proxy: '' }
  uploadFile.value = null
  installDropzoneRef.value?.reset()
  installTab.value = 'github'
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
      const ghProxy = installForm.value.gh_proxy?.trim() || undefined
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
  } catch {
    notify(t('plugin.install_failed'), 'error')
  } finally {
    installing.value = false
  }
}

async function toggleMcp(server: McpServerItem) {
  try {
    await toggleMcpServer(server.id, !server.enabled)
    notify(t('plugin.mcp_toggle_success'), 'success')
  } catch {
    notify(t('plugin.mcp_toggle_failed'), 'error')
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
    notify(t('plugin.mcp_config_load_failed'), 'error')
  }
}

async function saveMcpForm() {
  if (!mcpForm.value.name?.trim()) {
    notify(t('plugin.mcp_name_required'), 'error')
    return
  }
  savingMcp.value = true
  let config: any
  try {
    config = JSON.parse(mcpConfigJson.value)
  } catch {
    notify(t('plugin.mcp_invalid_json'), 'error')
    savingMcp.value = false
    return
  }
  // Backend expects a JSON object; reject arrays, null, and primitives up
  // front so the user sees the same error as the catch branch instead of a
  // 400 from the server.
  if (config === null || typeof config !== 'object' || Array.isArray(config)) {
    notify(t('plugin.mcp_invalid_json'), 'error')
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
    notify(t('plugin.mcp_save_success'), 'success')
    await loadMcpServers()
  } catch {
    notify(t('plugin.mcp_save_failed'), 'error')
  } finally {
    savingMcp.value = false
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
      } catch {
        notify(t('plugin.mcp_delete_failed'), 'error')
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

onMounted(() => {
  loadPlugins()
  loadMcpServers()
  loadSkills()
})
</script>
