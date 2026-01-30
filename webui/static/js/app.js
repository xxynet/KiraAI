/**
 * Main application JavaScript for KiraAI Admin Panel
 * Handles page navigation, API interactions, and data updates
 */

// Application state
const AppState = {
    currentPage: 'overview',
    refreshInterval: null,
    selectedProviderId: null,
    sseEventSource: null,
    configTab: 'message',
    configurationTabsInitialized: false,
    data: {
        overview: null,
        providers: [],
        adapters: [],
        personas: [],
        settings: {},
        providerModels: {},
        configuration: null,
        configProviders: [],
        configProviderModels: {},
        logConfig: {
            maxQueueSize: 100
        },
        logFilter: {
            level: 'all'
        }
    },
    editor: {
        instance: null,
        currentFile: null,
        currentFormat: 'ini',
        files: {
            'config.ini': { content: '; Configuration file\n[database]\nhost = localhost\nport = 5432\nusername = admin\npassword = secret', format: 'ini' },
            'settings.json': { content: '{\n  "name": "KiraAI",\n  "version": "1.0.0",\n  "debug": true,\n  "features": {\n    "logging": true,\n    "metrics": false\n  }\n}', format: 'json' },
            'README.md': { content: '# KiraAI\n\n## Description\nKiraAI is an advanced AI system.\n\n## Installation\n```bash\nnpm install\n```\n\n## Usage\n```javascript\nconst kira = new KiraAI();\nkira.initialize();\n```', format: 'md' },
            'app.xml': { content: '<?xml version="1.0" encoding="UTF-8"?>\n<application>\n  <name>KiraAI</name>\n  <version>1.0.0</version>\n  <settings>\n    <debug>true</debug>\n    <logging>\n      <level>info</level>\n      <file>app.log</file>\n    </logging>\n  </settings>\n</application>', format: 'xml' }
        }
    },
    personaEditor: {
        instance: null,
        format: 'json'
    }
};

/**
 * Unified API call function with JWT authentication
 */
async function apiCall(url, options = {}) {
    const jwtToken = localStorage.getItem('jwt_token');

    if (!jwtToken) {
        window.location.href = '/login';
        throw new Error('No JWT token found');
    }

    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    headers['Authorization'] = `Bearer ${jwtToken}`;

    const response = await fetch(url, {
        ...options,
        headers
    });

    // Handle 401 Unauthorized
    if (response.status === 401) {
        localStorage.removeItem('jwt_token');
        window.location.href = '/login';
        throw new Error('Unauthorized');
    }

    return response;
}

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

    setupNavigation();
    loadInitialData();
    setupEventListeners();
    startAutoRefresh();
    initializeMonacoEditor();
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

/**
 * Load overview statistics
 */
async function loadOverviewData() {
    try {
        const response = await apiCall('/api/overview');
        const data = await response.json();
        AppState.data.overview = data;
        
        // Update statistics cards
        updateElement('stat-total-adapters', data.total_adapters || 0);
        updateElement('stat-active-adapters', data.active_adapters || 0);
        updateElement('stat-total-providers', data.total_providers || 0);
        updateElement('stat-total-messages', data.total_messages || 0);
        
        // Update runtime duration
        const runtimeElement = document.getElementById('stat-runtime-duration');
        if (runtimeElement) {
            // Store the base timestamp for real-time updates
            AppState.data.overview.base_timestamp = Date.now();
            AppState.data.overview.runtime_duration = data.runtime_duration || 0;
            updateRuntimeDuration();
        }
        
        // Update memory usage
        const memoryUsage = data.memory_usage || 0;
        const totalMemory = data.total_memory || 0;
//        const memoryUsageDisplay = totalMemory > 0
//            ? `${memoryUsage} MB / ${totalMemory} MB`
//            : `${memoryUsage} MB`;
        const memoryUsageDisplay = `${memoryUsage} MB`;
        updateElement('stat-memory-usage', memoryUsageDisplay);
        
        // Update system status
        const statusIndicator = document.getElementById('system-status-indicator');
        const statusText = document.getElementById('system-status-text');
        
        if (statusIndicator && statusText) {
            const status = data.system_status || 'unknown';
            statusIndicator.className = `w-3 h-3 rounded-full mr-2 ${
                status === 'running' ? 'bg-green-500' :
                status === 'stopped' ? 'bg-red-500' : 'bg-gray-400'
            }`;
            
            if (window.i18n) {
                statusText.setAttribute('data-i18n', `overview.status_${status}`);
                statusText.textContent = window.i18n.t(`overview.status_${status}`);
            } else {
                statusText.textContent = status.charAt(0).toUpperCase() + status.slice(1);
            }
        }
    } catch (error) {
        console.error('Error loading overview data:', error);
    }
}

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
                                onclick="editAdapter('${id}')"
                            >
                                Edit
                            </button>
                            <button
                                class="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30"
                                onclick="deleteAdapter('${id}')"
                            >
                                Delete
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
        showNotification('Adapter status updated', 'success');
    } catch (error) {
        console.error('Error toggling adapter status:', error);
        showNotification('Failed to update adapter status', 'error');
    }
}

const AdapterModalState = {
    mode: 'create',
    adapterId: null
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
        showNotification('Failed to load adapter schema', 'error');
        return null;
    }
}

async function loadAdapterSchema(platform, currentValues = {}) {
    const schema = await fetchAdapterSchema(platform);
    if (schema) {
        renderAdapterConfigFields(schema, 'adapter-config-container', currentValues);
    }
}

function renderAdapterConfigFields(schema, containerOrId = 'adapter-config-container', currentValues = {}) {
    const container = typeof containerOrId === 'string' ? document.getElementById(containerOrId) : containerOrId;
    if (!container) return;

    container.innerHTML = '';

    Object.entries(schema).forEach(([key, fieldDef]) => {
        const fieldWrapper = document.createElement('div');
        fieldWrapper.className = 'mb-4';

        const label = document.createElement('label');
        label.className = 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2';
        label.textContent = fieldDef.name || key;

        let input;
        const hasOptions = Array.isArray(fieldDef.options) && fieldDef.options.length > 0;

        if (hasOptions) {
            const select = document.createElement('select');
            select.className = 'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500';
            if (fieldDef.type === 'list') {
                select.multiple = true;
            }
            const placeholderOption = document.createElement('option');
            placeholderOption.value = '';
            placeholderOption.textContent = '';
            if (!select.multiple) {
                select.appendChild(placeholderOption);
            }
            fieldDef.options.forEach(optionValue => {
                const option = document.createElement('option');
                option.value = optionValue;
                option.textContent = optionValue;
                select.appendChild(option);
            });
            input = select;
        } else if (fieldDef.type === 'integer' || fieldDef.type === 'float') {
            input = document.createElement('input');
            input.type = 'number';
            input.className = 'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500';
            if (fieldDef.type === 'float') {
                input.step = 'any';
            } else {
                input.step = '1';
            }
        } else if (fieldDef.type === 'list') {
            input = document.createElement('textarea');
            input.className = 'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500';
            input.rows = 3;
        } else {
            input = document.createElement('input');
            input.type = 'text';
            input.className = 'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500';
        }

        input.id = `adapter-config-${key}`;
        input.setAttribute('data-config-key', key);
        input.setAttribute('data-config-type', fieldDef.type || 'string');

        let value = currentValues[key];
        if (value === undefined || value === null) {
            value = fieldDef.default;
        }

        if (value !== undefined && value !== null) {
            if (input.tagName === 'SELECT') {
                const selectElement = input;
                if (selectElement.multiple && Array.isArray(value)) {
                    Array.from(selectElement.options).forEach(option => {
                        if (value.includes(option.value)) {
                            option.selected = true;
                        }
                    });
                } else {
                    selectElement.value = String(value);
                }
            } else if (input.tagName === 'TEXTAREA' && fieldDef.type === 'list') {
                if (Array.isArray(value)) {
                    input.value = value.join('\n');
                } else if (typeof value === 'string') {
                    input.value = value;
                }
            } else {
                input.value = value;
            }
        }

        if (fieldDef.hint) {
            input.placeholder = fieldDef.hint;
            input.title = fieldDef.hint;
        }

        fieldWrapper.appendChild(label);
        fieldWrapper.appendChild(input);

        if (fieldDef.hint) {
            const hint = document.createElement('p');
            hint.className = 'text-xs text-gray-500 mt-1';
            hint.textContent = fieldDef.hint;
            fieldWrapper.appendChild(hint);
        }

        container.appendChild(fieldWrapper);
    });
}

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
    const platformSelect = document.getElementById('adapter-platform');
    const statusSelect = document.getElementById('adapter-status');
    const configContainer = document.getElementById('adapter-config-container');
    const statusLabel = document.getElementById('adapter-status-label');
    const statusSwitch = document.getElementById('adapter-status-switch');

    if (nameInput) {
        nameInput.value = adapter ? (adapter.name || '') : '';
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

    modal.classList.remove('hidden');
    modal.classList.add('flex');

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
            showNotification('Failed to load adapter platforms', 'error');
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
    const modal = document.getElementById('adapter-modal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    AdapterModalState.mode = 'create';
    AdapterModalState.adapterId = null;
    const configContainer = document.getElementById('adapter-config-container');
    if (configContainer) {
        configContainer.innerHTML = '';
    }
    const platformSelect = document.getElementById('adapter-platform');
    if (platformSelect) {
        platformSelect.disabled = false;
    }
}

async function saveAdapter() {
    const nameInput = document.getElementById('adapter-name');
    const platformSelect = document.getElementById('adapter-platform');
    const statusSelect = document.getElementById('adapter-status');

    const name = nameInput ? nameInput.value.trim() : '';
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

    const config = {};
    const configContainer = document.getElementById('adapter-config-container');
    if (configContainer) {
        const inputs = configContainer.querySelectorAll('[data-config-key]');
        inputs.forEach(input => {
            const key = input.getAttribute('data-config-key');
            const fieldType = input.getAttribute('data-config-type');
            if (!key) return;

            let value;
            if (input.tagName === 'SELECT') {
                const selectElement = input;
                if (selectElement.multiple) {
                    value = Array.from(selectElement.selectedOptions).map(o => o.value).filter(v => v !== '');
                } else {
                    value = selectElement.value;
                }
            } else if (input.tagName === 'TEXTAREA' && fieldType === 'list') {
                const raw = input.value || '';
                value = raw.split('\n').map(s => s.trim()).filter(s => s.length > 0);
            } else {
                value = input.value;
            }

            if (fieldType === 'integer') {
                value = value === '' ? null : parseInt(value, 10);
            } else if (fieldType === 'float') {
                value = value === '' ? null : parseFloat(value);
            } else if (fieldType === 'list') {
                if (!Array.isArray(value)) {
                    const raw = value || '';
                    value = raw.split('\n').flatMap(s => s.split(',')).map(s => s.trim()).filter(s => s.length > 0);
                }
            }

            config[key] = value;
        });
    }

    const payload = {
        name: name,
        platform: platform,
        status: status,
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
                showNotification(errorData.detail || 'Failed to update adapter', 'error');
                return;
            }
        } else {
            const response = await apiCall('/api/adapters', {
                method: 'POST',
                body: JSON.stringify(payload)
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                showNotification(errorData.detail || 'Failed to create adapter', 'error');
                return;
            }
        }

        await loadAdapterData();
        closeAdapterModal();
        showNotification('Adapter saved successfully', 'success');
    } catch (error) {
        console.error('Error saving adapter:', error);
        showNotification('Failed to save adapter', 'error');
    }
}

/**
 * Load persona data
 */
async function loadPersonaData() {
    try {
        // Fetch current persona content from backend
        const response = await apiCall('/api/personas/current/content');
        const data = await response.json();
        
        // Store persona content
        AppState.data.personaContent = data.content || '';
        AppState.data.personaFormat = data.format || 'text';
        
        // Render default persona card
        renderDefaultPersonaCard();
        
        // Initialize persona editor if not already done
        if (!AppState.personaEditor.instance) {
            // Wait a bit for Monaco to load
            setTimeout(() => {
                if (typeof monaco !== 'undefined') {
                    createPersonaEditor();
                }
            }, 100);
        } else {
            // Update editor content
            if (AppState.personaEditor.instance) {
                AppState.personaEditor.instance.setValue(AppState.data.personaContent);
            }
        }
        
        // Update format selector
        const formatSelector = document.getElementById('persona-format');
        if (formatSelector) {
            formatSelector.value = AppState.data.personaFormat || 'text';
        }
    } catch (error) {
        console.error('Error loading persona data:', error);
    }
}

/**
 * Render default persona card
 */
function renderDefaultPersonaCard() {
    const container = document.getElementById('persona-list');
    if (!container) return;
    
    const description = AppState.data.personaContent 
        ? AppState.data.personaContent.substring(0, 150) + (AppState.data.personaContent.length > 150 ? '...' : '')
        : 'No persona content';
    
    const card = `
        <div class="bg-white border border-gray-200 rounded-lg p-6 glass-card cursor-pointer hover:shadow-lg transition-shadow" onclick="editPersona('default')">
            <div class="flex justify-between items-start mb-4">
                <div>
                    <h4 class="text-lg font-semibold text-gray-900">default</h4>
                    <p class="text-sm text-gray-500 mt-1">${escapeHtml(description)}</p>
                </div>
                <div class="flex space-x-2">
                    <button class="text-blue-600 hover:text-blue-900 text-sm" onclick="event.stopPropagation(); editPersona('default')">Edit</button>
                </div>
            </div>
        </div>
    `;
    
    container.innerHTML = `<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">${card}</div>`;
}

/**
 * Render persona list
 */
function renderPersonaList() {
    const container = document.getElementById('persona-list');
    if (!container) return;
    
    if (AppState.data.personas.length === 0) {
        container.innerHTML = `
            <div class="flex justify-center items-center py-12">
                <div class="text-center">
                    <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                    </svg>
                    <p class="text-gray-500" data-i18n="persona.no_personas">No personas configured</p>
                </div>
            </div>
        `;
        if (window.i18n) {
            updateTranslations();
        }
        return;
    }
    
    const cards = AppState.data.personas.map(persona => `
        <div class="bg-white border border-gray-200 rounded-lg p-6 glass-card">
            <div class="flex justify-between items-start mb-4">
                <div>
                    <h4 class="text-lg font-semibold text-gray-900">${escapeHtml(persona.name || 'Unnamed Persona')}</h4>
                    <p class="text-sm text-gray-500 mt-1">${escapeHtml(persona.description || 'No description')}</p>
                </div>
                <div class="flex space-x-2">
                    <button class="text-blue-600 hover:text-blue-900 text-sm" onclick="editPersona('${persona.id || ''}')">Edit</button>
                    <button class="text-red-600 hover:text-red-900 text-sm" onclick="deletePersona('${persona.id || ''}')">Delete</button>
                </div>
            </div>
        </div>
    `).join('');
    
    container.innerHTML = `<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">${cards}</div>`;
}

/**
 * Load configuration data
 */
async function loadConfigurationData() {
    try {
        setupConfigurationTabs();
        const response = await apiCall('/api/configuration');
        const data = await response.json();
        const configuration = data.configuration || {};
        const botConfig = configuration.bot_config || {};
        const modelsConfig = configuration.models || {};
        const providers = data.providers || [];
        const providerModels = data.provider_models || {};
        AppState.data.configuration = configuration;
        AppState.data.configProviders = providers;
        AppState.data.configProviderModels = providerModels;
        populateMessageConfiguration(botConfig);
        populateModelConfiguration(modelsConfig, providers, providerModels);
    } catch (error) {
        console.error('Error loading configuration data:', error);
    }
}

/**
 * Load sessions data
 */
async function loadSessionsData() {
    try {
        const response = await apiCall('/api/sessions');
        const data = await response.json();
        AppState.data.sessions = data.sessions || [];
        
        renderSessionList();
    } catch (error) {
        console.error('Error loading sessions data:', error);
    }
}

/**
 * Render session list
 */
function renderSessionList() {
    const container = document.getElementById('session-list');
    if (!container) return;
    
    if (!AppState.data.sessions || AppState.data.sessions.length === 0) {
        container.innerHTML = `
            <div class="flex justify-center items-center py-12">
                <div class="text-center">
                    <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"></path>
                    </svg>
                    <p class="text-gray-500" data-i18n="sessions.no_sessions">No active sessions</p>
                </div>
            </div>
        `;
        applyTranslations();
        return;
    }
    
    // Get session type label
    const getSessionTypeLabel = (type) => {
        const labels = {
            'dm': getTranslation('sessions.type_dm', 'Direct Message'),
            'gm': getTranslation('sessions.type_gm', 'Group Message'),
            'default': type
        };
        return labels[type] || labels['default'];
    };
    
    // Get session type color
    const getSessionTypeColor = (type) => {
        const colors = {
            'dm': 'bg-blue-100 text-blue-800',
            'gm': 'bg-purple-100 text-purple-800',
            'default': 'bg-gray-100 text-gray-800'
        };
        return colors[type] || colors['default'];
    };
    
    // Build table rows
    const rows = AppState.data.sessions.map(session => {
        const sessionId = session.id || session.session_id || '';
        const adapterName = session.adapter_name || 'Unknown';
        const sessionType = session.session_type || 'unknown';
        const sessionKeyId = session.session_id || 'Unknown';
        const messageCount = session.message_count || 0;
        
        return `
            <tr class="hover:bg-gray-50 dark:hover:bg-gray-800">
                <td class="px-6 py-4 whitespace-nowrap">
                    <div class="text-sm font-medium text-gray-900 dark:text-gray-100">${escapeHtml(adapterName)}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <span class="px-2 py-1 text-xs rounded-full ${getSessionTypeColor(sessionType)}">
                        ${getSessionTypeLabel(sessionType)}
                    </span>
                </td>
                <td class="px-6 py-4">
                    <div class="text-sm text-gray-500 dark:text-gray-400 font-mono break-all max-w-xs">${escapeHtml(sessionKeyId)}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <div class="text-sm text-gray-500 dark:text-gray-400">${messageCount}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
                    <button class="text-blue-600 dark:text-blue-400 hover:text-blue-900 dark:hover:text-blue-300 mr-3" data-i18n="sessions.edit" onclick="editSession('${encodeURIComponent(sessionId)}')">
                        ${getTranslation('sessions.edit', 'Edit')}
                    </button>
                    <button class="text-red-600 dark:text-red-400 hover:text-red-900 dark:hover:text-red-300" data-i18n="sessions.delete" onclick="confirmDeleteSession('${encodeURIComponent(sessionId)}')">
                        ${getTranslation('sessions.delete', 'Delete')}
                    </button>
                </td>
            </tr>
        `;
    }).join('');
    
    // Build table
    const table = `
        <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                <thead class="bg-gray-50 dark:bg-gray-800">
                    <tr>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider" data-i18n="sessions.adapter_name">${getTranslation('sessions.adapter_name', 'Adapter Name')}</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider" data-i18n="sessions.session_type">${getTranslation('sessions.session_type', 'Session Type')}</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider" data-i18n="sessions.session_id">${getTranslation('sessions.session_id', 'Session ID')}</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider" data-i18n="sessions.message_count">${getTranslation('sessions.message_count', 'Messages')}</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider" data-i18n="sessions.actions">${getTranslation('sessions.actions', 'Actions')}</th>
                    </tr>
                </thead>
                <tbody class="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                    ${rows}
                </tbody>
            </table>
        </div>
    `;
    
    container.innerHTML = table;
    
    // Apply translations to data-i18n elements
    applyTranslations();
}

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

/**
 * Load logs data
 */
async function loadLogsData() {
    try {
        // Fetch log configuration from backend to sync with MAX_QUEUE_SIZE
        try {
            const configResponse = await apiCall('/api/log-config');
            const configData = await configResponse.json();
            AppState.data.logConfig.maxQueueSize = configData.maxQueueSize || 100;
        } catch (configError) {
            console.warn('Failed to load log config, using default value:', configError);
            AppState.data.logConfig.maxQueueSize = 100;
        }
        
        // Initialize log level selector
        initLogLevelSelector();
        
        // Load log history
        const response = await apiCall('/api/log-history?limit=100');
        const data = await response.json();
        
        // Initialize log container with history
        const container = document.getElementById('log-container');
        if (container) {
            container.innerHTML = '';
            
            if (data.logs && data.logs.length > 0) {
                data.logs.forEach(log => {
                    addLogEntry(log);
                });
                
                // Scroll to bottom on first load to show latest logs
                container.scrollTop = container.scrollHeight;
            } else {
                container.innerHTML = `
                    <div class="flex justify-center items-center h-full">
                        <p class="text-gray-500" data-i18n="logs.no_logs">No logs available</p>
                    </div>
                `;
                if (window.i18n) {
                    updateTranslations();
                }
            }
        }
        
        // Initialize SSE connection for real-time logs
        initSSEConnection();
    } catch (error) {
        console.error('Error loading logs data:', error);
    }
}

/**
 * Initialize log level selector event listener
 */
function initLogLevelSelector() {
    const selector = document.getElementById('log-level-selector');
    if (selector) {
        // Set initial value from state
        selector.value = AppState.data.logFilter.level || 'all';
        
        // Add change event listener
        selector.addEventListener('change', (e) => {
            const selectedLevel = e.target.value;
            AppState.data.logFilter.level = selectedLevel;
            applyLogFilter();
        });
    }
}

/**
 * Initialize SSE connection for real-time logs
 * Uses EventSourcePolyfill with custom headers, falls back to query parameter auth
 */
function initSSEConnection() {
    // Close existing connection if any
    if (AppState.sseEventSource) {
        AppState.sseEventSource.close();
    }
    
    const jwtToken = localStorage.getItem('jwt_token');
    if (!jwtToken) {
        console.error('No JWT token found for SSE connection');
        return;
    }
    
    try {
        // Try to use EventSourcePolyfill with custom headers first
        if (typeof EventSourcePolyfill !== 'undefined') {
            console.log('Using EventSourcePolyfill with custom headers');
            try {
                AppState.sseEventSource = new EventSourcePolyfill('/api/live-log', {
                    headers: {
                        'Authorization': `Bearer ${jwtToken}`
                    },
                    heartbeatTimeout: 300000,
                    withCredentials: true
                });
                
                // Set up event handlers
                setupSSEEventHandlers(AppState.sseEventSource);
                return;
            } catch (polyfillError) {
                console.warn('EventSourcePolyfill failed, falling back to query parameter auth:', polyfillError);
                // Fall through to fallback strategy
            }
        }
        
        // Fallback: Use standard EventSource with token in query parameter
        console.log('Using fallback strategy: token in query parameter');
        const sseUrl = `/api/live-log?token=${encodeURIComponent(jwtToken)}`;
        AppState.sseEventSource = new EventSource(sseUrl);
        
        // Set up event handlers
        setupSSEEventHandlers(AppState.sseEventSource);
        
    } catch (error) {
        console.error('Error initializing SSE connection:', error);
    }
}

/**
 * Set up event handlers for SSE connection
 * @param {EventSource} eventSource - The EventSource instance
 */
function setupSSEEventHandlers(eventSource) {
    eventSource.onopen = function() {
        console.log('SSE connection established');
    };
    
    eventSource.onmessage = function(event) {
        try {
            const logData = JSON.parse(event.data);
            addLogEntry(logData);
        } catch (e) {
            console.error('Error parsing log data:', e);
        }
    };
    
    eventSource.onerror = function(err) {
        console.error('SSE connection error:', err);
        
        // Check for 401 error (authentication failed)
        if (err && err.status === 401) {
            console.error('Authentication failed (401), token may have expired');
            localStorage.removeItem('jwt_token');
            window.location.href = '/login';
        }
        
        // Close connection on error
        if (AppState.sseEventSource) {
            AppState.sseEventSource.close();
            AppState.sseEventSource = null;
        }
    };
}

/**
 * Add a log entry to the log container
 * @param {object} log - Log data object
 */
function addLogEntry(log) {
    const container = document.getElementById('log-container');
    if (!container) return;
    
    // Parse log data
    const timestamp = log.time || log.timestamp || new Date().toLocaleString();
    const level = log.level || 'INFO';
    const name = log.name || '';
    const message = log.message || log.content || '';
    const color = log.color || 'blue';
    
    // Apply log level filter
    const currentFilter = AppState.data.logFilter.level;
    if (currentFilter !== 'all') {
        const shouldShow = checkLogLevelMatch(level, currentFilter);
        if (!shouldShow) {
            return;  // Skip this log entry if it doesn't match the filter
        }
    }
    
    // Remove "No logs available" message if present
    const noLogsMsg = container.querySelector('[data-i18n="logs.no_logs"]');
    if (noLogsMsg) {
        container.innerHTML = '';
    }
    
    // Determine color class based on level
    let levelClass = 'text-gray-600';
    if (level === 'ERROR' || level === 'CRITICAL') {
        levelClass = 'text-red-600';
    } else if (level === 'WARNING') {
        levelClass = 'text-yellow-600';
    } else if (level === 'INFO') {
        levelClass = 'text-green-600';
    } else if (level === 'DEBUG') {
        levelClass = 'text-cyan-600';
    }
    
    // Create log entry element - all parameters on one line, wrap when overflow
    const logEntry = document.createElement('div');
    logEntry.className = 'font-mono text-base whitespace-normal break-words';
    
    // Format level to 7 characters wide for alignment (WARNING is 7 chars)
    const paddedLevel = escapeHtml(level).padEnd(7, ' ');
    
    // Build log entry with space separators (no gaps between spans)
    let logHtml = `<span class="text-gray-500 dark:text-gray-400">[${escapeHtml(timestamp)}]</span> `;
    logHtml += `<span class="${levelClass} font-semibold whitespace-pre-wrap">${paddedLevel}</span> `;
    if (name) {
        logHtml += `<span style="color: ${color}" class="font-semibold">[${escapeHtml(name)}]</span> `;
    }
    logHtml += `<span class="text-gray-700 dark:text-gray-300 whitespace-pre-wrap">${escapeHtml(message)}</span>`;
    
    logEntry.innerHTML = logHtml;
    
    // Append to container
    container.appendChild(logEntry);
    
    // Smart auto-scroll: only scroll to bottom if user is already at the bottom
    // Calculate scroll position ratio (0 = top, 1 = bottom)
    const scrollRatio = (container.scrollTop + container.clientHeight) / container.scrollHeight;

    // Auto-scroll only if user is near the bottom (ratio > 0.99)
    if (scrollRatio > 0.95) {
        container.scrollTop = container.scrollHeight;
    }
    
    // Limit number of log entries to prevent memory issues
    // Remove oldest entries when exceeding maxQueueSize to maintain performance
    // This value is synced with MAX_QUEUE_SIZE from core/logging_manager.py
    const maxEntries = AppState.data.logConfig.maxQueueSize || 100;
    while (container.children.length > maxEntries) {
        container.removeChild(container.firstChild);
    }
}

/**
 * Check if log level matches the selected filter
 * @param {string} logLevel - The log level from the log entry
 * @param {string} filterLevel - The selected filter level
 * @returns {boolean} - True if the log should be displayed
 */
function checkLogLevelMatch(logLevel, filterLevel) {
    const upperLogLevel = logLevel.toUpperCase();
    const upperFilterLevel = filterLevel.toUpperCase();
    
    switch (upperFilterLevel) {
        case 'ERROR':
            return upperLogLevel === 'ERROR' || upperLogLevel === 'CRITICAL';
        case 'WARNING':
            return upperLogLevel === 'WARNING';
        case 'INFO':
            return upperLogLevel === 'INFO';
        case 'DEBUG':
            return upperLogLevel === 'DEBUG';
        default:
            return false;
    }
}

/**
 * Apply log filter to all existing log entries in the container
 * This function is called when the filter is changed
 */
function applyLogFilter() {
    const container = document.getElementById('log-container');
    if (!container) return;
    
    // Get current filter state
    const currentFilter = AppState.data.logFilter.level;
    
    // If filter is 'all', show all logs
    if (currentFilter === 'all') {
        Array.from(container.children).forEach(child => {
            child.style.display = 'block';
        });
        // Scroll to bottom after showing all logs
        container.scrollTop = container.scrollHeight;
        return;
    }
    
    // Hide/show log entries based on filter
    // Parse each log entry to extract the log level and apply filter
    Array.from(container.children).forEach(child => {
        // Find the level span element (second span in the log entry)
        const levelSpan = child.querySelector('span:nth-child(2)');
        if (levelSpan) {
            const logLevel = levelSpan.textContent.trim();
            const shouldShow = checkLogLevelMatch(logLevel, currentFilter);
            child.style.display = shouldShow ? 'block' : 'none';
        }
    });
    
    // Scroll to bottom after applying filter
    container.scrollTop = container.scrollHeight;
}

/**
 * Render logs (legacy function, kept for compatibility)
 */
function renderLogs() {
    // This function is now handled by loadLogsData and addLogEntry
    console.log('renderLogs called - logs are now rendered via SSE');
}

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
            
            // Update editor theme if editor is active
            if (AppState.editor.instance) {
                AppState.editor.instance.updateOptions({
                    theme: theme === 'dark' ? 'vs-dark' : 'vs'
                });
            }
        });
    }
    
    // Initialize log level selector
    initLogLevelSelector();
    
    document.addEventListener('click', (e) => {
        const target = e.target.closest('button');
        if (!target) return;
        if (target.id === 'configuration-save-button') {
            const configurationPage = document.getElementById('page-configuration');
            if (configurationPage && configurationPage.contains(target) && !configurationPage.classList.contains('hidden')) {
                e.preventDefault();
                saveConfiguration();
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

/**
 * Update runtime duration display in real-time
 */
function updateRuntimeDuration() {
    if (!AppState.data.overview || AppState.data.overview.runtime_duration === undefined) {
        return;
    }
    
    // Calculate elapsed time since last data fetch
    const elapsedSinceFetch = Math.floor((Date.now() - AppState.data.overview.base_timestamp) / 1000);
    const totalSeconds = AppState.data.overview.runtime_duration + elapsedSinceFetch;
    
    // Format the duration as HH:MM:SS
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    
    const formattedDuration = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    
    updateElement('stat-runtime-duration', formattedDuration);
}

/**
 * Update element text content
 * @param {string} id - Element ID
 * @param {string|number} value - Value to set
 */
function updateElement(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.textContent = value;
    }
}

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

/**
 * Show notification
 * @param {string} message - Notification message
 * @param {string} type - Notification type (success, error, info)
 */
function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 px-6 py-4 rounded-lg shadow-lg z-50 ${
        type === 'success' ? 'bg-green-500 text-white' :
        type === 'error' ? 'bg-red-500 text-white' :
        'bg-blue-500 text-white'
    }`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

/**
 * Open provider modal
 */
async function openProviderModal() {
    const modal = document.getElementById('provider-modal');
    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        
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
                showNotification(`Failed to load provider types: ${error.message}`, 'error');
            }
        }
    }
}

/**
 * Close provider modal
 */
function closeProviderModal() {
    const modal = document.getElementById('provider-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
    AppState.selectedProviderId = null;
}

/**
 * Fetch provider schema
 * @param {string} providerType - Type of the provider
 * @returns {Promise<object>} Schema object
 */
async function fetchProviderSchema(providerType) {
    try {
        const response = await apiCall(`/api/providers/schema/${providerType}`);
        return await response.json();
    } catch (error) {
        console.error('Error fetching provider schema:', error);
        showNotification('Failed to load provider schema', 'error');
        return null;
    }
}

/**
 * Load provider schema and render to default container
 */
async function loadProviderSchema(providerType) {
    const schema = await fetchProviderSchema(providerType);
    if (schema) {
        renderProviderConfigFields(schema, 'provider-config-container');
    }
}

/**
 * Render provider config fields based on schema
 * @param {object} schema - The schema definition
 * @param {HTMLElement|string} containerOrId - Container element or ID
 * @param {object} currentValues - Current configuration values (optional)
 */
function renderProviderConfigFields(schema, containerOrId = 'provider-config-container', currentValues = {}) {
    const container = typeof containerOrId === 'string' ? document.getElementById(containerOrId) : containerOrId;
    if (!container) return;
    
    container.innerHTML = '';
    
    // Create fields for each schema item
    Object.entries(schema).forEach(([key, fieldDef]) => {
        const fieldWrapper = document.createElement('div');
        fieldWrapper.className = 'mb-4';
        
        const label = document.createElement('label');
        label.className = 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2';
        label.textContent = key;
        
        let input;
        
        if (fieldDef.type === 'sensitive') {
            input = document.createElement('input');
            input.type = 'password';
            input.className = 'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500';
        } else if (fieldDef.type === 'integer' || fieldDef.type === 'float') {
            input = document.createElement('input');
            input.type = 'number';
            input.className = 'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500';
            if (fieldDef.type === 'float') {
                input.step = 'any';
            } else {
                input.step = '1';
            }
        } else {
            // Default to text for string and others
            input = document.createElement('input');
            input.type = 'text';
            input.className = 'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500';
        }
        
        // Set common attributes
        input.id = `config-${key}`;
        input.setAttribute('data-config-key', key);
        input.setAttribute('data-config-type', fieldDef.type);
        
        // Determine value: currentValues > default > ''
        let value = currentValues[key];
        if (value === undefined || value === null) {
            value = fieldDef.default;
        }
        
        if (value !== undefined && value !== null) {
            input.value = value;
        }
        
        if (fieldDef.hint) {
            input.placeholder = fieldDef.hint;
            input.title = fieldDef.hint;
        }
        
        fieldWrapper.appendChild(label);
        fieldWrapper.appendChild(input);
        
        // Add hint text if available
        if (fieldDef.hint) {
            const hint = document.createElement('p');
            hint.className = 'text-xs text-gray-500 mt-1';
            hint.textContent = fieldDef.hint;
            fieldWrapper.appendChild(hint);
        }
        
        container.appendChild(fieldWrapper);
    });
}

/**
 * Save provider
 */
async function saveProvider() {
    const name = document.getElementById('provider-name').value.trim();
    const typeSelect = document.getElementById('provider-type');
    const type = typeSelect ? typeSelect.value : '';
    
    if (!name) {
        showNotification('Please enter provider name', 'error');
        return;
    }
    
    if (!type) {
        showNotification('Please select provider type', 'error');
        return;
    }
    
    // Collect dynamic config
    const config = {};
    const configContainer = document.getElementById('provider-config-container');
    if (configContainer) {
        const inputs = configContainer.querySelectorAll('input[data-config-key]');
        inputs.forEach(input => {
            const key = input.getAttribute('data-config-key');
            const fieldType = input.getAttribute('data-config-type');
            
            if (key) {
                let value = input.value;
                if (fieldType === 'integer') {
                    value = value === '' ? null : parseInt(value, 10);
                } else if (fieldType === 'float') {
                    value = value === '' ? null : parseFloat(value);
                }
                config[key] = value;
            }
        });
    }
    
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
            showNotification('Provider added successfully', 'success');
        } else {
            const errorData = await response.json();
            showNotification(errorData.detail || 'Failed to add provider', 'error');
        }
    } catch (error) {
        console.error('Error saving provider:', error);
        showNotification('Error saving provider', 'error');
    }
}

/**
 * Placeholder functions for edit/delete actions
 */
function editProvider(id) {
    showNotification('Edit provider functionality coming soon', 'info');
}

function deleteProvider(id) {
    if (confirm('Are you sure you want to delete this provider?')) {
        apiCall(`/api/providers/${id}`, { method: 'DELETE' })
            .then(() => {
                showNotification('Provider deleted successfully', 'success');
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
            })
            .catch(error => {
                console.error('Error deleting provider:', error);
                showNotification('Failed to delete provider', 'error');
            });
    }
}

function editAdapter(id) {
    const adapter = AppState.data.adapters.find(a => a.id === id);
    if (!adapter) {
        showNotification('Adapter not found', 'error');
        return;
    }
    openAdapterModal(adapter);
}

async function deleteAdapter(id) {
    if (!id) return;
    if (!confirm('Are you sure you want to delete this adapter?')) {
        return;
    }
    try {
        const response = await apiCall(`/api/adapters/${encodeURIComponent(id)}`, {
            method: 'DELETE'
        });
        if (response.status === 204 || response.status === 200) {
            AppState.data.adapters = AppState.data.adapters.filter(a => a.id !== id);
            renderAdapterList();
            showNotification('Adapter deleted successfully', 'success');
        } else {
            const errorData = await response.json().catch(() => ({}));
            showNotification(errorData.detail || 'Failed to delete adapter', 'error');
        }
    } catch (error) {
        console.error('Error deleting adapter:', error);
        showNotification('Failed to delete adapter', 'error');
    }
}

function editPersona(id) {
    // Open persona modal for editing
    openPersonaModal();
}

function deletePersona(id) {
    if (confirm('Are you sure you want to delete this persona?')) {
        showNotification('Delete persona functionality coming soon', 'info');
    }
}

/**
 * Session management functions
 */

// Session editor state
const sessionEditorState = {
    instance: null,
    currentSessionId: null,
    sessionData: null
};

/**
 * Edit session - opens modal with Monaco editor
 * @param {string} encodedSessionId - URL-encoded session ID
 */
async function editSession(encodedSessionId) {
    const sessionId = decodeURIComponent(encodedSessionId);
    
    try {
        // Fetch session data from backend
        const response = await apiCall(`/api/sessions/${encodeURIComponent(sessionId)}`);
        const data = await response.json();
        
        // Store session data
        sessionEditorState.currentSessionId = sessionId;
        sessionEditorState.sessionData = data;
        
        // Update modal fields
        document.getElementById('session-adapter-name').value = data.adapter_name || '';
        document.getElementById('session-type').value = data.session_type || '';
        document.getElementById('session-id').value = data.session_id || '';
        document.getElementById('session-modal-subtitle').textContent = sessionId;
        
        // Update message count
        const messageCount = data.messages ? data.messages.length : 0;
        document.getElementById('session-message-count').textContent = 
            (window.i18n ? window.i18n.t('sessions.message_count') : 'Messages') + ': ' + messageCount;
        
        // Show modal
        const modal = document.getElementById('session-modal');
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        
        // Initialize Monaco editor for session data
        await initializeSessionEditor(data.messages || []);
        
    } catch (error) {
        console.error('Error loading session:', error);
        showNotification('Failed to load session data', 'error');
    }
}

/**
 * Initialize Monaco editor for session editing
 * @param {Array} messages - Array of message objects
 */
async function initializeSessionEditor(messages) {
    // Wait for Monaco to load if not already loaded
    if (typeof monaco === 'undefined') {
        await new Promise(resolve => {
            const checkMonaco = setInterval(() => {
                if (typeof monaco !== 'undefined') {
                    clearInterval(checkMonaco);
                    resolve();
                }
            }, 100);
        });
    }
    
    const container = document.getElementById('session-editor-container');
    if (!container) return;
    
    // Dispose of existing editor if any
    if (sessionEditorState.instance) {
        sessionEditorState.instance.dispose();
    }
    
    // Format messages as JSON for editing
    // Display raw JSON content to ensure consistency with file storage
    // This allows users to see exactly what is stored (e.g., [] vs [[]])
    const formattedContent = JSON.stringify(messages, null, 2);
    
    // Create new editor instance
    sessionEditorState.instance = monaco.editor.create(container, {
        value: formattedContent,
        language: 'json',
        theme: document.documentElement.classList.contains('dark') ? 'vs-dark' : 'vs',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        fontSize: 13,
        wordWrap: 'on',
        lineNumbers: 'on',
        folding: true,
        bracketPairColorization: { enabled: true }
    });
}

/**
 * Close session modal
 */
function closeSessionModal() {
    const modal = document.getElementById('session-modal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    
    // Dispose editor instance
    if (sessionEditorState.instance) {
        sessionEditorState.instance.dispose();
        sessionEditorState.instance = null;
    }
    
    // Clear state
    sessionEditorState.currentSessionId = null;
    sessionEditorState.sessionData = null;
}

/**
 * Save session data
 */
async function saveSession() {
    if (!sessionEditorState.currentSessionId) {
        showNotification('No session selected', 'error');
        return;
    }
    
    try {
        // Get content from editor
        const content = sessionEditorState.instance.getValue();
        
        // Parse JSON
        let messages;
        try {
            // Check if content is empty or whitespace only
            const trimmedContent = content.trim();
            if (!trimmedContent) {
                messages = [];
            } else if (trimmedContent === '[]') {
                // Special case: User explicitly entered [] or it was loaded as [] to represent empty memory
                messages = [];
            } else {
                // Smart parsing logic:
                // 1. Try to parse directly first (in case user entered a full JSON array [[...]])
                // 2. If that fails or isn't a list of lists, try wrapping in [] (assuming user entered chunks list [...], [...])
                
                let parsed = null;
                let directParseSuccess = false;
                
                try {
                    parsed = JSON.parse(trimmedContent);
                    // Check if it's a valid list of lists
                    if (Array.isArray(parsed) && parsed.every(item => Array.isArray(item))) {
                        messages = parsed;
                        directParseSuccess = true;
                    }
                } catch (e) {
                    // Direct parse failed, proceed to wrapped parse
                }
                
                if (!directParseSuccess) {
                    // Try wrapping in brackets
                    messages = JSON.parse(`[${content}]`);
                }
            }
        } catch (parseError) {
            console.error('JSON Parse Error:', parseError);
            showNotification('Invalid JSON format: ' + parseError.message, 'error');
            return;
        }
        
        // Validate messages array
        if (!Array.isArray(messages)) {
            showNotification('Messages must be an array', 'error');
            return;
        }

        // Validate that every item in the array is also an array (chunk)
        if (!messages.every(item => Array.isArray(item))) {
            showNotification('Invalid structure: content must be a list of message lists (chunks)', 'error');
            return;
        }
        
        // Send update request to backend
        const response = await apiCall(`/api/sessions/${encodeURIComponent(sessionEditorState.currentSessionId)}`, {
            method: 'PUT',
            body: JSON.stringify({ messages })
        });
        
        if (response.ok) {
            showNotification('Session saved successfully', 'success');
            closeSessionModal();
            // Reload session list
            await loadSessionsData();
        } else {
            showNotification('Failed to save session', 'error');
        }
    } catch (error) {
        console.error('Error saving session:', error);
        showNotification('Failed to save session', 'error');
    }
}

/**
 * Confirm delete session - shows confirmation modal
 * @param {string} encodedSessionId - URL-encoded session ID
 */
function confirmDeleteSession(encodedSessionId) {
    const sessionId = decodeURIComponent(encodedSessionId);
    sessionEditorState.currentSessionId = sessionId;
    
    const modal = document.getElementById('delete-modal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

/**
 * Close delete confirmation modal
 */
function closeDeleteModal() {
    const modal = document.getElementById('delete-modal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    sessionEditorState.currentSessionId = null;
}

/**
 * Execute delete session
 */
async function executeDeleteSession() {
    if (!sessionEditorState.currentSessionId) {
        closeDeleteModal();
        return;
    }
    
    try {
        const response = await apiCall(`/api/sessions/${encodeURIComponent(sessionEditorState.currentSessionId)}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showNotification('Session deleted successfully', 'success');
            closeDeleteModal();
            // Reload session list
            await loadSessionsData();
        } else {
            showNotification('Failed to delete session', 'error');
        }
    } catch (error) {
        console.error('Error deleting session:', error);
        showNotification('Failed to delete session', 'error');
    }
}

/**
 * Initialize Monaco Editor
 */
function initializeMonacoEditor() {
    // Set up Monaco Editor loader
    require.config({ paths: { 'vs': 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs' }});
    
    // Load Monaco Editor
    require(['vs/editor/editor.main'], function() {
        // Set up the editor when the configuration page is loaded
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
    
    // Dispose of existing editor if any
    if (AppState.editor.instance) {
        AppState.editor.instance.dispose();
    }
    
    // Create new editor instance
    AppState.editor.instance = monaco.editor.create(container, {
        value: AppState.editor.files[AppState.editor.currentFile]?.content || '',
        language: AppState.editor.currentFormat,
        theme: document.documentElement.classList.contains('dark') ? 'vs-dark' : 'vs',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        fontSize: 14,
        wordWrap: 'on',
        folding: true,
        lineNumbers: 'on',
        renderWhitespace: 'selection'
    });
    
    // Update editor status
    updateEditorStatus();
    
    // Set up editor change event
    AppState.editor.instance.onDidChangeModelContent(() => {
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
            if (AppState.editor.instance) {
                monaco.editor.setModelLanguage(AppState.editor.instance.getModel(), AppState.editor.currentFormat);
            }
            updateEditorStatus();
        });
    }
    
    // Copy button
    const copyButton = document.getElementById('editor-copy');
    if (copyButton) {
        copyButton.addEventListener('click', () => {
            if (AppState.editor.instance) {
                navigator.clipboard.writeText(AppState.editor.instance.getValue());
                showNotification(window.i18n ? window.i18n.t('configuration.copied') : 'Content copied to clipboard', 'success');
            }
        });
    }
    
    // Download button
    const downloadButton = document.getElementById('editor-download');
    if (downloadButton) {
        downloadButton.addEventListener('click', () => {
            if (AppState.editor.instance && AppState.editor.currentFile) {
                const content = AppState.editor.instance.getValue();
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
    if (AppState.editor.instance) {
        AppState.editor.instance.setValue(AppState.editor.files[fileName].content);
        monaco.editor.setModelLanguage(AppState.editor.instance.getModel(), AppState.editor.currentFormat);
    }
    
    updateEditorStatus();
}

/**
 * Save the current file
 */
function saveCurrentFile() {
    if (!AppState.editor.instance || !AppState.editor.currentFile) return;
    
    const content = AppState.editor.instance.getValue();
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

/**
 * Logs management functions
 */
function clearLogs() {
    if (confirm('Are you sure you want to clear all logs?')) {
        const container = document.getElementById('log-container');
        if (container) {
            container.innerHTML = `
                <div class="flex justify-center items-center h-full">
                    <p class="text-gray-500" data-i18n="logs.no_logs">No logs available</p>
                </div>
            `;
            if (window.i18n) {
                updateTranslations();
            }
        }
        showNotification('Logs cleared', 'success');
    }
}

function refreshLogs() {
    // Close existing SSE connection
    if (AppState.sseEventSource) {
        AppState.sseEventSource.close();
        AppState.sseEventSource = null;
    }
    
    // Reload logs data
    loadLogsData();
    showNotification('Logs refreshed', 'success');
}

// Export for global access
window.AppState = AppState;
window.switchPage = switchPage;
window.loadPageData = loadPageData;

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

/**
 * Render provider configuration fields based on schema
 * @param {object} schema - The provider schema
 * @param {HTMLElement} container - The container element
 * @param {object} [currentConfig] - Current configuration values (optional)
 */
function renderProviderConfigFields(schema, container, currentConfig = {}) {
    container.innerHTML = '';
    
    if (!schema || Object.keys(schema).length === 0) {
        container.innerHTML = '<div class="text-gray-500 py-2">No configuration required</div>';
        return;
    }
    
    // Sort keys or iterate
    const providerConfigSchema = schema.provider_config || schema; // Handle if schema is nested or flat

    Object.entries(providerConfigSchema).forEach(([key, field]) => {
        // Skip internal keys if any
        if (key.startsWith('_')) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'mb-4';
        
        const label = document.createElement('label');
        label.className = 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1';
        label.textContent = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        wrapper.appendChild(label);
        
        let input;
        const fieldType = field.type || 'string';
        const currentValue = currentConfig[key] !== undefined ? currentConfig[key] : field.default;
        
        if (fieldType === 'sensitive') {
            input = document.createElement('input');
            input.type = 'password';
        } else if (fieldType === 'integer') {
            input = document.createElement('input');
            input.type = 'number';
            input.step = '1';
        } else if (fieldType === 'float') {
            input = document.createElement('input');
            input.type = 'number';
            input.step = 'any';
        } else {
            input = document.createElement('input');
            input.type = 'text';
        }
        
        input.className = 'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500';
        input.setAttribute('data-config-key', key);
        input.setAttribute('data-config-type', fieldType);
        
        if (currentValue !== undefined && currentValue !== null) {
            input.value = currentValue;
        }
        
        if (field.hint) {
            input.placeholder = field.hint;
        }
        
        wrapper.appendChild(input);
        
        if (field.hint) {
            const hint = document.createElement('p');
            hint.className = 'text-xs text-gray-500 dark:text-gray-400 mt-1';
            hint.textContent = field.hint;
            wrapper.appendChild(hint);
        }
        
        container.appendChild(wrapper);
    });
}

/**
 * Close provider modal
 */
function closeProviderModal() {
    const modal = document.getElementById('provider-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

/**
 * Save provider
 */
async function saveProvider() {
    const name = document.getElementById('provider-name').value.trim();
    const type = document.getElementById('provider-type').value;
    
    if (!name) {
        showNotification('Please enter provider name', 'error');
        return;
    }
    
    if (!type) {
        showNotification('Please select provider type', 'error');
        return;
    }
    
    // Collect dynamic config
    const config = {};
    const configContainer = document.getElementById('provider-config-container');
    if (configContainer) {
        const inputs = configContainer.querySelectorAll('input[data-config-key]');
        inputs.forEach(input => {
            const key = input.getAttribute('data-config-key');
            const fieldType = input.getAttribute('data-config-type');
            
            if (key) {
                let value = input.value;
                if (fieldType === 'integer') {
                    value = value === '' ? null : parseInt(value, 10);
                } else if (fieldType === 'float') {
                    value = value === '' ? null : parseFloat(value);
                }
                config[key] = value;
            }
        });
    }
    
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
            showNotification('Provider added successfully', 'success');
        } else {
            const errorData = await response.json();
            showNotification(errorData.detail || 'Failed to add provider', 'error');
        }
    } catch (error) {
        console.error('Error saving provider:', error);
        showNotification('Error saving provider', 'error');
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
                    ${modelGroups.map(group => `
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
        showNotification('Provider not found', 'error');
        return;
    }

    const config = {};
    const inputs = detailsContainer.querySelectorAll('input[data-config-key]');
    inputs.forEach(input => {
        const key = input.getAttribute('data-config-key');
        const fieldType = input.getAttribute('data-config-type');
        
        if (key) {
            let value = input.value;
            if (fieldType === 'integer') {
                value = value === '' ? null : parseInt(value, 10);
            } else if (fieldType === 'float') {
                value = value === '' ? null : parseFloat(value);
            }
            config[key] = value;
        }
    });

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
    const modal = document.getElementById('model-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    const modelIdInput = document.getElementById('model-id');
    if (modelIdInput) {
        if (modelId) {
            modelIdInput.value = modelId;
            modelIdInput.disabled = true;
        } else {
            modelIdInput.value = '';
            modelIdInput.disabled = false;
        }
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

function closeModelModal() {
    const modal = document.getElementById('model-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
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
        modelId = modelIdInput.value.trim();
        if (!modelId) {
            showNotification(getTranslation('model.id_required', 'Model ID is required'), 'error');
            return;
        }
    }
    const configContainer = document.getElementById('model-config-container');
    const config = {};
    if (configContainer) {
        const inputs = configContainer.querySelectorAll('input[data-config-key]');
        inputs.forEach(input => {
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
    }
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
        showNotification(`Provider ${provider.status === 'active' ? 'enabled' : 'disabled'}`, 'success');
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

/**
 * Open persona modal
 */
function openPersonaModal() {
    const modal = document.getElementById('persona-modal');
    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        
        // Set format selector to current format
        document.getElementById('persona-format').value = AppState.data.personaFormat || 'text';
        
        // Initialize persona editor with existing content
        setTimeout(() => {
            createPersonaEditor();
            // Load existing content into editor
            if (AppState.personaEditor.instance && AppState.data.personaContent) {
                AppState.personaEditor.instance.setValue(AppState.data.personaContent);
            }
            // Force layout recalculation
            setTimeout(() => {
                if (AppState.personaEditor.instance) {
                    AppState.personaEditor.instance.layout();
                }
            }, 50);
        }, 100);
    }
}

/**
 * Close persona modal
 */
function closePersonaModal() {
    const modal = document.getElementById('persona-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        
        // Dispose editor instance
        if (AppState.personaEditor.instance) {
            AppState.personaEditor.instance.dispose();
            AppState.personaEditor.instance = null;
        }
    }
}

/**
 * Create persona editor instance
 */
function createPersonaEditor() {
    const container = document.getElementById('persona-editor-container');
    if (!container) return;
    
    // Dispose of existing editor if any
    if (AppState.personaEditor.instance) {
        AppState.personaEditor.instance.dispose();
    }
    
    // Get default content based on format
    const format = document.getElementById('persona-format').value;
    const defaultContent = getDefaultPersonaContent(format);
    
    // Create new editor instance
    AppState.personaEditor.instance = monaco.editor.create(container, {
        value: defaultContent,
        language: format === 'markdown' ? 'markdown' : format,
        theme: document.documentElement.classList.contains('dark') ? 'vs-dark' : 'vs',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        fontSize: 14,
        wordWrap: 'on',
        folding: true,
        lineNumbers: 'on',
        renderWhitespace: 'selection'
    });
    
    AppState.personaEditor.format = format;
    
    // Set up format change listener
    const formatSelector = document.getElementById('persona-format');
    if (formatSelector) {
        formatSelector.onchange = null; // Remove any existing listener
        formatSelector.onchange = function() {
            const newFormat = this.value;
            const newContent = getDefaultPersonaContent(newFormat);
            
            if (AppState.personaEditor.instance) {
                AppState.personaEditor.instance.setValue(newContent);
                monaco.editor.setModelLanguage(AppState.personaEditor.instance.getModel(), 
                    newFormat === 'markdown' ? 'markdown' : newFormat);
            }
            AppState.personaEditor.format = newFormat;
        };
    }
}

/**
 * Get default persona content based on format
 * @param {string} format - Format type
 * @returns {string} Default content
 */
function getDefaultPersonaContent(format) {
    switch (format) {
        case 'json':
            return '{\n  "name": "My Persona",\n  "description": "A helpful AI assistant",\n  "traits": ["friendly", "knowledgeable"],\n  "instructions": "You are a helpful AI assistant."\n}';
        case 'yaml':
            return 'name: My Persona\ndescription: A helpful AI assistant\ntraits:\n  - friendly\n  - knowledgeable\ninstructions: You are a helpful AI assistant.';
        case 'markdown':
            return '# My Persona\n\n## Description\nA helpful AI assistant\n\n## Traits\n- Friendly\n- Knowledgeable\n\n## Instructions\nYou are a helpful AI assistant.';
        case 'text':
            return 'My Persona\n\nDescription: A helpful AI assistant\n\nTraits: Friendly, Knowledgeable\n\nInstructions: You are a helpful AI assistant.';
        default:
            return '';
    }
}

/**
 * Create Monaco Editor instance for persona
 */
function createPersonaEditor() {
    const container = document.getElementById('persona-editor-container');
    if (!container) return;
    
    // Dispose of existing editor if any
    if (AppState.personaEditor.instance) {
        AppState.personaEditor.instance.dispose();
    }
    
    // Create new editor instance
    AppState.personaEditor.instance = monaco.editor.create(container, {
        value: AppState.data.personaContent || '',
        language: AppState.data.personaFormat || 'text',
        theme: document.documentElement.classList.contains('dark') ? 'vs-dark' : 'vs',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        fontSize: 14,
        wordWrap: 'on',
        folding: true,
        lineNumbers: 'on',
        renderWhitespace: 'selection'
    });
    
    // Set up format selector change event
    const formatSelector = document.getElementById('persona-format');
    if (formatSelector) {
        formatSelector.addEventListener('change', (e) => {
            AppState.data.personaFormat = e.target.value;
            if (AppState.personaEditor.instance) {
                monaco.editor.setModelLanguage(AppState.personaEditor.instance.getModel(), AppState.data.personaFormat);
            }
        });
    }
}

/**
 * Save persona
 */
async function savePersona() {
    // Get content from editor
    let content = '';
    if (AppState.personaEditor.instance) {
        content = AppState.personaEditor.instance.getValue();
    }
    
    if (!content.trim()) {
        showNotification('Please enter persona content', 'error');
        return;
    }
    
    try {
        // Save persona content to backend
        const response = await apiCall('/api/personas/current/content', {
            method: 'PUT',
            body: JSON.stringify({
                content: content
            })
        });
        
        if (response.ok) {
            // Update local state
            AppState.data.personaContent = content;
            
            // Show success notification
            showNotification('Persona saved successfully', 'success');
        } else {
            showNotification('Failed to save persona', 'error');
        }
    } catch (error) {
        console.error('Error saving persona:', error);
        showNotification('Error saving persona', 'error');
    }
}

// Export persona functions
window.openPersonaModal = openPersonaModal;
window.closePersonaModal = closePersonaModal;
window.savePersona = savePersona;
