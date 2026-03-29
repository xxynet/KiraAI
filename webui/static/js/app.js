/**
 * Main application entry point for KiraAI Admin Panel
 * Handles page navigation, initialization, and global event wiring.
 *
 * Extracted modules (loaded via index.html <script> tags before this file):
 *   core/state.js          — AppState
 *   core/api.js            — apiCall
 *   core/notify.js         — showNotification
 *   core/modal.js          — Modal
 *   core/monaco.js         — Monaco
 *   core/state.js          — AppState
 *   shared/render-config-fields.js — renderConfigFields, collectConfigFromContainer,
 *                                    validateConfigFieldInput
 *   modules/overview.js    — loadOverviewData, updateRuntimeDuration
 *   modules/log.js         — loadLogsData, clearLogs, refreshLogs, initLogLevelSelector
 *   modules/sticker.js     — loadStickerData
 *   modules/persona.js     — loadPersonaData, openPersonaModal
 *   modules/session.js     — loadSessionsData
 *   modules/plugin.js      — loadPluginData, setupPluginTabs, PluginConfigModalState,
 *                             mcpEditorState, closeMcpConfigModal, saveMcpConfig,
 *                             closePluginConfigModal, savePluginConfig
 *   modules/adapter.js     — loadAdapterData, openAdapterModal, closeAdapterModal,
 *                             saveAdapter, AdapterModalState
 *   modules/provider.js    — loadProviderData, openProviderModal, closeProviderModal,
 *                             saveProvider, selectProvider, closeModelModal, saveModel
 *   modules/settings.js    — loadSettingsData, saveSettings, applyTheme,
 *                             getTranslation, applyTranslations,
 *                             loadConfigurationData, setupConfigurationTabs
 */

document.addEventListener('DOMContentLoaded', () => {
    initializeApp();
});

/**
 * Initialize all application components.
 */
function initializeApp() {
    // Apply saved theme before any rendering
    const savedTheme = localStorage.getItem('theme') || 'light';
    applyTheme(savedTheme);

    setupThemeToggle();
    setupNavigation();
    loadAppVersion();
    loadInitialData();
    setupEventListeners();
    startAutoRefresh();
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
 * Set up navigation between pages.
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

    switchPage('overview');
}

/**
 * Switch to a different page.
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

    AppState.currentPage = pageName;

    loadPageData(pageName);
}

/**
 * Load data for a specific page.
 * @param {string} pageName
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

/**
 * Set up global event listeners.
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

    // Configuration save button — delegates to configManager only (no legacy fallback)
    document.addEventListener('click', (e) => {
        const target = e.target.closest('button');
        if (!target || target.id !== 'configuration-save-button') return;
        const configurationPage = document.getElementById('page-configuration');
        if (configurationPage && configurationPage.contains(target) && !configurationPage.classList.contains('hidden')) {
            e.preventDefault();
            saveConfigurationPage();
        }
    });

    // Register data-action handlers via EventRouter
    EventRouter.on('add-provider',  () => openProviderModal());
    EventRouter.on('add-adapter',   () => openAdapterModal());
    EventRouter.on('new-session',   () => showNotification('New session functionality coming soon', 'info'));
    EventRouter.on('clear-logs',    () => clearLogs());
    EventRouter.on('refresh-logs',  () => refreshLogs());
    EventRouter.on('download-logs', () => downloadLogs());
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
 * Start auto-refresh timers for the overview page.
 */
function startAutoRefresh() {
    // Refresh overview data every 30 seconds
    AppState.refreshInterval = setInterval(() => {
        if (AppState.currentPage === 'overview') {
            loadOverviewData();
        }
    }, 30000);

    // Update runtime duration every second
    AppState.runtimeInterval = setInterval(() => {
        if (AppState.currentPage === 'overview') {
            updateRuntimeDuration();
        }
    }, 1000);
}

/**
 * Escape HTML to prevent XSS.
 * @param {string} text
 * @returns {string}
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Delete confirmation modal wrappers (used by multiple modules)
// ---------------------------------------------------------------------------

function openDeleteModal(title, message, onConfirm) { Modal.confirm(title, message, onConfirm); }
async function confirmDelete() { await Modal.confirmExecute(); }
function closeDeleteModal() { Modal.confirmClose(); }

// ---------------------------------------------------------------------------
// Global exports
// ---------------------------------------------------------------------------

window.AppState = AppState;
window.switchPage = switchPage;
window.loadPageData = loadPageData;
window.apiCall = apiCall;
window.showNotification = showNotification;
