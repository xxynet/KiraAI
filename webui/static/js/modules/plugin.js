/**
 * Plugin & MCP server domain module
 * Handles plugin list rendering, enable/disable toggling, plugin config modal,
 * MCP server list rendering, MCP config editor modal, and plugin/MCP tab setup.
 *
 * Dependencies (loaded before this file):
 *   core/state.js    — AppState
 *   core/api.js      — apiCall
 *   core/notify.js   — showNotification
 *   core/modal.js    — Modal
 *   core/monaco.js   — Monaco
 *   shared/render-config-fields.js — renderConfigFields, collectConfigFromContainer
 *   app.js (global)  — escapeHtml, getTranslation, updateTranslations
 */

// Tracks which plugin's config modal is open
const PluginConfigModalState = {
    pluginId: null
};

// Tracks the MCP config editor state (edit vs create)
const mcpEditorState = {
    instance: null,
    serverId: null,
    mode: 'edit'
};

// ---------------------------------------------------------------------------
// Data loaders
// ---------------------------------------------------------------------------

async function loadPluginData() {
    try {
        const response = await apiCall('/api/plugins');
        const data = await response.json();
        AppState.data.plugins = Array.isArray(data) ? data : [];
        renderPluginList();
    } catch (error) {
        console.error('Error loading plugin data:', error);
    }
}

async function loadMcpServers() {
    try {
        const response = await apiCall('/api/mcp-servers');
        const data = await response.json();
        AppState.data.mcpServers = Array.isArray(data) ? data : [];
        renderMcpServers();
    } catch (error) {
        console.error('Error loading MCP servers:', error);
    }
}

// ---------------------------------------------------------------------------
// Plugin list rendering
// ---------------------------------------------------------------------------

function renderPluginList() {
    const container = document.getElementById('plugin-list');
    if (!container) {
        return;
    }
    const plugins = AppState.data.plugins || [];
    if (!plugins.length) {
        container.innerHTML = `
            <div class="flex items-center justify-start mb-4">
                <button
                    type="button"
                    id="plugin-add-button"
                    class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                    <span class="mr-1">+</span>
                    <span data-i18n="plugin.install_add">Install Plugin</span>
                </button>
            </div>
            <div class="flex justify-center items-center py-12">
                <div class="text-center">
                    <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 4a2 2 0 114 0v1a1 1 0 001 1h3a1 1 0 011 1v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H7a1 1 0 01-1-1v-3a1 1 0 00-1-1H4a2 2 0 110-4h1a1 1 0 001-1V7a1 1 0 011-1h3a1 1 0 001-1V4z"></path>
                    </svg>
                    <p class="text-gray-500" data-i18n="plugin.no_plugins">No add-ons configured</p>
                </div>
            </div>
        `;
        attachPluginToggleHandlers();
        if (window.i18n) {
            updateTranslations();
        }
        return;
    }
    const cards = plugins.map((plugin) => {
        const id = plugin.id || '';
        const name = plugin.name || id || '';
        const version = plugin.version || '';
        const author = plugin.author || '';
        const description = plugin.description || '';
        const repo = plugin.repo || '';
        const enabled = plugin.enabled !== false;
        const showMeta = version || author;
        const toggleOnClasses = 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500';
        const toggleOffClasses = 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600';
        const knobOnClasses = 'translate-x-4';
        const knobOffClasses = 'translate-x-0';
        const toggleClasses = enabled ? toggleOnClasses : toggleOffClasses;
        const knobClasses = enabled ? knobOnClasses : knobOffClasses;
        return `
            <div class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 flex flex-col">
                <div class="flex items-start justify-between mb-3">
                    <div>
                        <div class="text-base font-semibold text-gray-900 dark:text-gray-100">${escapeHtml(name)}</div>
                        ${showMeta ? `
                            <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                                ${version ? `v${escapeHtml(String(version))}` : ''}${version && author ? ' · ' : ''}${author ? escapeHtml(String(author)) : ''}
                            </div>
                        ` : ''}
                    </div>
                    <div class="flex items-start space-x-2">
                        ${repo ? `
                            <a href="${escapeHtml(String(repo))}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 mt-1">
                                <span class="mr-1">Repo</span>
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 3h7m0 0v7m0-7L10 14"></path>
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10v11h11"></path>
                                </svg>
                            </a>
                        ` : ''}
                        <button
                            type="button"
                            class="ml-2 relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none ${toggleClasses}"
                            aria-pressed="${enabled ? 'true' : 'false'}"
                            data-plugin-id="${escapeHtml(String(id))}"
                            aria-label="${window.i18n ? window.i18n.t('plugin.toggle_label') : 'Enable plugin'}"
                        >
                            <span class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${knobClasses}"></span>
                        </button>
                    </div>
                </div>
                ${description ? `
                    <p class="text-sm text-gray-600 dark:text-gray-300 line-clamp-3 mb-3" title="${escapeHtml(String(description))}">
                        ${escapeHtml(String(description))}
                    </p>
                ` : ''}
                <div class="mt-auto">
                    <div class="text-xs font-mono text-gray-400 dark:text-gray-500 break-all mb-3">
                        ${escapeHtml(String(id))}
                    </div>
                    <div class="flex items-center justify-end space-x-3">
                        <button
                            type="button"
                            class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
                            data-i18n="plugin.configure"
                            data-plugin-config-id="${escapeHtml(String(id))}"
                        >
                            Configure
                        </button>
                        <button
                            type="button"
                            class="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30"
                            data-i18n="plugin.uninstall"
                            onclick="deletePlugin('${escapeHtml(String(id))}')"
                        >
                            Uninstall
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
    container.innerHTML = `
        <div class="flex items-center justify-start mb-4">
            <button
                type="button"
                id="plugin-add-button"
                class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            >
                <span class="mr-1">+</span>
                <span data-i18n="plugin.install_add">Install Plugin</span>
            </button>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-3 gap-4">
            ${cards}
        </div>
    `;
    attachPluginToggleHandlers();
    if (window.i18n) {
        updateTranslations();
    }
}

// ---------------------------------------------------------------------------
// MCP server list rendering
// ---------------------------------------------------------------------------

function renderMcpServers() {
    const container = document.getElementById('plugin-mcp');
    if (!container) {
        return;
    }
    const servers = AppState.data.mcpServers || [];
    if (!servers.length) {
        const emptyText = window.i18n ? window.i18n.t('plugin.no_mcp_servers') : 'No MCP servers configured';
        container.innerHTML = `
            <div class="flex items-center justify-start mb-4">
                <button
                    type="button"
                    id="mcp-add-button"
                    class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                    <span class="mr-1">+</span>
                    <span data-i18n="plugin.mcp_add">Add MCP server</span>
                </button>
            </div>
            <div class="flex justify-center items-center py-12">
                <div class="text-center">
                    <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M12 6a9 9 0 11-9 9 9 9 0 019-9z"></path>
                    </svg>
                    <p class="text-gray-500">${escapeHtml(emptyText)}</p>
                </div>
            </div>
        `;
        attachMcpHandlers();
        if (window.i18n) {
            updateTranslations();
        }
        return;
    }
    const cards = servers.map((server) => {
        const id = server.id || '';
        const type = server.type || '';
        const name = server.name || id || '';
        const description = server.description || '';
        const enabled = server.enabled === true;
        const toolsCount = typeof server.tools_count === 'number' ? server.tools_count : 0;
        const toggleOnClasses = 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500';
        const toggleOffClasses = 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600';
        const knobOnClasses = 'translate-x-4';
        const knobOffClasses = 'translate-x-0';
        const toggleClasses = enabled ? toggleOnClasses : toggleOffClasses;
        const knobClasses = enabled ? knobOnClasses : knobOffClasses;
        return `
            <div class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 flex flex-col">
                <div class="flex items-start justify-between mb-3">
                    <div>
                        <div class="text-base font-semibold text-gray-900 dark:text-gray-100">${escapeHtml(String(name))}</div>
                        ${type ? `
                            <div class="mt-1 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
                                ${escapeHtml(String(type))}
                            </div>
                        ` : ''}
                        <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                            ${escapeHtml(String(id))}
                        </div>
                    </div>
                    <div class="flex items-start space-x-2">
                        <button
                            type="button"
                            class="ml-2 relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none ${toggleClasses}"
                            aria-pressed="${enabled ? 'true' : 'false'}"
                            data-mcp-id="${escapeHtml(String(id))}"
                            aria-label="${window.i18n ? window.i18n.t('plugin.mcp_toggle_label') : 'Enable MCP server'}"
                        >
                            <span class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${knobClasses}"></span>
                        </button>
                    </div>
                </div>
                ${description ? `
                    <p class="text-sm text-gray-600 dark:text-gray-300 line-clamp-3 mb-3" title="${escapeHtml(String(description))}">
                        ${escapeHtml(String(description))}
                    </p>
                ` : ''}
                <div class="mt-2 text-xs text-gray-500 dark:text-gray-400">
                    ${window.i18n ? window.i18n.t('plugin.mcp_tools_label') : 'Tools'}: ${toolsCount}
                </div>
                <div class="mt-4 flex items-center justify-end space-x-3 mt-auto">
                    <button
                        type="button"
                        class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
                        data-mcp-edit-id="${escapeHtml(String(id))}"
                        data-i18n="plugin.mcp_edit"
                    >
                        Edit
                    </button>
                    <button
                        type="button"
                        class="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30"
                        data-mcp-delete-id="${escapeHtml(String(id))}"
                        data-i18n="plugin.mcp_delete"
                    >
                        Delete
                    </button>
                </div>
            </div>
        `;
    }).join('');
    container.innerHTML = `
        <div class="flex items-center justify-start mb-4">
            <button
                type="button"
                id="mcp-add-button"
                class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            >
                <span class="mr-1">+</span>
                <span data-i18n="plugin.mcp_add">Add MCP server</span>
            </button>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-3 gap-4">
            ${cards}
        </div>
    `;
    attachMcpHandlers();
    if (window.i18n) {
        updateTranslations();
    }
}

// ---------------------------------------------------------------------------
// Toggle handlers
// ---------------------------------------------------------------------------

async function togglePluginEnabled(button) {
    const pluginId = button.getAttribute('data-plugin-id') || '';
    if (!pluginId) {
        return;
    }
    const isOn = button.getAttribute('aria-pressed') === 'true';
    const nextState = !isOn;

    // Save original UI state for rollback
    const origAriaPressed = button.getAttribute('aria-pressed');
    const origButtonClass = button.className;
    const knob = button.querySelector('span');
    const origKnobClass = knob ? knob.className : null;
    const origDisabled = button.disabled;
    const origAriaDisabled = button.getAttribute('aria-disabled');

    // Optimistically update UI
    button.setAttribute('aria-pressed', nextState ? 'true' : 'false');
    const baseClasses = 'ml-2 relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none';
    const onClasses = 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500';
    const offClasses = 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600';
    button.className = `${baseClasses} ${nextState ? onClasses : offClasses}`;
    if (knob) {
        knob.className = `pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${nextState ? 'translate-x-4' : 'translate-x-0'}`;
    }

    // Disable button during API call
    button.disabled = true;
    button.setAttribute('aria-disabled', 'true');

    try {
        const response = await apiCall(`/api/plugins/${encodeURIComponent(pluginId)}/enabled`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ enabled: nextState })
        });
        if (!response.ok) {
            throw new Error(`Failed to update plugin state: ${response.status}`);
        }
        // Sync local state so subsequent reads see the updated value
        if (AppState.data.plugins) {
            const plugin = AppState.data.plugins.find(p => p.id === pluginId || p.name === pluginId);
            if (plugin) {
                plugin.enabled = nextState;
            }
        }
    } catch (error) {
        console.error('Error updating plugin state:', error);
        // Rollback UI to original state
        button.setAttribute('aria-pressed', origAriaPressed);
        button.className = origButtonClass;
        if (knob && origKnobClass !== null) {
            knob.className = origKnobClass;
        }
        showNotification(getTranslation('plugin.toggle_error', 'Failed to update plugin state'), 'error');
    } finally {
        button.disabled = origDisabled;
        if (origAriaDisabled === null) {
            button.removeAttribute('aria-disabled');
        } else {
            button.setAttribute('aria-disabled', origAriaDisabled);
        }
    }
}

async function toggleMcpEnabled(button) {
    const serverId = button.getAttribute('data-mcp-id') || '';
    if (!serverId) {
        return;
    }
    const isOn = button.getAttribute('aria-pressed') === 'true';
    const nextState = !isOn;

    const origAriaPressed = button.getAttribute('aria-pressed');
    const origButtonClass = button.className;
    const knob = button.querySelector('span');
    const origKnobClass = knob ? knob.className : null;
    const origDisabled = button.disabled;
    const origAriaDisabled = button.getAttribute('aria-disabled');

    button.setAttribute('aria-pressed', nextState ? 'true' : 'false');
    const baseClasses = 'ml-2 relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none';
    const onClasses = 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500';
    const offClasses = 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600';
    button.className = `${baseClasses} ${nextState ? onClasses : offClasses}`;
    if (knob) {
        knob.className = `pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${nextState ? 'translate-x-4' : 'translate-x-0'}`;
    }

    button.disabled = true;
    button.setAttribute('aria-disabled', 'true');

    try {
        const response = await apiCall(`/api/mcp-servers/${encodeURIComponent(serverId)}/enabled`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ enabled: nextState })
        });
        if (!response.ok) {
            throw new Error(`Failed to update MCP server state: ${response.status}`);
        }
        if (AppState.data.mcpServers) {
            const server = AppState.data.mcpServers.find(s => s.id === serverId || s.name === serverId);
            if (server) {
                server.enabled = nextState;
            }
        }
        await loadMcpServers();
    } catch (error) {
        console.error('Error updating MCP server state:', error);
        button.setAttribute('aria-pressed', origAriaPressed);
        button.className = origButtonClass;
        if (knob && origKnobClass !== null) {
            knob.className = origKnobClass;
        }
        if (window.i18n) {
            showNotification(window.i18n.t('plugin.mcp_toggle_error'), 'error');
        } else {
            showNotification('Failed to update MCP server state', 'error');
        }
    } finally {
        button.disabled = origDisabled;
        if (origAriaDisabled !== null) {
            button.setAttribute('aria-disabled', origAriaDisabled);
        } else {
            button.removeAttribute('aria-disabled');
        }
    }
}

// ---------------------------------------------------------------------------
// Event handler attachment
// ---------------------------------------------------------------------------

/** Attach click handlers to MCP server action buttons after list render */
function attachMcpHandlers() {
    const container = document.getElementById('plugin-mcp');
    if (!container) {
        return;
    }
    const addButton = container.querySelector('#mcp-add-button');
    if (addButton) {
        addButton.addEventListener('click', (e) => {
            e.preventDefault();
            openMcpCreateModal();
        });
    }
    container.querySelectorAll('button[data-mcp-id]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            toggleMcpEnabled(btn);
        });
    });
    container.querySelectorAll('button[data-mcp-edit-id]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const serverId = btn.getAttribute('data-mcp-edit-id') || '';
            if (serverId) {
                openMcpConfigEditor(serverId);
            }
        });
    });
    container.querySelectorAll('button[data-mcp-delete-id]').forEach((btn) => {
        btn.addEventListener('click', async (e) => {
            e.preventDefault();
            const serverId = btn.getAttribute('data-mcp-delete-id') || '';
            if (!serverId) {
                return;
            }
            try {
                const response = await apiCall(`/api/mcp-servers/${encodeURIComponent(serverId)}`, {
                    method: 'DELETE'
                });
                if (!response.ok) {
                    throw new Error(`Failed to delete MCP server: ${response.status}`);
                }
                AppState.data.mcpServers = (AppState.data.mcpServers || []).filter(s => s.id !== serverId);
                renderMcpServers();
                showNotification(window.i18n ? window.i18n.t('plugin.mcp_delete_success') : 'MCP server deleted', 'success');
            } catch (error) {
                console.error('Error deleting MCP server:', error);
                showNotification(window.i18n ? window.i18n.t('plugin.mcp_delete_error') : 'Failed to delete MCP server', 'error');
            }
        });
    });
}

/** Attach click handlers to plugin toggle and configure buttons after list render */
function attachPluginToggleHandlers() {
    const container = document.getElementById('plugin-list');
    if (!container) {
        return;
    }
    const addButton = container.querySelector('#plugin-add-button');
    if (addButton) {
        addButton.addEventListener('click', (e) => {
            e.preventDefault();
            openPluginInstallModal();
        });
    }
    container.querySelectorAll('button[data-plugin-id]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            togglePluginEnabled(btn);
        });
    });
    container.querySelectorAll('button[data-plugin-config-id]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const pluginId = btn.getAttribute('data-plugin-config-id') || '';
            if (pluginId) {
                openPluginConfigModal(pluginId);
            }
        });
    });
}

// ---------------------------------------------------------------------------
// Plugin config modal
// ---------------------------------------------------------------------------

async function openPluginConfigModal(pluginId) {
    if (!pluginId) {
        return;
    }
    const modal = document.getElementById('plugin-config-modal');
    const container = document.getElementById('plugin-config-container');
    const titleElement = document.getElementById('plugin-config-modal-title');
    if (!modal || !container) {
        return;
    }
    PluginConfigModalState.pluginId = pluginId;
    const plugins = AppState.data.plugins || [];
    const plugin = plugins.find((p) => p.id === pluginId);
    if (titleElement && plugin) {
        titleElement.textContent = plugin.name || plugin.id || '';
    }
    container.innerHTML = '';
    Modal.show('plugin-config-modal');
    try {
        const response = await apiCall(`/api/plugins/${encodeURIComponent(pluginId)}/config`);
        if (!response.ok) {
            showNotification('Failed to load plugin config', 'error');
            return;
        }
        const data = await response.json();
        const schema = data && data.schema ? data.schema : {};
        const config = data && data.config ? data.config : {};
        renderConfigFields(schema, container, config);
    } catch (error) {
        console.error('Error loading plugin config:', error);
        showNotification('Failed to load plugin config', 'error');
    }
}

function closePluginConfigModal() {
    Modal.hide('plugin-config-modal', () => {
        const container = document.getElementById('plugin-config-container');
        if (container) container.innerHTML = '';
        PluginConfigModalState.pluginId = null;
    });
}

async function savePluginConfig() {
    if (!PluginConfigModalState.pluginId) {
        return;
    }
    const container = document.getElementById('plugin-config-container');
    const config = collectConfigFromContainer(container);
    try {
        const response = await apiCall(`/api/plugins/${encodeURIComponent(PluginConfigModalState.pluginId)}/config`, {
            method: 'PUT',
            body: JSON.stringify({ config: config })
        });
        if (!response.ok) {
            showNotification(window.i18n ? window.i18n.t('plugin.config_save_failed') : 'Failed to save plugin config', 'error');
            return;
        }
        closePluginConfigModal();
        showNotification(window.i18n ? window.i18n.t('plugin.config_saved') : 'Plugin configuration saved', 'success');
    } catch (error) {
        console.error('Error saving plugin config:', error);
        showNotification(window.i18n ? window.i18n.t('plugin.config_save_failed') : 'Failed to save plugin config', 'error');
    }
}

// ---------------------------------------------------------------------------
// Plugin delete
// ---------------------------------------------------------------------------

function deletePlugin(pluginId) {
    if (!pluginId) return;
    const title = window.i18n ? window.i18n.t('plugin.delete_confirm_title') : 'Uninstall Plugin';
    const message = window.i18n ? window.i18n.t('plugin.delete_confirm_message') : 'Are you sure you want to uninstall this plugin? The plugin files will be permanently deleted.';
    openDeleteModal(title, message, async () => {
        try {
            const response = await apiCall(`/api/plugins/${encodeURIComponent(pluginId)}`, { method: 'DELETE' });
            if (response.ok) {
                closeDeleteModal();
                await loadPluginData();
                showNotification(window.i18n ? window.i18n.t('plugin.delete_success') : 'Plugin uninstalled successfully', 'success');
            } else {
                const data = await response.json().catch(() => ({}));
                showNotification(data.detail || (window.i18n ? window.i18n.t('plugin.delete_failed') : 'Failed to uninstall plugin'), 'error');
                closeDeleteModal();
            }
        } catch (error) {
            console.error('Error deleting plugin:', error);
            showNotification(window.i18n ? window.i18n.t('plugin.delete_failed') : 'Failed to uninstall plugin', 'error');
            closeDeleteModal();
        }
    });
}

// ---------------------------------------------------------------------------
// Plugin install modal
// ---------------------------------------------------------------------------

const PluginInstallModalState = { tab: 'github', installing: false };

function openPluginInstallModal() {
    const urlInput = document.getElementById('install-github-url');
    const proxyInput = document.getElementById('install-gh-proxy');
    const btn = document.getElementById('install-submit-btn');
    if (urlInput) urlInput.value = '';
    if (proxyInput) proxyInput.value = '';
    if (btn) {
        btn.disabled = false;
        btn.setAttribute('data-i18n', 'plugin.install_btn');
        if (window.i18n) btn.textContent = window.i18n.t('plugin.install_btn');
        else btn.textContent = 'Install';
    }
    PluginInstallModalState.installing = false;
    if (!_zipDropzone) {
        _zipDropzone = new FileDropzone('install-zip-dropzone', {
            inputId: 'install-zip-input',
            titleKey: 'plugin.install_upload_hint',
            titleFallback: 'Drop a .zip file here or click to select',
            reselectKey: 'plugin.install_upload_reselect',
            reselectFallback: 'Click or drag to reselect',
        });
    } else {
        _zipDropzone.reset();
    }
    switchPluginInstallTab('github');
    Modal.show('plugin-install-modal');
}

function closePluginInstallModal() {
    Modal.hide('plugin-install-modal', () => {
        PluginInstallModalState.tab = 'github';
        PluginInstallModalState.installing = false;
    });
}

function switchPluginInstallTab(tab) {
    PluginInstallModalState.tab = tab;
    const githubContent = document.getElementById('install-tab-github');
    const uploadContent = document.getElementById('install-tab-upload');
    const githubBtn = document.getElementById('install-tab-github-btn');
    const uploadBtn = document.getElementById('install-tab-upload-btn');
    const activeClasses = ['border-blue-600', 'dark:border-blue-500', 'text-blue-600', 'dark:text-blue-500'];
    const inactiveClasses = ['border-transparent', 'text-gray-500', 'dark:text-gray-400'];
    if (tab === 'github') {
        if (githubContent) githubContent.classList.remove('hidden');
        if (uploadContent) uploadContent.classList.add('hidden');
        if (githubBtn) { githubBtn.classList.add(...activeClasses); githubBtn.classList.remove(...inactiveClasses); }
        if (uploadBtn) { uploadBtn.classList.remove(...activeClasses); uploadBtn.classList.add(...inactiveClasses); }
    } else {
        if (githubContent) githubContent.classList.add('hidden');
        if (uploadContent) uploadContent.classList.remove('hidden');
        if (uploadBtn) { uploadBtn.classList.add(...activeClasses); uploadBtn.classList.remove(...inactiveClasses); }
        if (githubBtn) { githubBtn.classList.remove(...activeClasses); githubBtn.classList.add(...inactiveClasses); }
    }
}

let _zipDropzone = null;

async function installPlugin() {
    if (PluginInstallModalState.installing) return;
    const btn = document.getElementById('install-submit-btn');
    const setLoading = (loading) => {
        PluginInstallModalState.installing = loading;
        if (!btn) return;
        btn.disabled = loading;
        btn.removeAttribute('data-i18n');
        if (loading) {
            btn.textContent = window.i18n ? window.i18n.t('plugin.install_installing') : 'Installing...';
        } else {
            btn.setAttribute('data-i18n', 'plugin.install_btn');
            btn.textContent = window.i18n ? window.i18n.t('plugin.install_btn') : 'Install';
        }
    };
    setLoading(true);
    try {
        let response;
        if (PluginInstallModalState.tab === 'github') {
            const repoUrl = (document.getElementById('install-github-url')?.value || '').trim();
            const ghProxy = (document.getElementById('install-gh-proxy')?.value || '').trim();
            if (!repoUrl) {
                showNotification(window.i18n ? window.i18n.t('plugin.install_url_required') : 'Repository URL is required', 'error');
                setLoading(false);
                return;
            }
            response = await apiCall('/api/plugins/install/github', {
                method: 'POST',
                body: JSON.stringify({ repo_url: repoUrl, gh_proxy: ghProxy || null })
            });
        } else {
            const zipFile = _zipDropzone?.getFile();
            if (!zipFile) {
                showNotification(window.i18n ? window.i18n.t('plugin.install_no_file') : 'Please select a .zip file', 'error');
                setLoading(false);
                return;
            }
            const formData = new FormData();
            formData.append('file', zipFile);
            response = await apiCall('/api/plugins/install/upload', {
                method: 'POST',
                body: formData
            });
        }
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            const msg = data.detail || `HTTP ${response.status}`;
            showNotification(`${window.i18n ? window.i18n.t('plugin.install_failed') : 'Installation failed'}: ${msg}`, 'error');
            setLoading(false);
            return;
        }
        const result = await response.json();
        closePluginInstallModal();
        await loadPluginData();
        if (result.warnings && result.warnings.length) {
            showNotification(`${window.i18n ? window.i18n.t('plugin.install_warning') : 'Installed with warnings'}: ${result.warnings.join('; ')}`, 'warning');
        } else {
            showNotification(window.i18n ? window.i18n.t('plugin.install_success') : 'Plugin installed successfully', 'success');
        }
    } catch (error) {
        console.error('Error installing plugin:', error);
        showNotification(window.i18n ? window.i18n.t('plugin.install_failed') : 'Installation failed', 'error');
        setLoading(false);
    }
}

// ---------------------------------------------------------------------------
// MCP config editor modal
// ---------------------------------------------------------------------------

async function openMcpConfigEditor(serverId) {
    try {
        const response = await apiCall(`/api/mcp-servers/${encodeURIComponent(serverId)}/config`);
        if (!response.ok) {
            throw new Error(`Failed to load MCP config: ${response.status}`);
        }
        const data = await response.json();
        const modal = document.getElementById('mcp-config-modal');
        const subtitle = document.getElementById('mcp-modal-subtitle');
        const nameInput = document.getElementById('mcp-server-name-input');
        const descInput = document.getElementById('mcp-server-description-input');
        if (!modal || !nameInput) {
            return;
        }
        mcpEditorState.serverId = serverId;
        mcpEditorState.mode = 'edit';
        if (subtitle) {
            subtitle.textContent = '';
        }
        nameInput.value = data.name || serverId;
        if (descInput) {
            descInput.value = data.description || '';
        }

        await Monaco.waitForMonaco();

        const container = document.getElementById('mcp-editor-container');
        if (!container) {
            return;
        }
        const editorValue = data.config ? JSON.stringify(data.config, null, 4) : '';
        Monaco.register('mcp', container, 'json', editorValue, {
            fontSize: 13,
            bracketPairColorization: { enabled: true },
        });

        Modal.show('mcp-config-modal');
    } catch (error) {
        console.error('Error loading MCP config:', error);
        showNotification('Failed to load MCP config', 'error');
    }
}

async function openMcpCreateModal() {
    const modal = document.getElementById('mcp-config-modal');
    const subtitle = document.getElementById('mcp-modal-subtitle');
    const nameInput = document.getElementById('mcp-server-name-input');
    const descInput = document.getElementById('mcp-server-description-input');
    if (!modal || !nameInput) {
        return;
    }
    mcpEditorState.serverId = null;
    mcpEditorState.mode = 'create';
    if (subtitle) {
        subtitle.textContent = '';
    }
    nameInput.value = '';
    if (descInput) {
        descInput.value = '';
    }

    await Monaco.waitForMonaco();

    const container = document.getElementById('mcp-editor-container');
    if (!container) {
        return;
    }

    const template = JSON.stringify({
        type: "streamable_http",
        url: "",
        headers: {}
    }, null, 4);

    Monaco.register('mcp', container, 'json', template, {
        fontSize: 13,
        bracketPairColorization: { enabled: true },
    });

    Modal.show('mcp-config-modal');
}

function closeMcpConfigModal() {
    Modal.hide('mcp-config-modal', () => {
        Monaco.dispose('mcp');
        mcpEditorState.serverId = null;
        mcpEditorState.mode = 'edit';
    });
}

async function saveMcpConfig() {
    const nameInput = document.getElementById('mcp-server-name-input');
    const descInput = document.getElementById('mcp-server-description-input');
    const nameValue = nameInput ? (nameInput.value || '').trim() : '';
    if (!nameValue) {
        showNotification('Server name is required', 'error');
        return;
    }
    const descriptionValue = descInput ? (descInput.value || '') : '';

    if (!Monaco.get('mcp')) {
        return;
    }
    const content = Monaco.getValue('mcp');
    try {
        JSON.parse(content);
    } catch (e) {
        showNotification('Invalid JSON in MCP config', 'error');
        return;
    }
    const isCreate = mcpEditorState.mode === 'create' || !mcpEditorState.serverId;
    try {
        let response;
        if (isCreate) {
            response = await apiCall('/api/mcp-servers', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    name: nameValue,
                    description: descriptionValue,
                    config: content
                })
            });
        } else {
            const serverId = mcpEditorState.serverId;
            response = await apiCall(`/api/mcp-servers/${encodeURIComponent(serverId)}/config`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    name: nameValue,
                    description: descriptionValue,
                    config: content
                })
            });
        }
        if (!response.ok) {
            throw new Error(`Failed to save MCP config: ${response.status}`);
        }
        closeMcpConfigModal();
        await loadMcpServers();
        showNotification(isCreate ? 'MCP server created' : 'MCP config saved', 'success');
    } catch (error) {
        console.error('Error saving MCP config:', error);
        showNotification('Failed to save MCP config', 'error');
    }
}

// ---------------------------------------------------------------------------
// Plugin / MCP tab setup
// ---------------------------------------------------------------------------

/**
 * Initialize plugin page tabs (Plugins / MCP Servers).
 * Idempotent — skips if already initialized.
 */
function setupPluginTabs() {
    if (AppState.pluginTabsInitialized) {
        return;
    }
    const tabPlugins = document.getElementById('plugin-tab-plugins');
    const tabMcp = document.getElementById('plugin-tab-mcp');
    const pluginList = document.getElementById('plugin-list');
    const mcpContainer = document.getElementById('plugin-mcp');
    if (!tabPlugins || !tabMcp || !pluginList || !mcpContainer) {
        return;
    }
    const activateTab = (tab) => {
        AppState.pluginTab = tab;
        const isPlugins = tab === 'plugins';
        if (isPlugins) {
            tabPlugins.classList.add('border-blue-600', 'dark:border-blue-500', 'text-blue-600', 'dark:text-blue-500');
            tabPlugins.classList.remove('border-transparent', 'text-gray-500', 'dark:text-gray-400');
            tabMcp.classList.remove('border-blue-600', 'dark:border-blue-500', 'text-blue-600', 'dark:text-blue-500');
            tabMcp.classList.add('border-transparent', 'text-gray-500', 'dark:text-gray-400');
        } else {
            tabMcp.classList.add('border-blue-600', 'dark:border-blue-500', 'text-blue-600', 'dark:text-blue-500');
            tabMcp.classList.remove('border-transparent', 'text-gray-500', 'dark:text-gray-400');
            tabPlugins.classList.remove('border-blue-600', 'dark:border-blue-500', 'text-blue-600', 'dark:text-blue-500');
            tabPlugins.classList.add('border-transparent', 'text-gray-500', 'dark:text-gray-400');
        }
        if (isPlugins) {
            pluginList.classList.remove('hidden');
            mcpContainer.classList.add('hidden');
        } else {
            pluginList.classList.add('hidden');
            mcpContainer.classList.remove('hidden');
        }
    };
    tabPlugins.addEventListener('click', (e) => {
        e.preventDefault();
        activateTab('plugins');
        loadPluginData();
    });
    tabMcp.addEventListener('click', (e) => {
        e.preventDefault();
        activateTab('mcp');
        loadMcpServers();
    });
    const initialTab = AppState.pluginTab || 'plugins';
    activateTab(initialTab);
    if (initialTab === 'plugins') {
        loadPluginData();
    } else {
        loadMcpServers();
    }
    AppState.pluginTabsInitialized = true;
}
