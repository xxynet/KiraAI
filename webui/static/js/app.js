/**
 * Main application JavaScript for KiraAI Admin Panel
 * Handles page navigation, API interactions, and data updates
 *
 * Extracted modules (loaded via index.html <script> tags before this file):
 *   core/state.js          — AppState
 *   core/api.js            — apiCall
 *   core/notify.js         — showNotification
 *   shared/render-config-fields.js — renderConfigFields, collectConfigFromContainer,
 *                                    initConfigMonacoEditor, validateConfigFieldInput
 */

/**
 * Initialize the application
 */
document.addEventListener('DOMContentLoaded', () => {
    initializeApp();
});

/**
 * Initialize application components
 */
function initializeApp() {
    // Apply saved theme from localStorage before anything else
    const savedTheme = localStorage.getItem('theme') || 'light';
    applyTheme(savedTheme);

    setupThemeToggle();
    setupNavigation();
    loadAppVersion();
    loadInitialData();
    setupEventListeners();
    startAutoRefresh();
    initializeMonacoEditor();
    initializeDropzones();
}

function setupThemeToggle() {
    const button = document.getElementById('theme-toggle-button');
    const iconPath = document.getElementById('theme-toggle-icon-path');
    if (!button || !iconPath) {
        return;
    }

    const updateIcon = (theme) => {
        if (theme === 'dark') {
            iconPath.setAttribute(
                'd',
                'M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z'
            );
        } else {
            iconPath.setAttribute(
                'd',
                'M12 3v2.25M18.364 5.636l-1.59 1.59M21 12h-2.25M18.364 18.364l-1.59-1.59M12 18.75V21M7.227 16.773l-1.59 1.59M5.25 12H3M7.227 7.227l-1.59-1.59M12 8.25A3.75 3.75 0 1015.75 12 3.75 3.75 0 0012 8.25z'
            );
        }
    };

    const currentTheme = localStorage.getItem('theme') || 'light';
    updateIcon(currentTheme);

    button.addEventListener('click', () => {
        const theme = document.documentElement.classList.contains('dark') ? 'light' : 'dark';
        applyTheme(theme);
        updateIcon(theme);
    });
}

/**
 * Setup navigation between pages
 */
function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const page = item.getAttribute('data-page');
            switchPage(page);
        });
    });
    
    // Set initial page
    switchPage('overview');
}

/**
 * Switch to a different page
 * @param {string} pageName - Name of the page to switch to
 */
function switchPage(pageName) {
    // Close SSE connection when leaving logs page
    if (AppState.currentPage === 'logs' && pageName !== 'logs') {
        if (AppState.sseEventSource) {
            AppState.sseEventSource.close();
            AppState.sseEventSource = null;
        }
    }
    
    // Update navigation active state
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active', 'bg-blue-600');
        if (item.getAttribute('data-page') === pageName) {
            item.classList.add('active', 'bg-blue-600');
        }
    });
    
    // Hide all pages
    document.querySelectorAll('.page-content').forEach(page => {
        page.classList.add('hidden');
    });
    
    // Show selected page
    const targetPage = document.getElementById(`page-${pageName}`);
    if (targetPage) {
        targetPage.classList.remove('hidden');
    }
    
    // Update page title
    const pageTitle = document.getElementById('page-title');
    if (pageTitle && window.i18n) {
        pageTitle.setAttribute('data-i18n', `pages.${pageName}.title`);
        pageTitle.textContent = window.i18n.t(`pages.${pageName}.title`);
    }
    
    // Update app state
    AppState.currentPage = pageName;
    
    // Load page-specific data
    loadPageData(pageName);
}

/**
 * Load data for a specific page
 * @param {string} pageName - Name of the page
 */
async function loadPageData(pageName) {
    try {
        switch (pageName) {
            case 'overview':
                await loadOverviewData();
                break;
            case 'provider':
                await loadProviderData();
                break;
            case 'adapter':
                await loadAdapterData();
                break;
            case 'persona':
                await loadPersonaData();
                break;
            case 'plugin':
                setupPluginTabs();
                break;
            case 'sticker':
                await loadStickerData();
                break;
            case 'configuration':
                await loadConfigurationData();
                break;
            case 'sessions':
                await loadSessionsData();
                break;
            case 'logs':
                await loadLogsData();
                break;
            case 'settings':
                await loadSettingsData();
                break;
        }
    } catch (error) {
        console.error(`Error loading ${pageName} data:`, error);
        showNotification('Error loading data', 'error');
    }
}

/**
 * Load initial data on app start
 */
async function loadInitialData() {
    await loadPageData(AppState.currentPage);
}

async function loadAppVersion() {
    try {
        const response = await apiCall('/api/version');
        const data = await response.json();
        const element = document.getElementById('app-version');
        if (element && data && data.version) {
            element.textContent = data.version;
        }
    } catch (error) {
        console.error('Error loading version:', error);
    }
}

// loadOverviewData → modules/overview.js

/**
 * Load provider data
 */
async function loadProviderData() {
    try {
        const response = await apiCall('/api/providers');
        const data = await response.json();
        AppState.data.providers = Array.isArray(data) ? data : (data.providers || []);
        
        renderProviderList();
    } catch (error) {
        console.error('Error loading provider data:', error);
    }
}

/**
 * Render provider list
 */
function renderProviderList() {
    const container = document.getElementById('provider-list');
    if (!container) return;
    
    if (AppState.data.providers.length === 0) {
        container.innerHTML = `
            <div class="flex justify-center items-center py-12">
                <div class="text-center">
                    <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"></path>
                    </svg>
                    <p class="text-gray-500 text-sm" data-i18n="provider.no_providers">No providers configured</p>
                </div>
            </div>
        `;
        if (window.i18n) {
            updateTranslations();
        }
        return;
    }
    
    const listItems = AppState.data.providers.map(provider => `
        <div class="provider-item flex items-center p-3 rounded-lg cursor-pointer transition-colors hover:bg-gray-100 ${AppState.selectedProviderId === provider.id ? 'bg-blue-50 border border-blue-200' : 'border border-transparent'}" 
             onclick="selectProvider('${provider.id}')" 
             data-provider-id="${provider.id}">
            <div class="mr-3">
                <svg class="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"></path>
                </svg>
            </div>
            <div class="flex-1">
                <div class="text-sm font-medium text-gray-900">${escapeHtml(provider.name || 'N/A')}</div>
                <div class="text-xs text-gray-500">${escapeHtml(provider.type || 'N/A')}</div>
            </div>
            <div class="flex items-center space-x-2">
                <span class="px-2 py-1 text-xs rounded-full ${
                    provider.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
                }">
                    ${provider.status === 'active' ? 'Active' : 'Inactive'}
                </span>
            </div>
        </div>
    `).join('');
    
    container.innerHTML = listItems;
}

/**
 * Load adapter data
 */
async function loadAdapterData() {
    try {
        const response = await apiCall('/api/adapters');
        const data = await response.json();
        AppState.data.adapters = Array.isArray(data) ? data : (data.adapters || []);
        
        renderAdapterList();
    } catch (error) {
        console.error('Error loading adapter data:', error);
    }
}

/**
 * Render adapter list
 */
function renderAdapterList() {
    const container = document.getElementById('adapter-list');
    if (!container) return;
    
    if (AppState.data.adapters.length === 0) {
        container.innerHTML = `
            <div class="flex justify-center items-center py-12">
                <div class="text-center">
                    <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                    </svg>
                    <p class="text-gray-500" data-i18n="adapter.no_adapters">No adapters configured</p>
                </div>
            </div>
        `;
        if (window.i18n) {
            updateTranslations();
        }
        return;
    }
    
    const cards = `
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            ${AppState.data.adapters.map(adapter => {
                const id = adapter.id || '';
                const name = escapeHtml(adapter.name || 'N/A');
                const platform = escapeHtml(adapter.platform || 'N/A');
                const isActive = adapter.status === 'active';
                const statusLabel = isActive ? 'Active' : 'Inactive';
                const statusColor = isActive ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800';
                const switchBg = isActive ? 'bg-green-500' : 'bg-gray-300';
                const switchTranslate = isActive ? 'translate-x-5' : 'translate-x-0';
                return `
                    <div class="bg-white dark:bg-gray-900 rounded-lg shadow p-5 flex flex-col justify-between">
                        <div class="flex items-start justify-between mb-4">
                            <div>
                                <div class="flex items-center">
                                    <h4 class="text-base font-semibold text-gray-900 dark:text-gray-100 mr-2">${name}</h4>
                                    <span class="px-2 py-0.5 text-xs rounded-full ${statusColor}">
                                        ${escapeHtml(adapter.status || statusLabel)}
                                    </span>
                                </div>
                                <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
                                    ${platform}
                                </p>
                            </div>
                            <button
                                type="button"
                                class="flex items-center focus:outline-none"
                                onclick="toggleAdapterActive('${id}')"
                            >
                                <span class="mr-2 text-xs text-gray-500 dark:text-gray-400">
                                    ${isActive ? 'On' : 'Off'}
                                </span>
                                <span class="relative inline-flex items-center h-5 w-9 rounded-full ${switchBg} transition-colors">
                                    <span class="inline-block h-4 w-4 bg-white rounded-full shadow transform ${switchTranslate} transition-transform"></span>
                                </span>
                            </button>
                        </div>
                        <div class="flex justify-end space-x-3 mt-4">
                            <button
                                class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
                                data-i18n="adapter.edit"
                                onclick="editAdapter('${id}')"
                            >
                                ${getTranslation('adapter.edit', 'Edit')}
                            </button>
                            <button
                                class="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30"
                                data-i18n="adapter.delete"
                                onclick="deleteAdapter('${id}')"
                            >
                                ${getTranslation('adapter.delete', 'Delete')}
                            </button>
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
    `;
    
    container.innerHTML = cards;
    if (window.i18n) {
        updateTranslations();
    }
}

async function toggleAdapterActive(id) {
    if (!id) {
        return;
    }

    const adapter = AppState.data.adapters.find(a => a.id === id);
    if (!adapter) {
        return;
    }

    const newStatus = adapter.status === 'active' ? 'inactive' : 'active';

    try {
        const payload = {
            name: adapter.name,
            platform: adapter.platform,
            status: newStatus,
            config: adapter.config || {}
        };
        await apiCall(`/api/adapters/${encodeURIComponent(id)}`, {
            method: 'PUT',
            body: JSON.stringify(payload)
        });

        adapter.status = newStatus;
        renderAdapterList();
        showNotification(window.i18n ? window.i18n.t('adapter.status_updated') : 'Adapter status updated', 'success');
    } catch (error) {
        console.error('Error toggling adapter status:', error);
        showNotification(window.i18n ? window.i18n.t('adapter.status_update_failed') : 'Failed to update adapter status', 'error');
    }
}

const AdapterModalState = {
    mode: 'create',
    adapterId: null
};

const PluginConfigModalState = {
    pluginId: null
};

async function fetchAdapterSchema(platform) {
    try {
        const response = await apiCall(`/api/adapters/schema/${encodeURIComponent(platform)}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch schema: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching adapter schema:', error);
        showNotification(window.i18n ? window.i18n.t('adapter.schema_load_failed') : 'Failed to load adapter schema', 'error');
        return null;
    }
}

async function loadAdapterSchema(platform, currentValues = {}) {
    const schema = await fetchAdapterSchema(platform);
    if (schema) {
        renderConfigFields(schema, 'adapter-config-container', currentValues);
    }
}

// renderConfigFields, initConfigMonacoEditor → shared/render-config-fields.js

async function openAdapterModal(adapter) {
    const modal = document.getElementById('adapter-modal');
    if (!modal) return;

    AdapterModalState.mode = adapter ? 'edit' : 'create';
    AdapterModalState.adapterId = adapter ? adapter.id : null;

    const title = modal.querySelector('[data-i18n="adapter.modal_title"]');
    if (title) {
        title.textContent = AdapterModalState.mode === 'edit' ? 'Edit Adapter' : 'Add Adapter';
    }

    const nameInput = document.getElementById('adapter-name');
    const descInput = document.getElementById('adapter-desc');
    const platformSelect = document.getElementById('adapter-platform');
    const statusSelect = document.getElementById('adapter-status');
    const configContainer = document.getElementById('adapter-config-container');
    const statusLabel = document.getElementById('adapter-status-label');
    const statusSwitch = document.getElementById('adapter-status-switch');

    if (nameInput) {
        nameInput.value = adapter ? (adapter.name || '') : '';
    }
    if (descInput) {
        descInput.value = adapter ? (adapter.description || '') : '';
    }
    if (statusSelect) {
        statusSelect.value = adapter && adapter.status === 'active' ? 'active' : 'inactive';
    }
    if (statusLabel && statusSwitch && statusSelect) {
        const isActive = statusSelect.value === 'active';
        statusLabel.textContent = isActive ? 'On' : 'Off';
        statusSwitch.className = `relative inline-flex items-center h-5 w-9 rounded-full ${isActive ? 'bg-green-500' : 'bg-gray-300'} transition-colors`;
        const knob = statusSwitch.querySelector('span');
        if (knob) {
            knob.className = `inline-block h-4 w-4 bg-white rounded-full shadow transform ${isActive ? 'translate-x-5' : 'translate-x-0'} transition-transform`;
        }
    }
    if (configContainer) {
        configContainer.innerHTML = '';
    }

    Modal.show('adapter-modal');

    if (platformSelect) {
        try {
            const response = await apiCall('/api/adapter-platforms');
            if (!response.ok) {
                throw new Error(`Failed to fetch adapter platforms: ${response.status}`);
            }
            const platforms = await response.json();
            if (!Array.isArray(platforms)) {
                throw new Error('Invalid adapter platforms response format');
            }

            const currentPlatformSelect = document.getElementById('adapter-platform');
            if (!currentPlatformSelect) return;

            const placeholderText = window.i18n ? window.i18n.t('adapter.platform_placeholder') : 'Select adapter platform...';

            currentPlatformSelect.innerHTML = '';
            const placeholderOption = document.createElement('option');
            placeholderOption.value = '';
            placeholderOption.textContent = placeholderText;
            currentPlatformSelect.appendChild(placeholderOption);

            platforms.forEach(p => {
                const option = document.createElement('option');
                option.value = p;
                option.textContent = p;
                currentPlatformSelect.appendChild(option);
            });

            if (adapter && adapter.platform) {
                currentPlatformSelect.value = adapter.platform;
                currentPlatformSelect.disabled = true;
            } else {
                currentPlatformSelect.value = '';
                currentPlatformSelect.disabled = false;
            }

            const customSelectWrapper = document.querySelector('.custom-select[data-custom-select="adapter-platform"]');
            if (customSelectWrapper) {
                customSelectWrapper.remove();
            }
            if (typeof CustomSelect !== 'undefined') {
                new CustomSelect(currentPlatformSelect, {
                    placeholder: placeholderText,
                    disabled: currentPlatformSelect.disabled
                });
            }

            if (adapter && adapter.platform) {
                if (configContainer) {
                    configContainer.innerHTML = '';
                }
                await loadAdapterSchema(adapter.platform, adapter.config || {});
            } else {
                currentPlatformSelect.onchange = async (e) => {
                    const selectedPlatform = e.target.value;
                    if (configContainer) {
                        configContainer.innerHTML = '';
                    }
                    if (selectedPlatform) {
                        await loadAdapterSchema(selectedPlatform, {});
                    }
                };
            }
        } catch (error) {
            console.error('Error fetching adapter platforms:', error);
            showNotification(window.i18n ? window.i18n.t('adapter.platform_load_failed') : 'Failed to load adapter platforms', 'error');
        }
    }
}

document.addEventListener('click', (e) => {
    const toggle = e.target.closest('#adapter-status-toggle');
    if (!toggle) return;
    const statusSelect = document.getElementById('adapter-status');
    const statusLabel = document.getElementById('adapter-status-label');
    const statusSwitch = document.getElementById('adapter-status-switch');
    if (!statusSelect || !statusLabel || !statusSwitch) return;
    const isCurrentlyActive = statusSelect.value === 'active';
    const newValue = isCurrentlyActive ? 'inactive' : 'active';
    statusSelect.value = newValue;
    const isActive = newValue === 'active';
    statusLabel.textContent = isActive ? 'On' : 'Off';
    statusSwitch.className = `relative inline-flex items-center h-5 w-9 rounded-full ${isActive ? 'bg-green-500' : 'bg-gray-300'} transition-colors`;
    const knob = statusSwitch.querySelector('span');
    if (knob) {
        knob.className = `inline-block h-4 w-4 bg-white rounded-full shadow transform ${isActive ? 'translate-x-5' : 'translate-x-0'} transition-transform`;
    }
});

function closeAdapterModal() {
    Modal.hide('adapter-modal', () => {
        AdapterModalState.mode = 'create';
        AdapterModalState.adapterId = null;
        const configContainer = document.getElementById('adapter-config-container');
        if (configContainer) configContainer.innerHTML = '';
        const platformSelect = document.getElementById('adapter-platform');
        if (platformSelect) platformSelect.disabled = false;
    });
}

async function saveAdapter() {
    const nameInput = document.getElementById('adapter-name');
    const descInput = document.getElementById('adapter-desc');
    const platformSelect = document.getElementById('adapter-platform');
    const statusSelect = document.getElementById('adapter-status');

    const name = nameInput ? nameInput.value.trim() : '';
    const description = descInput ? descInput.value.trim() : '';
    const platform = platformSelect ? platformSelect.value.trim() : '';
    const status = statusSelect ? statusSelect.value : 'inactive';

    if (!name || !platform) {
        showNotification('Name and platform are required', 'error');
        return;
    }

    const statusLabel = document.getElementById('adapter-status-label');
    const statusSwitch = document.getElementById('adapter-status-switch');
    if (statusLabel && statusSwitch && statusSelect) {
        const isActive = statusSelect.value === 'active';
        statusLabel.textContent = isActive ? 'On' : 'Off';
        statusSwitch.className = `relative inline-flex items-center h-5 w-9 rounded-full ${isActive ? 'bg-green-500' : 'bg-gray-300'} transition-colors`;
        const knob = statusSwitch.querySelector('span');
        if (knob) {
            knob.className = `inline-block h-4 w-4 bg-white rounded-full shadow transform ${isActive ? 'translate-x-5' : 'translate-x-0'} transition-transform`;
        }
    }

    const configContainer = document.getElementById('adapter-config-container');
    const config = collectConfigFromContainer(configContainer);

    const payload = {
        name: name,
        platform: platform,
        status: status,
        description: description,
        config: config
    };

    try {
        if (AdapterModalState.mode === 'edit' && AdapterModalState.adapterId) {
            const response = await apiCall(`/api/adapters/${encodeURIComponent(AdapterModalState.adapterId)}`, {
                method: 'PUT',
                body: JSON.stringify(payload)
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                showNotification(errorData.detail || (window.i18n ? window.i18n.t('adapter.update_failed') : 'Failed to update adapter'), 'error');
                return;
            }
        } else {
            const response = await apiCall('/api/adapters', {
                method: 'POST',
                body: JSON.stringify(payload)
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                showNotification(errorData.detail || (window.i18n ? window.i18n.t('adapter.create_failed') : 'Failed to create adapter'), 'error');
                return;
            }
        }

        await loadAdapterData();
        closeAdapterModal();
        showNotification(window.i18n ? window.i18n.t('adapter.saved') : 'Adapter saved successfully', 'success');
    } catch (error) {
        console.error('Error saving adapter:', error);
        showNotification(window.i18n ? window.i18n.t('adapter.save_failed') : 'Failed to save adapter', 'error');
    }
}

// collectConfigFromContainer → shared/render-config-fields.js

/**
 * Load persona data
 */
// loadPersonaData → modules/persona.js

// loadStickerData → modules/sticker.js

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

function renderPluginList() {
    const container = document.getElementById('plugin-list');
    if (!container) {
        return;
    }
    const plugins = AppState.data.plugins || [];
    if (!plugins.length) {
        container.innerHTML = `
            <div class="flex justify-center items-center py-12">
                <div class="text-center">
                    <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 4a2 2 0 114 0v1a1 1 0 001 1h3a1 1 0 011 1v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H7a1 1 0 01-1-1v-3a1 1 0 00-1-1H4a2 2 0 110-4h1a1 1 0 001-1V7a1 1 0 011-1h3a1 1 0 001-1V4z"></path>
                    </svg>
                    <p class="text-gray-500" data-i18n="plugin.no_plugins">No add-ons configured</p>
                </div>
            </div>
        `;
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
                        >
                            Uninstall
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
    container.innerHTML = `
        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-3 gap-4">
            ${cards}
        </div>
    `;
    attachPluginToggleHandlers();
    if (window.i18n) {
        updateTranslations();
    }
}

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

function attachPluginToggleHandlers() {
    const container = document.getElementById('plugin-list');
    if (!container) {
        return;
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
            showNotification('Failed to save plugin config', 'error');
            return;
        }
        closePluginConfigModal();
        showNotification('Plugin configuration saved', 'success');
    } catch (error) {
        console.error('Error saving plugin config:', error);
        showNotification('Failed to save plugin config', 'error');
    }
}

// renderStickerList, openStickerModal, closeStickerModal,
// openAddStickerModal, saveSticker, deleteSticker → modules/sticker.js

// renderDefaultPersonaCard, renderPersonaList → modules/persona.js

/**
 * Load configuration data - uses ConfigurationManager
 */
async function loadConfigurationData() {
    try {
        if (window.configManager) {
            await window.configManager.load();
            // Bind toolbar events (idempotent)
            _bindConfigToolbarEvents();
        } else {
            console.error('ConfigurationManager not loaded');
            showNotification(getTranslation('config.load_failed', 'Configuration subsystem failed to load. Please refresh the page.'), 'error');
            // Disable config controls to prevent silent failures
            const configContainer = document.getElementById('config-dynamic-container') || document.getElementById('config-container');
            if (configContainer) {
                configContainer.innerHTML = '<div class="text-center text-red-500 py-8">' + getTranslation('config.module_unavailable', 'Configuration module unavailable') + '</div>';
            }
            return;
        }
    } catch (error) {
        console.error('Error loading configuration data:', error);
        const msg = error && error.message ? error.message : String(error) || 'Unknown error';
        showNotification(getTranslation('config.load_error', 'Failed to load configuration') + ': ' + msg, 'error');
    }
}

/** Bind configuration toolbar button events */
function _bindConfigToolbarEvents() {
    const searchInput = document.getElementById('config-search-input');
    if (searchInput && searchInput.dataset.boundConfigToolbar !== '1') {
        searchInput.dataset.boundConfigToolbar = '1';
        let debounceTimer;
        searchInput.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                if (window.configManager) {
                    window.configManager.setSearch(e.target.value);
                }
            }, 150);
        });
    }

    const undoBtn = document.getElementById('config-undo-btn');
    if (undoBtn && undoBtn.dataset.boundConfigToolbar !== '1') {
        undoBtn.dataset.boundConfigToolbar = '1';
        undoBtn.addEventListener('click', () => window.configManager?.undo());
    }

    const redoBtn = document.getElementById('config-redo-btn');
    if (redoBtn && redoBtn.dataset.boundConfigToolbar !== '1') {
        redoBtn.dataset.boundConfigToolbar = '1';
        redoBtn.addEventListener('click', () => window.configManager?.redo());
    }

    const resetBtn = document.getElementById('config-reset-btn');
    if (resetBtn && resetBtn.dataset.boundConfigToolbar !== '1') {
        resetBtn.dataset.boundConfigToolbar = '1';
        resetBtn.addEventListener('click', () => window.configManager?.reset());
    }

    const expandBtn = document.getElementById('config-expand-all-btn');
    if (expandBtn && expandBtn.dataset.boundConfigToolbar !== '1') {
        expandBtn.dataset.boundConfigToolbar = '1';
        expandBtn.addEventListener('click', () => window.configManager?.expandAll());
    }

    const collapseBtn = document.getElementById('config-collapse-all-btn');
    if (collapseBtn && collapseBtn.dataset.boundConfigToolbar !== '1') {
        collapseBtn.dataset.boundConfigToolbar = '1';
        collapseBtn.addEventListener('click', () => window.configManager?.collapseAll());
    }
}

// loadSessionsData, renderSessionList → modules/session.js

/**
 * Get translation with fallback
 * @param {string} key - Translation key
 * @param {string} fallback - Fallback text if translation not available
 * @returns {string} Translated text or fallback
 */
function getTranslation(key, fallback) {
    if (window.i18n && typeof window.i18n.t === 'function') {
        try {
            const translation = window.i18n.t(key);
            return translation !== key ? translation : fallback;
        } catch (e) {
            return fallback;
        }
    }
    return fallback;
}

/**
 * Apply translations to all elements with data-i18n attribute
 */
function applyTranslations() {
    if (window.i18n && typeof window.i18n.t === 'function') {
        document.querySelectorAll('[data-i18n]').forEach(element => {
            const key = element.getAttribute('data-i18n');
            const translation = window.i18n.t(key);
            if (translation && translation !== key) {
                if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
                    element.placeholder = translation;
                } else {
                    element.textContent = translation;
                }
            }
        });
    }
}

// loadLogsData, initLogLevelSelector, initSSEConnection, setupSSEEventHandlers,
// addLogEntry, checkLogLevelMatch, applyLogFilter, renderLogs → modules/log.js

/**
 * Load settings data
 */
async function loadSettingsData() {
    try {
        const response = await apiCall('/api/settings');
        const data = await response.json();
        AppState.data.settings = data.settings || {};
        
        // Populate settings form
        const languageSelect = document.getElementById('settings-language');
        const themeSelect = document.getElementById('settings-theme');
        
        if (languageSelect && data.settings.language) {
            languageSelect.value = data.settings.language;
        }

         if (themeSelect && data.settings.theme) {
         themeSelect.value = data.settings.theme;
         }

        // Apply theme
        applyTheme(data.settings.theme || 'light');

    } catch (error) {
        console.error('Error loading settings data:', error);
    }
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Settings save button
    const saveSettingsBtn = document.getElementById('save-settings');
    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', saveSettings);
    }
    
    // Settings language change
    const settingsLanguage = document.getElementById('settings-language');
    if (settingsLanguage) {
        settingsLanguage.addEventListener('change', (e) => {
            if (window.i18n) {
                window.i18n.changeLanguage(e.target.value);
            }
        });
    }
    
    // Settings theme change
    const settingsTheme = document.getElementById('settings-theme');
    if (settingsTheme) {
        settingsTheme.addEventListener('change', (e) => {
            const theme = e.target.value;
            applyTheme(theme);
            
            // Save theme to localStorage
            localStorage.setItem('theme', theme);
            
            Monaco.syncTheme();
        });
    }
    
    // Initialize log level selector
    initLogLevelSelector();

    const logoutButton = document.getElementById('logout-button');
    if (logoutButton) {
        logoutButton.addEventListener('click', () => {
            localStorage.removeItem('jwt_token');
            window.location.href = '/login';
        });
    }
    
    document.addEventListener('click', (e) => {
        const target = e.target.closest('button');
        if (!target) return;
        if (target.id === 'configuration-save-button') {
            const configurationPage = document.getElementById('page-configuration');
            if (configurationPage && configurationPage.contains(target) && !configurationPage.classList.contains('hidden')) {
                e.preventDefault();
                if (window.configManager) {
                    window.configManager.save();
                } else {
                    // Only call legacy save if its expected form fields exist
                    const requiredLegacyFieldIds = [
                        'msg-max-memory-length',
                        'msg-max-message-interval',
                        'msg-max-buffer-messages',
                        'msg-min-message-delay',
                        'msg-max-message-delay',
                        'msg-agent-max-tool-loop',
                        'msg-selfie-path'
                    ];
                    const hasLegacyFields = requiredLegacyFieldIds.every(id => document.getElementById(id));
                    if (hasLegacyFields) {
                        showNotification(getTranslation('config.fallback_save_warning', 'Configuration manager not loaded, falling back to legacy save'), 'warning');
                        saveConfiguration();
                    } else {
                        showNotification(getTranslation('config.manager_not_loaded', 'Configuration manager not loaded'), 'warning');
                    }
                }
                return;
            }
        }
        const buttonText = target.textContent || '';
        
        // Check for session new button
        if (buttonText.includes('New Session') || buttonText.includes('新建会话')) {
            e.preventDefault();
            showNotification('New session functionality coming soon', 'info');
        }
        
        if (buttonText.includes('Clear Logs') || buttonText.includes('清除日志')) {
            e.preventDefault();
            clearLogs();
        }
        
        if (buttonText.includes('Refresh') || buttonText.includes('刷新')) {
            const logsPage = document.getElementById('page-logs');
            if (logsPage && !logsPage.classList.contains('hidden')) {
                e.preventDefault();
                refreshLogs();
            }
        }
    });
    
    // Use event delegation for Add buttons
    document.addEventListener('click', (e) => {
        // Check if clicked element is an Add button
        const target = e.target.closest('button');
        if (!target) return;
        
        // Check if button contains "Add" text or is in a page section
        const buttonText = target.textContent || '';
        const isAddButton = buttonText.includes('Add') || buttonText.includes('添加');
        
        if (isAddButton) {
            const providerPage = document.getElementById('page-provider');
            const adapterPage = document.getElementById('page-adapter');
            const personaPage = document.getElementById('page-persona');
            
            if (providerPage && providerPage.contains(target) && !providerPage.classList.contains('hidden')) {
                e.preventDefault();
                openProviderModal();
            } else if (adapterPage && adapterPage.contains(target) && !adapterPage.classList.contains('hidden')) {
                e.preventDefault();
                openAdapterModal();
            } else if (personaPage && personaPage.contains(target) && !personaPage.classList.contains('hidden')) {
                e.preventDefault();
                openPersonaModal();
            }
        }
    });
}

function initializeDropzones() {
    const stickerDropContainer = document.getElementById('sticker-dropzone');
    if (stickerDropContainer) {
        window.__stickerDropzoneInstance = new ImageDropzone(stickerDropContainer, {
            inputId: 'sticker-file'
        });
    }
}

/**
 * Save settings
 */
async function saveSettings() {
    try {
        const language = document.getElementById('settings-language')?.value;
        const theme = document.getElementById('settings-theme')?.value;
        
        const response = await apiCall('/api/settings', {
            method: 'POST',
            body: JSON.stringify({
                language,
                theme
            })
        });
        
        const data = await response.json();
        
        if (data.status === 'ok') {
            showNotification(window.i18n ? window.i18n.t('settings.saved') : 'Settings saved successfully', 'success');
            // Apply theme immediately
            applyTheme(theme);
        } else {
            showNotification('Failed to save settings', 'error');
        }
    } catch (error) {
        console.error('Error saving settings:', error);
        showNotification('Error saving settings', 'error');
    }
}

/**
 * Apply theme to the application
 * @param {string} theme - Theme name ('light' or 'dark')
 */
function applyTheme(theme) {
    const htmlElement = document.documentElement;

    if (theme === 'dark') {
        htmlElement.classList.add('dark');
        document.body.classList.add('dark');
    } else {
        htmlElement.classList.remove('dark');
        document.body.classList.remove('dark');
    }

    // Save theme to localStorage
    localStorage.setItem('theme', theme);

    // Update theme selector if it exists
    const themeSelect = document.getElementById('settings-theme');
    if (themeSelect) {
        themeSelect.value = theme;
    }

    // Sync all Monaco editor instances to the new theme
    Monaco.syncTheme();
}

/**
 * Start auto-refresh for overview page
 */
function startAutoRefresh() {
    // Refresh overview data every 30 seconds
    AppState.refreshInterval = setInterval(() => {
        if (AppState.currentPage === 'overview') {
            loadOverviewData();
        }
    }, 30000);
    
    // Update runtime duration every second for real-time display
    AppState.runtimeInterval = setInterval(() => {
        if (AppState.currentPage === 'overview') {
            updateRuntimeDuration();
        }
    }, 1000);
}

// updateRuntimeDuration, updateElement → modules/overview.js

/**
 * Escape HTML to prevent XSS
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// showNotification → core/notify.js

/**
 * Open provider modal
 */
async function openProviderModal() {
    Modal.show('provider-modal');

    // Clear form fields
    document.getElementById('provider-name').value = '';
    const typeSelect = document.getElementById('provider-type');

    // Clear config container
    const configContainer = document.getElementById('provider-config-container');
    if (configContainer) {
        configContainer.innerHTML = '';
    }

    if (typeSelect) {
        // Fetch provider types
        try {
            const response = await apiCall('/api/provider-types');
            if (!response.ok) {
                throw new Error(`Failed to fetch types: ${response.status}`);
            }
            const types = await response.json();

            if (!Array.isArray(types)) {
                console.error('Provider types response is not an array:', types);
                throw new Error('Invalid response format');
            }

            // Re-fetch element to handle potential race conditions
            const currentTypeSelect = document.getElementById('provider-type');
            if (!currentTypeSelect) return;

            // Populate select
            currentTypeSelect.innerHTML = '<option value="">Select provider type...</option>';
            types.forEach(type => {
                const option = document.createElement('option');
                option.value = type;
                option.textContent = type;
                currentTypeSelect.appendChild(option);
            });

            // Refresh CustomSelect if present
            const customSelectWrapper = document.querySelector('.custom-select[data-custom-select="provider-type"]');
            if (customSelectWrapper) {
                customSelectWrapper.remove();
                // Re-initialize CustomSelect for this element
                if (typeof CustomSelect !== 'undefined') {
                    new CustomSelect(currentTypeSelect, {
                         placeholder: 'Select provider type...'
                    });
                }
            }

            // Use onchange property to avoid stacking listeners without replacing element
            currentTypeSelect.onchange = async (e) => {
                const selectedType = e.target.value;
                const configContainer = document.getElementById('provider-config-container');
                if (configContainer) configContainer.innerHTML = '';

                if (selectedType) {
                    await loadProviderSchema(selectedType);
                }
            };

        } catch (error) {
            console.error('Error fetching provider types:', error);
            showNotification(window.i18n ? window.i18n.t('provider.type_load_failed') : 'Failed to load provider types', 'error');
        }
    }
}

/**
 * Placeholder functions for edit/delete actions
 */
function editProvider(id) {
    showNotification('Edit provider functionality coming soon', 'info');
}

function deleteProvider(id) {
    if (!id) return;
    const title = window.i18n ? window.i18n.t('provider.delete_confirm_title') : 'Delete Provider';
    const message = window.i18n ? window.i18n.t('provider.delete_confirm_message') : 'Are you sure you want to delete this provider? This action cannot be undone.';
    openDeleteModal(title, message, async () => {
        try {
            const response = await apiCall(`/api/providers/${id}`, { method: 'DELETE' });
            if (response.status === 204 || response.status === 200) {
                showNotification(window.i18n ? window.i18n.t('provider.delete_success') : 'Provider deleted successfully', 'success');
                loadProviderData();
                if (AppState.selectedProviderId === id) {
                    AppState.selectedProviderId = null;
                    const configContainer = document.getElementById('provider-config');
                    if (configContainer) {
                        configContainer.innerHTML = `
                            <div class="flex justify-center items-center h-full">
                                <div class="text-center">
                                    <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"></path>
                                    </svg>
                                    <p class="text-gray-500" data-i18n="provider.select_provider">Select a provider to configure</p>
                                </div>
                            </div>
                        `;
                    }
                }
            } else {
                const errorData = await response.json().catch(() => ({}));
                showNotification(errorData.detail || (window.i18n ? window.i18n.t('provider.delete_failed') : 'Failed to delete provider'), 'error');
            }
            closeDeleteModal();
        } catch (error) {
            console.error('Error deleting provider:', error);
            showNotification(window.i18n ? window.i18n.t('provider.delete_failed') : 'Failed to delete provider', 'error');
        }
    });
}

function editAdapter(id) {
    const adapter = AppState.data.adapters.find(a => a.id === id);
    if (!adapter) {
        showNotification(window.i18n ? window.i18n.t('adapter.not_found') : 'Adapter not found', 'error');
        return;
    }
    openAdapterModal(adapter);
}

async function deleteAdapter(id) {
    if (!id) return;
    const title = window.i18n ? window.i18n.t('adapter.delete_confirm_title') : 'Delete Adapter';
    const message = window.i18n ? window.i18n.t('adapter.delete_confirm_message') : 'Are you sure you want to delete this adapter? This action cannot be undone.';
    openDeleteModal(title, message, async () => {
        try {
            const response = await apiCall(`/api/adapters/${encodeURIComponent(id)}`, {
                method: 'DELETE'
            });
            if (response.status === 204 || response.status === 200) {
                AppState.data.adapters = AppState.data.adapters.filter(a => a.id !== id);
                renderAdapterList();
                showNotification(window.i18n ? window.i18n.t('adapter.delete_success') : 'Adapter deleted successfully', 'success');
            } else {
                const errorData = await response.json().catch(() => ({}));
                showNotification(errorData.detail || (window.i18n ? window.i18n.t('adapter.delete_failed') : 'Failed to delete adapter'), 'error');
            }
            closeDeleteModal();
        } catch (error) {
            console.error('Error deleting adapter:', error);
            showNotification(window.i18n ? window.i18n.t('adapter.delete_failed') : 'Failed to delete adapter', 'error');
        }
    });
}

// editPersona, deletePersona → modules/persona.js
// sessionEditorState, session management → modules/session.js

function openDeleteModal(title, message, onConfirm) { Modal.confirm(title, message, onConfirm); }
async function confirmDelete() { await Modal.confirmExecute(); }
function closeDeleteModal() { Modal.confirmClose(); }

// editSession, initializeSessionEditor → modules/session.js

const mcpEditorState = {
    instance: null,
    serverId: null,
    mode: 'edit'
};

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

// closeSessionModal, saveSession, confirmDeleteSession → modules/session.js
// closeDeleteModal stays as global wrapper (used by sticker/session modules)

/**
 * Initialize Monaco Editor
 */
function initializeMonacoEditor() {
    // Monaco is already loading (triggered in core/monaco.js at parse time).
    // Just attach the callback for when it's ready.
    Monaco.load().then(() => {
        if (AppState.currentPage === 'configuration') {
            createEditor();
        }
    });
}

/**
 * Create Monaco Editor instance
 */
function createEditor() {
    const container = document.getElementById('monaco-editor-container');
    if (!container) return;

    const editor = Monaco.register('config', container,
        AppState.editor.currentFormat,
        AppState.editor.files[AppState.editor.currentFile]?.content || '',
        { renderWhitespace: 'selection' }
    );

    updateEditorStatus();

    editor.onDidChangeModelContent(() => {
        updateEditorStatus(true); // true indicates unsaved changes
    });
}

/**
 * Set up editor event listeners
 */
function setupEditorEventListeners() {
    // File selector change
    const fileSelector = document.getElementById('file-selector');
    if (fileSelector) {
        fileSelector.addEventListener('change', (e) => {
            const selectedFile = e.target.value;
            if (selectedFile) {
                loadFile(selectedFile);
            }
        });
    }
    
    // Format selector change
    const formatSelector = document.getElementById('format-selector');
    if (formatSelector) {
        formatSelector.addEventListener('change', (e) => {
            AppState.editor.currentFormat = e.target.value;
            Monaco.setLanguage('config', AppState.editor.currentFormat);
            updateEditorStatus();
        });
    }
    
    // Copy button
    const copyButton = document.getElementById('editor-copy');
    if (copyButton) {
        copyButton.addEventListener('click', () => {
            if (Monaco.get('config')) {
                navigator.clipboard.writeText(Monaco.getValue('config'));
                showNotification(window.i18n ? window.i18n.t('configuration.copied') : 'Content copied to clipboard', 'success');
            }
        });
    }
    
    // Download button
    const downloadButton = document.getElementById('editor-download');
    if (downloadButton) {
        downloadButton.addEventListener('click', () => {
            if (Monaco.get('config') && AppState.editor.currentFile) {
                const content = Monaco.getValue('config');
                const blob = new Blob([content], { type: 'text/plain' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = AppState.editor.currentFile;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                showNotification(window.i18n ? window.i18n.t('configuration.downloaded') : 'File downloaded', 'success');
            }
        });
    }
    
    // Refresh files button
    const refreshButton = document.getElementById('refresh-files');
    if (refreshButton) {
        refreshButton.addEventListener('click', () => {
            refreshFileList();
        });
    }
}

/**
 * Load a file into the editor
 * @param {string} fileName - Name of the file to load
 */
function loadFile(fileName) {
    if (!AppState.editor.files[fileName]) return;
    
    AppState.editor.currentFile = fileName;
    AppState.editor.currentFormat = AppState.editor.files[fileName].format;
    
    // Update format selector
    const formatSelector = document.getElementById('format-selector');
    if (formatSelector) {
        formatSelector.value = AppState.editor.currentFormat;
    }
    
    // Update editor content
    if (Monaco.get('config')) {
        Monaco.get('config').setValue(AppState.editor.files[fileName].content);
        Monaco.setLanguage('config', AppState.editor.currentFormat);
    }
    
    updateEditorStatus();
}

/**
 * Save the current file
 */
function saveCurrentFile() {
    if (!Monaco.get('config') || !AppState.editor.currentFile) return;

    const content = Monaco.getValue('config');
    AppState.editor.files[AppState.editor.currentFile].content = content;
    
    // In a real application, you would send this to the server
    // For now, we'll just show a success message
    updateEditorStatus(false);
    showNotification(window.i18n ? window.i18n.t('configuration.saved') : 'File saved successfully', 'success');
}

/**
 * Create a new file
 */
function createNewFile() {
    const fileName = prompt(window.i18n ? window.i18n.t('configuration.enter_filename') : 'Enter filename:');
    if (!fileName) return;
    
    const format = fileName.split('.').pop().toLowerCase();
    const supportedFormats = ['ini', 'json', 'md', 'xml'];
    
    if (!supportedFormats.includes(format)) {
        showNotification(window.i18n ? window.i18n.t('configuration.unsupported_format') : 'Unsupported file format', 'error');
        return;
    }
    
    // Create default content based on format
    let defaultContent = '';
    switch (format) {
        case 'ini':
            defaultContent = '; New INI file\n[section]\nkey = value';
            break;
        case 'json':
            defaultContent = '{\n  "key": "value"\n}';
            break;
        case 'md':
            defaultContent = '# New Markdown File\n\n## Section\n\nContent here';
            break;
        case 'xml':
            defaultContent = '<?xml version="1.0" encoding="UTF-8"?>\n<root>\n  <element>Content</element>\n</root>';
            break;
    }
    
    // Add file to the list
    AppState.editor.files[fileName] = { content: defaultContent, format };
    
    // Update file selector
    updateFileSelector();
    
    // Load the new file
    loadFile(fileName);
}

/**
 * Refresh the file list
 */
function refreshFileList() {
    // In a real application, you would fetch the file list from the server
    // For now, we'll just show a message
    showNotification(window.i18n ? window.i18n.t('configuration.refreshed') : 'File list refreshed', 'info');
}

/**
 * Update the file selector dropdown
 */
function updateFileSelector() {
    const fileSelector = document.getElementById('file-selector');
    if (!fileSelector) return;
    
    // Clear existing options except the first one
    while (fileSelector.children.length > 1) {
        fileSelector.removeChild(fileSelector.lastChild);
    }
    
    // Add file options
    Object.keys(AppState.editor.files).forEach(fileName => {
        const option = document.createElement('option');
        option.value = fileName;
        option.textContent = fileName;
        option.setAttribute('data-format', AppState.editor.files[fileName].format);
        fileSelector.appendChild(option);
    });
    
    // Select current file if available
    if (AppState.editor.currentFile) {
        fileSelector.value = AppState.editor.currentFile;
    }
}

/**
 * Update editor status
 * @param {boolean} hasChanges - Whether the file has unsaved changes
 */
function updateEditorStatus(hasChanges = false) {
    const statusElement = document.getElementById('editor-status');
    if (!statusElement) return;
    
    let statusText = '';
    if (AppState.editor.currentFile) {
        statusText = AppState.editor.currentFile;
        if (hasChanges) {
            statusText += ' *';
        }
    } else {
        statusText = window.i18n ? window.i18n.t('configuration.no_file') : 'No file selected';
    }
    
    statusElement.textContent = statusText;
}

function setupConfigurationTabs() {
    if (AppState.configurationTabsInitialized) {
        return;
    }
    const tabMessage = document.getElementById('config-tab-message');
    const tabModel = document.getElementById('config-tab-model');
    const contentMessage = document.getElementById('configuration-content-message');
    const contentModel = document.getElementById('configuration-content-model');
    if (!tabMessage || !tabModel || !contentMessage || !contentModel) {
        return;
    }
    const activateTab = (tab) => {
        AppState.configTab = tab;
        const isMessage = tab === 'message';
        contentMessage.classList.toggle('hidden', !isMessage);
        contentModel.classList.toggle('hidden', isMessage);
        if (isMessage) {
            tabMessage.classList.add('border-blue-600', 'dark:border-blue-500', 'text-blue-600', 'dark:text-blue-500');
            tabMessage.classList.remove('border-transparent', 'text-gray-500', 'dark:text-gray-400');
            tabModel.classList.remove('border-blue-600', 'dark:border-blue-500', 'text-blue-600', 'dark:text-blue-500');
            tabModel.classList.add('border-transparent', 'text-gray-500', 'dark:text-gray-400');
        } else {
            tabModel.classList.add('border-blue-600', 'dark:border-blue-500', 'text-blue-600', 'dark:text-blue-500');
            tabModel.classList.remove('border-transparent', 'text-gray-500', 'dark:text-gray-400');
            tabMessage.classList.remove('border-blue-600', 'dark:border-blue-500', 'text-blue-600', 'dark:text-blue-500');
            tabMessage.classList.add('border-transparent', 'text-gray-500', 'dark:text-gray-400');
        }
    };
    tabMessage.addEventListener('click', (e) => {
        e.preventDefault();
        activateTab('message');
    });
    tabModel.addEventListener('click', (e) => {
        e.preventDefault();
        activateTab('model');
    });
    activateTab(AppState.configTab || 'message');
    AppState.configurationTabsInitialized = true;
}

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

function getInputValue(id) {
    const el = document.getElementById(id);
    if (!el) {
        return '';
    }
    return String(el.value || '').trim();
}

function populateMessageConfiguration(botConfig) {
    const bot = botConfig.bot || {};
    const agent = botConfig.agent || {};
    const selfie = botConfig.selfie || {};
    const setValue = (id, value) => {
        const el = document.getElementById(id);
        if (el) {
            el.value = value != null ? value : '';
        }
    };
    setValue('msg-max-memory-length', bot.max_memory_length);
    setValue('msg-max-message-interval', bot.max_message_interval);
    setValue('msg-max-buffer-messages', bot.max_buffer_messages);
    setValue('msg-min-message-delay', bot.min_message_delay);
    setValue('msg-max-message-delay', bot.max_message_delay);
    setValue('msg-agent-max-tool-loop', agent.max_tool_loop);
    setValue('msg-selfie-path', selfie.path);
}

function parseModelReference(ref) {
    if (typeof ref !== 'string' || !ref) {
        return { providerId: '', modelId: '' };
    }
    const parts = ref.split(':');
    if (parts.length === 1) {
        return { providerId: parts[0], modelId: '' };
    }
    return { providerId: parts[0], modelId: parts.slice(1).join(':') };
}

function populateModelConfiguration(modelsConfig, providers, providerModels) {
    const modelTypes = [
        {
            key: 'default_llm',
            providerSelectId: 'config-model-default-llm-provider',
            modelSelectId: 'config-model-default-llm-model',
            typeKey: 'llm'
        },
        {
            key: 'default_vlm',
            providerSelectId: 'config-model-default-vlm-provider',
            modelSelectId: 'config-model-default-vlm-model',
            typeKey: 'llm'
        },
        {
            key: 'default_fast_llm',
            providerSelectId: 'config-model-default-fast-llm-provider',
            modelSelectId: 'config-model-default-fast-llm-model',
            typeKey: 'llm'
        },
        {
            key: 'default_tts',
            providerSelectId: 'config-model-default-tts-provider',
            modelSelectId: 'config-model-default-tts-model',
            typeKey: 'tts'
        },
        {
            key: 'default_stt',
            providerSelectId: 'config-model-default-stt-provider',
            modelSelectId: 'config-model-default-stt-model',
            typeKey: 'stt'
        },
        {
            key: 'default_image',
            providerSelectId: 'config-model-default-image-provider',
            modelSelectId: 'config-model-default-image-model',
            typeKey: 'image'
        },
        {
            key: 'default_embedding',
            providerSelectId: 'config-model-default-embedding-provider',
            modelSelectId: 'config-model-default-embedding-model',
            typeKey: 'embedding'
        },
        {
            key: 'default_rerank',
            providerSelectId: 'config-model-default-rerank-provider',
            modelSelectId: 'config-model-default-rerank-model',
            typeKey: 'rerank'
        },
        {
            key: 'default_video',
            providerSelectId: 'config-model-default-video-provider',
            modelSelectId: 'config-model-default-video-model',
            typeKey: 'video'
        }
    ];
    const fillProviderOptions = (select, selectedProviderId) => {
        if (!select) {
            return;
        }
        select.innerHTML = '';
        const emptyOption = document.createElement('option');
        emptyOption.value = '';
        emptyOption.textContent = '';
        select.appendChild(emptyOption);
        providers.forEach((p) => {
            const option = document.createElement('option');
            option.value = p.id;
            option.textContent = p.name || p.id;
            if (p.id === selectedProviderId) {
                option.selected = true;
            }
            select.appendChild(option);
        });
    };
    const fillModelOptions = (select, providerId, typeKey, selectedModelId) => {
        if (!select) {
            return;
        }
        select.innerHTML = '';
        const emptyOption = document.createElement('option');
        emptyOption.value = '';
        emptyOption.textContent = '';
        select.appendChild(emptyOption);
        if (!providerId) {
            return;
        }
        const providerConfig = providerModels[providerId] || {};
        const typeConfig = providerConfig[typeKey] || {};
        Object.keys(typeConfig).forEach((modelId) => {
            const option = document.createElement('option');
            option.value = modelId;
            option.textContent = modelId;
            if (modelId === selectedModelId) {
                option.selected = true;
            }
            select.appendChild(option);
        });
    };
    modelTypes.forEach((entry) => {
        const value = modelsConfig[entry.key];
        const parsed = parseModelReference(value);
        const providerSelect = document.getElementById(entry.providerSelectId);
        const modelSelect = document.getElementById(entry.modelSelectId);
        fillProviderOptions(providerSelect, parsed.providerId);
        fillModelOptions(modelSelect, parsed.providerId, entry.typeKey, parsed.modelId);
        if (providerSelect && modelSelect) {
            providerSelect.onchange = () => {
                const providerId = providerSelect.value || '';
                fillModelOptions(modelSelect, providerId, entry.typeKey, '');
            };
        }
    });
}

function buildModelsConfiguration() {
    const modelTypes = [
        {
            key: 'default_llm',
            providerSelectId: 'config-model-default-llm-provider',
            modelSelectId: 'config-model-default-llm-model'
        },
        {
            key: 'default_vlm',
            providerSelectId: 'config-model-default-vlm-provider',
            modelSelectId: 'config-model-default-vlm-model'
        },
        {
            key: 'default_fast_llm',
            providerSelectId: 'config-model-default-fast-llm-provider',
            modelSelectId: 'config-model-default-fast-llm-model'
        },
        {
            key: 'default_tts',
            providerSelectId: 'config-model-default-tts-provider',
            modelSelectId: 'config-model-default-tts-model'
        },
        {
            key: 'default_stt',
            providerSelectId: 'config-model-default-stt-provider',
            modelSelectId: 'config-model-default-stt-model'
        },
        {
            key: 'default_image',
            providerSelectId: 'config-model-default-image-provider',
            modelSelectId: 'config-model-default-image-model'
        },
        {
            key: 'default_embedding',
            providerSelectId: 'config-model-default-embedding-provider',
            modelSelectId: 'config-model-default-embedding-model'
        },
        {
            key: 'default_rerank',
            providerSelectId: 'config-model-default-rerank-provider',
            modelSelectId: 'config-model-default-rerank-model'
        },
        {
            key: 'default_video',
            providerSelectId: 'config-model-default-video-provider',
            modelSelectId: 'config-model-default-video-model'
        }
    ];
    const models = {};
    modelTypes.forEach((entry) => {
        const providerSelect = document.getElementById(entry.providerSelectId);
        const modelSelect = document.getElementById(entry.modelSelectId);
        const providerId = providerSelect ? providerSelect.value : '';
        const modelId = modelSelect ? modelSelect.value : '';
        if (providerId && modelId) {
            models[entry.key] = providerId + ':' + modelId;
        } else {
            models[entry.key] = null;
        }
    });
    return models;
}

/**
 * Configuration save function
 */
async function saveConfiguration() {
    try {
        const botConfig = {
            bot: {
                max_memory_length: getInputValue('msg-max-memory-length'),
                max_message_interval: getInputValue('msg-max-message-interval'),
                max_buffer_messages: getInputValue('msg-max-buffer-messages'),
                min_message_delay: getInputValue('msg-min-message-delay'),
                max_message_delay: getInputValue('msg-max-message-delay')
            },
            agent: {
                max_tool_loop: getInputValue('msg-agent-max-tool-loop')
            },
            selfie: {
                path: getInputValue('msg-selfie-path')
            }
        };
        const models = buildModelsConfiguration();
        const response = await apiCall('/api/configuration', {
            method: 'POST',
            body: JSON.stringify({
                bot_config: botConfig,
                models: models
            })
        });
        
        const data = await response.json();
        
        if (data.status === 'ok') {
            showNotification(window.i18n ? window.i18n.t('configuration.saved') : 'Configuration saved successfully', 'success');
        } else {
            showNotification('Failed to save configuration', 'error');
        }
    } catch (error) {
        console.error('Error saving configuration:', error);
        showNotification('Error saving configuration', 'error');
    }
}

// clearLogs, refreshLogs → modules/log.js

// Export for global access
window.AppState = AppState;
window.switchPage = switchPage;
window.loadPageData = loadPageData;
window.apiCall = apiCall;
window.showNotification = showNotification;

// Remove duplicate openProviderModal if present at the end of file
// The valid one is around line 1325


/**
 * Fetch provider schema
 * @param {string} providerType - The provider type
 * @returns {Promise<object>} The schema object
 */
async function fetchProviderSchema(providerType) {
    try {
        const response = await apiCall(`/api/providers/schema/${providerType}`);
        if (!response.ok) throw new Error('Failed to load schema');
        return await response.json();
    } catch (error) {
        console.error('Error loading schema:', error);
        return null;
    }
}

/**
 * Load provider schema and render config fields (for Modal)
 * @param {string} providerType - The provider type
 */
async function loadProviderSchema(providerType) {
    const configContainer = document.getElementById('provider-config-container');
    if (!configContainer) return;
    
    configContainer.innerHTML = '<div class="text-center text-gray-500 py-4">Loading schema...</div>';
    
    const schema = await fetchProviderSchema(providerType);
    if (schema) {
        renderProviderConfigFields(schema, configContainer);
    } else {
        configContainer.innerHTML = '<div class="text-red-500 py-2">Error loading configuration schema</div>';
    }
}

function renderProviderConfigFields(schema, container, currentConfig = {}) {
    renderConfigFields(schema, container, currentConfig);
}

// validateConfigFieldInput → shared/render-config-fields.js

/**
 * Close provider modal
 */
function closeProviderModal() {
    Modal.hide('provider-modal');
}

/**
 * Save provider
 */
async function saveProvider() {
    const name = document.getElementById('provider-name').value.trim();
    const type = document.getElementById('provider-type').value;
    
    if (!name) {
        showNotification(window.i18n ? window.i18n.t('provider.name_required') : 'Please enter provider name', 'error');
        return;
    }
    
    if (!type) {
        showNotification(window.i18n ? window.i18n.t('provider.type_required') : 'Please select provider type', 'error');
        return;
    }
    
    // Collect dynamic config
    const configContainer = document.getElementById('provider-config-container');
    let hasValidationError = false;
    if (configContainer) {
        configContainer.querySelectorAll('input[data-config-key]').forEach(input => {
            if (!validateConfigFieldInput(input)) hasValidationError = true;
        });
    }
    if (hasValidationError) {
        showNotification(getTranslation('model.validation_failed', 'Please fix validation errors before saving'), 'error');
        return;
    }
    const config = collectConfigFromContainer(configContainer);
    
    try {
        const response = await apiCall('/api/providers', {
            method: 'POST',
            body: JSON.stringify({
                name: name,
                type: type,
                config: config
            })
        });
        
        if (response.ok) {
            // Reload provider list
            await loadProviderData();
            
            // Close modal
            closeProviderModal();
            
            // Show success notification
            showNotification(window.i18n ? window.i18n.t('provider.added') : 'Provider added successfully', 'success');
        } else {
            const errorData = await response.json();
            showNotification(errorData.detail || (window.i18n ? window.i18n.t('provider.add_failed') : 'Failed to add provider'), 'error');
        }
    } catch (error) {
        console.error('Error saving provider:', error);
        showNotification(window.i18n ? window.i18n.t('provider.save_failed') : 'Error saving provider', 'error');
    }
}

// Export modal functions
window.openProviderModal = openProviderModal;
window.closeProviderModal = closeProviderModal;
window.saveProvider = saveProvider;

/**
 * Select a provider and display its configuration
 * @param {string} providerId - ID of the provider to select
 */
function selectProvider(providerId) {
    AppState.selectedProviderId = providerId;
    
    // Update provider list to show selected state
    renderProviderList();
    
    // Display provider configuration
    const provider = AppState.data.providers.find(p => p.id === providerId);
    if (provider) {
        displayProviderConfig(provider);
    }
}

/**
 * Display provider configuration in the right panel
 * @param {object} provider - Provider object to display
 */
async function displayProviderConfig(provider) {
    const configContainer = document.getElementById('provider-config');
    if (!configContainer) return;
    
    // Define model groups
    const modelGroups = ['LLM', 'TTS', 'STT', 'Image', 'Video', 'Embedding', 'Rerank'];
    const groupTypeMapping = {
        LLM: 'llm',
        TTS: 'tts',
        STT: 'stt',
        Image: 'image',
        Video: 'video',
        Embedding: 'embedding',
        Rerank: 'rerank'
    };
    let visibleGroups = modelGroups;
    if (provider && Array.isArray(provider.supported_model_types) && provider.supported_model_types.length > 0) {
        const typesSet = new Set(provider.supported_model_types);
        visibleGroups = modelGroups.filter(group => typesSet.has(groupTypeMapping[group]));
    }
    
    configContainer.innerHTML = `
        <div class="space-y-6">
            <div class="border-b border-gray-200 pb-4">
                <h3 class="text-xl font-semibold text-gray-800">${escapeHtml(provider.name)}</h3>
                <p class="text-sm text-gray-500 mt-1">${escapeHtml(provider.type)}</p>
            </div>
            
            <div id="provider-details-config" class="space-y-4">
                <div class="text-center text-gray-500 py-4">Loading configuration...</div>
            </div>
            
            <div class="flex justify-end space-x-3 pt-2">
                 <button onclick="saveProviderConfig('${provider.id}')" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                    Save Configuration
                </button>
            </div>
            
            <div class="border-t border-gray-200 dark:border-gray-700 pt-6">
                <h4 class="text-lg font-semibold text-gray-800 dark:text-gray-200 mb-4" data-i18n="provider.model_groups">Model Groups</h4>
                <div class="space-y-3">
                    ${visibleGroups.map(group => `
                        <div class="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                            <div class="flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-gray-800 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors" onclick="toggleModelGroup('${group}')">
                                <div class="flex items-center">
                                    <svg id="model-group-icon-${group}" class="w-5 h-5 text-gray-500 dark:text-gray-400 mr-2 transition-transform duration-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                                    </svg>
                                    <span class="font-medium text-gray-700 dark:text-gray-200" data-i18n="provider.model_group_${group.toLowerCase()}">${group}</span>
                                </div>
                                <button onclick="event.stopPropagation(); addModel('${group}')" class="p-1 text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 transition-colors" title="${i18n.t('provider.add_model')}">
                                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
                                    </svg>
                                </button>
                            </div>
                            <div id="model-group-content-${group}" class="px-4 py-3 bg-white dark:bg-gray-900 hidden">
                                <div class="text-sm text-gray-500 dark:text-gray-400 text-center py-4" data-i18n="provider.no_models">No models configured</div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
            
            <div class="flex justify-end space-x-3 pt-4 border-t border-gray-200">
                <button onclick="deleteProvider('${provider.id}')" class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors" data-i18n="provider.delete">
                    Delete Provider
                </button>
            </div>
        </div>
    `;
    
    // Fetch schema and render config fields
    const detailsContainer = document.getElementById('provider-details-config');
    if (detailsContainer) {
        const schema = await fetchProviderSchema(provider.type);
        if (schema) {
            detailsContainer.innerHTML = '';
            
            const nameWrapper = document.createElement('div');
            nameWrapper.className = 'mb-4';
            
            const nameLabel = document.createElement('label');
            nameLabel.className = 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2';
            nameLabel.textContent = 'Name';
            
            const nameInput = document.createElement('input');
            nameInput.type = 'text';
            nameInput.id = 'provider-name-input';
            nameInput.className = 'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500';
            nameInput.value = provider.name || '';
            
            nameWrapper.appendChild(nameLabel);
            nameWrapper.appendChild(nameInput);
            detailsContainer.appendChild(nameWrapper);
            
            const configFieldsContainer = document.createElement('div');
            detailsContainer.appendChild(configFieldsContainer);
            
            renderProviderConfigFields(schema, configFieldsContainer, provider.config);
            await loadProviderModels(provider.id);
        } else {
            detailsContainer.innerHTML = '<div class="text-red-500 py-2">Error loading configuration schema</div>';
        }
    }

    if (window.i18n) {
        updateTranslations();
    }
}

/**
 * Save provider configuration from details panel
 * @param {string} providerId
 */
async function saveProviderConfig(providerId) {
    const detailsContainer = document.getElementById('provider-details-config');
    if (!detailsContainer) return;

    // Get current provider details to preserve name and type
    const provider = AppState.data.providers.find(p => p.id === providerId);
    if (!provider) {
        showNotification(window.i18n ? window.i18n.t('provider.not_found') : 'Provider not found', 'error');
        return;
    }

    const config = collectConfigFromContainer(detailsContainer);

    let name = provider.name;
    const nameInput = detailsContainer.querySelector('#provider-name-input');
    if (nameInput) {
        name = nameInput.value.trim() || provider.name;
    }

    try {
        const response = await apiCall(`/api/providers/${providerId}`, {
            method: 'PUT',
            body: JSON.stringify({
                name: name,
                type: provider.type,
                config: config
            })
        });
        
        if (response.ok) {
            showNotification('Configuration saved successfully', 'success');
            await loadProviderData(); // Reload data
        } else {
            const errorData = await response.json();
            showNotification(errorData.detail || 'Failed to save configuration', 'error');
        }
    } catch (error) {
        console.error('Error saving config:', error);
        showNotification('Error saving configuration', 'error');
    }
}

window.saveProviderConfig = saveProviderConfig;


async function loadProviderModels(providerId) {
    try {
        const response = await apiCall(`/api/providers/${providerId}/models`);
        if (!response.ok) {
            return;
        }
        const modelConfig = await response.json();
        AppState.data.providerModels = AppState.data.providerModels || {};
        AppState.data.providerModels[providerId] = modelConfig;
        renderModelGroupModels(modelConfig);
    } catch (error) {
        console.error('Error loading provider models:', error);
    }
}

function renderModelGroupModels(modelConfig) {
    modelConfig = modelConfig || {};
    const groups = {
        LLM: 'llm',
        TTS: 'tts',
        STT: 'stt',
        Image: 'image',
        Video: 'video',
        Embedding: 'embedding',
        Rerank: 'rerank'
    };
    Object.entries(groups).forEach(([groupName, type]) => {
        const container = document.getElementById(`model-group-content-${groupName}`);
        if (!container) {
            return;
        }
        container.innerHTML = '';
        const typeConfig = modelConfig[type] || {};
        const modelIds = Object.keys(typeConfig);
        if (modelIds.length === 0) {
            container.innerHTML = `
                <div class="text-sm text-gray-500 dark:text-gray-400 text-center py-4" data-i18n="provider.no_models">No models configured</div>
            `;
            return;
        }
        const wrapper = document.createElement('div');
        wrapper.className = 'space-y-2';
        modelIds.forEach(modelId => {
            const row = document.createElement('div');
            row.className = 'flex items-center justify-between py-1 border-b border-gray-100 dark:border-gray-800 last:border-b-0';

            const left = document.createElement('div');
            left.className = 'flex-1 text-sm text-gray-800 dark:text-gray-100';
            left.textContent = modelId;

            const actions = document.createElement('div');
            actions.className = 'flex items-center space-x-2';

            const settingsButton = document.createElement('button');
            settingsButton.className = 'p-1 text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 transition-colors';
            settingsButton.innerHTML = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"></path></svg>';
            settingsButton.onclick = async () => {
                const providerId = AppState.selectedProviderId;
                if (!providerId) return;
                const provider = AppState.data.providers.find(p => p.id === providerId);
                if (!provider) return;
                try {
                    const resp = await apiCall(`/api/providers/${providerId}/models`);
                    if (!resp.ok) return;
                    const allModels = await resp.json();
                    const typeModels = allModels[type] || {};
                    const existingConfig = typeModels[modelId] || {};
                    openModelModal(providerId, type, groupName, modelId, existingConfig);
                } catch (e) {
                    console.error('Error loading model config for edit:', e);
                }
            };

            const deleteButton = document.createElement('button');
            deleteButton.className = 'p-1 text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 transition-colors';
            deleteButton.innerHTML = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>';
            deleteButton.onclick = () => {
                const providerId = AppState.selectedProviderId;
                if (!providerId) return;
                deleteModel(providerId, type, modelId);
            };

            actions.appendChild(settingsButton);
            actions.appendChild(deleteButton);

            row.appendChild(left);
            row.appendChild(actions);

            wrapper.appendChild(row);
        });
        container.appendChild(wrapper);
    });
}


function toggleModelGroup(groupName) {
    const content = document.getElementById(`model-group-content-${groupName}`);
    const icon = document.getElementById(`model-group-icon-${groupName}`);
    
    if (content && icon) {
        content.classList.toggle('hidden');
        icon.classList.toggle('rotate-180');
    }
}

const modelModalState = {
    providerId: null,
    modelType: null,
    mode: 'create',
    modelId: null
};

async function openModelModal(providerId, modelType, groupLabel, modelId = null, existingConfig = null) {
    modelModalState.providerId = providerId;
    modelModalState.modelType = modelType;
    modelModalState.mode = modelId ? 'edit' : 'create';
    modelModalState.modelId = modelId;
    Modal.show('model-modal');
    const modelIdInput = document.getElementById('model-id');
    const modelIdError = document.getElementById('model-id-error');
    const modelIdHint = document.getElementById('model-id-hint');
    if (modelIdInput) {
        // Reset validation state
        modelIdInput.classList.remove('border-red-500', 'dark:border-red-400');
        modelIdInput.classList.add('border-gray-300', 'dark:border-gray-600');
        if (modelIdError) { modelIdError.classList.add('hidden'); modelIdError.textContent = ''; }
        if (modelIdHint) modelIdHint.classList.remove('hidden');

        if (modelId) {
            modelIdInput.value = modelId;
            modelIdInput.disabled = true;
        } else {
            modelIdInput.value = '';
            modelIdInput.disabled = false;
        }
        // Remove old listeners then attach new real-time validation
        const currentValue = modelIdInput.value;
        const currentDisabled = modelIdInput.disabled;
        const newInput = modelIdInput.cloneNode(true);
        modelIdInput.parentNode.replaceChild(newInput, modelIdInput);
        newInput.value = currentValue;
        newInput.disabled = currentDisabled;
        newInput.addEventListener('input', function() {
            validateModelIdInput(this);
        });
        newInput.addEventListener('blur', function() {
            validateModelIdInput(this);
        });
    }
    const groupElement = document.getElementById('model-modal-group');
    if (groupElement) {
        groupElement.textContent = groupLabel || '';
    }
    const configContainer = document.getElementById('model-config-container');
    if (configContainer) {
        configContainer.innerHTML = '';
    }
    const provider = AppState.data.providers.find(p => p.id === providerId);
    if (!provider) {
        showNotification(getTranslation('model.provider_not_found', 'Provider not found'), 'error');
        return;
    }
    try {
        const schema = await fetchProviderSchema(provider.type);
        if (!schema) return;
        const modelConfigSchema = (schema.model_config || {})[modelType] || {};
        let initialConfig = {};
        if (existingConfig) {
            initialConfig = existingConfig;
        }
        renderProviderConfigFields(modelConfigSchema, configContainer, initialConfig);
    } catch (error) {
        console.error('Error loading model schema:', error);
        showNotification(getTranslation('model.schema_load_failed', 'Failed to load model config schema'), 'error');
    }
}

/**
 * Validate model ID input in real-time
 * @param {HTMLInputElement} input
 * @returns {boolean}
 */
function validateModelIdInput(input) {
    const value = input.value.trim();
    const errorEl = document.getElementById('model-id-error');
    const hintEl = document.getElementById('model-id-hint');

    let errorMsg = '';
    if (value === '') {
        errorMsg = getTranslation('model.validation_id_required', 'Model ID is required');
    } else if (value.length > 128) {
        errorMsg = getTranslation('model.validation_id_too_long', 'Model ID must be 128 characters or less');
    }

    if (errorMsg) {
        input.classList.remove('border-gray-300', 'dark:border-gray-600', 'focus:ring-blue-500');
        input.classList.add('border-red-500', 'dark:border-red-400', 'focus:ring-red-500');
        if (errorEl) { errorEl.textContent = errorMsg; errorEl.classList.remove('hidden'); }
        if (hintEl) hintEl.classList.add('hidden');
        return false;
    } else {
        input.classList.remove('border-red-500', 'dark:border-red-400', 'focus:ring-red-500');
        input.classList.add('border-gray-300', 'dark:border-gray-600', 'focus:ring-blue-500');
        if (errorEl) { errorEl.textContent = ''; errorEl.classList.add('hidden'); }
        if (hintEl) hintEl.classList.remove('hidden');
        return true;
    }
}

function closeModelModal() {
    Modal.hide('model-modal');
    modelModalState.providerId = null;
    modelModalState.modelType = null;
    modelModalState.mode = 'create';
    modelModalState.modelId = null;
}

async function saveModel() {
    const providerId = modelModalState.providerId;
    const modelType = modelModalState.modelType;
    const mode = modelModalState.mode || 'create';
    if (!providerId || !modelType) {
        showNotification(getTranslation('model.no_provider_selected', 'No provider selected'), 'error');
        return;
    }
    const modelIdInput = document.getElementById('model-id');
    if (!modelIdInput) return;
    let modelId = modelModalState.modelId;
    if (mode === 'create') {
        // Run real-time validation before proceeding
        if (!validateModelIdInput(modelIdInput)) {
            modelIdInput.focus();
            return;
        }
        modelId = modelIdInput.value.trim();
        if (!modelId) {
            showNotification(getTranslation('model.id_required', 'Model ID is required'), 'error');
            return;
        }
    }
    // Validate config fields
    const configContainer = document.getElementById('model-config-container');
    let hasValidationError = false;
    const configInputs = configContainer ? configContainer.querySelectorAll('input[data-config-key]') : [];
    configInputs.forEach(input => {
        if (!validateConfigFieldInput(input)) {
            hasValidationError = true;
        }
    });
    if (hasValidationError) {
        showNotification(getTranslation('model.validation_failed', 'Please fix validation errors before saving'), 'error');
        return;
    }
    const config = {};
    configInputs.forEach(input => {
            const key = input.getAttribute('data-config-key');
            const fieldType = input.getAttribute('data-config-type');
            if (!key) {
                return;
            }
            let value = input.value;
            if (fieldType === 'integer') {
                value = value === '' ? null : parseInt(value, 10);
            } else if (fieldType === 'float') {
                value = value === '' ? null : parseFloat(value);
            }
            config[key] = value;
        });
    try {
        let response;
        if (mode === 'edit') {
            response = await apiCall(`/api/providers/${providerId}/models/${modelType}/${encodeURIComponent(modelId)}`, {
                method: 'PUT',
                body: JSON.stringify({
                    config: config
                })
            });
        } else {
            response = await apiCall(`/api/providers/${providerId}/models`, {
                method: 'POST',
                body: JSON.stringify({
                    model_type: modelType,
                    model_id: modelId,
                    config: config
                })
            });
        }
        if (response.ok) {
            const successKey = mode === 'edit' ? 'model.update_success' : 'model.add_success';
            const successFallback = mode === 'edit' ? 'Model updated successfully' : 'Model added successfully';
            showNotification(getTranslation(successKey, successFallback), 'success');
            closeModelModal();
            AppState.data.providerModels = AppState.data.providerModels || {};
            const modelConfig = AppState.data.providerModels[providerId] || {};
            if (!modelConfig[modelType]) {
                modelConfig[modelType] = {};
            }
            modelConfig[modelType][modelId] = config;
            AppState.data.providerModels[providerId] = modelConfig;
            renderModelGroupModels(modelConfig);
        } else {
            const errorData = await response.json().catch(() => ({}));
            const message = errorData.detail || getTranslation('model.add_failed', 'Failed to add model');
            showNotification(message, 'error');
        }
    } catch (error) {
        console.error('Error adding model:', error);
        showNotification(getTranslation('model.add_error', 'Error adding model'), 'error');
    }
}

function addModel(groupName) {
    const providerId = AppState.selectedProviderId;
    if (!providerId) {
        showNotification(getTranslation('model.select_provider_first', 'Please select a provider first'), 'error');
        return;
    }
    const modelType = groupName.toLowerCase();
    openModelModal(providerId, modelType, groupName);
}

async function reloadProvider(providerId) {
    try {
        const response = await apiCall(`/api/providers/${providerId}`);
        if (!response.ok) {
            return;
        }
        const provider = await response.json();
        const index = AppState.data.providers.findIndex(p => p.id === providerId);
        if (index !== -1) {
            AppState.data.providers[index] = provider;
        } else {
            AppState.data.providers.push(provider);
        }
        renderProviderList();
        AppState.selectedProviderId = providerId;
        displayProviderConfig(provider);
    } catch (error) {
        console.error('Error reloading provider:', error);
    }
}

async function deleteModel(providerId, modelType, modelId) {
    try {
        const response = await apiCall(`/api/providers/${providerId}/models/${modelType}/${encodeURIComponent(modelId)}`, {
            method: 'DELETE'
        });
        if (response.ok) {
            showNotification(getTranslation('model.delete_success', 'Model deleted successfully'), 'success');
            AppState.data.providerModels = AppState.data.providerModels || {};
            const modelConfig = AppState.data.providerModels[providerId] || {};
            const typeConfig = modelConfig[modelType] || {};
            delete typeConfig[modelId];
            modelConfig[modelType] = typeConfig;
            AppState.data.providerModels[providerId] = modelConfig;
            renderModelGroupModels(modelConfig);
        } else {
            const errorData = await response.json().catch(() => ({}));
            const message = errorData.detail || getTranslation('model.delete_failed', 'Failed to delete model');
            showNotification(message, 'error');
        }
    } catch (error) {
        console.error('Error deleting model:', error);
        showNotification(getTranslation('model.delete_error', 'Error deleting model'), 'error');
    }
}

/**
 * Toggle provider status
 * @param {string} providerId - ID of the provider to toggle
 */
function toggleProviderStatus(providerId) {
    const provider = AppState.data.providers.find(p => p.id === providerId);
    if (provider) {
        provider.status = provider.status === 'active' ? 'inactive' : 'active';
        renderProviderList();
        displayProviderConfig(provider);
        showNotification(window.i18n ? window.i18n.t(provider.status === 'active' ? 'provider.enabled' : 'provider.disabled') : `Provider ${provider.status === 'active' ? 'enabled' : 'disabled'}`, 'success');
    }
}

window.selectProvider = selectProvider;
window.toggleProviderStatus = toggleProviderStatus;
window.toggleModelGroup = toggleModelGroup;
window.addModel = addModel;
window.deleteModel = deleteModel;
window.openModelModal = openModelModal;
window.closeModelModal = closeModelModal;
window.saveModel = saveModel;

// openPersonaModal, closePersonaModal, createPersonaEditor, savePersona → modules/persona.js
