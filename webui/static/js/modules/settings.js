/**
 * Settings & configuration domain module
 * Handles i18n utilities, theme management, settings page load/save,
 * the configuration page (ConfigurationManager + legacy fallback),
 * and the file editor within the configuration page.
 *
 * Dependencies (loaded before this file):
 *   core/state.js    — AppState
 *   core/api.js      — apiCall
 *   core/notify.js   — showNotification
 *   core/monaco.js   — Monaco
 */

// ---------------------------------------------------------------------------
// i18n utilities
// ---------------------------------------------------------------------------

/**
 * Get a translated string with a fallback.
 * @param {string} key      - i18n key
 * @param {string} fallback - text to return when key is missing
 * @returns {string}
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

/** Apply translations to all [data-i18n] elements in the DOM */
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

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

/**
 * Apply a theme to the application.
 * @param {string} theme - 'light' or 'dark'
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

    // Persist choice
    localStorage.setItem('theme', theme);

    // Keep theme selector in sync
    const themeSelect = document.getElementById('settings-theme');
    if (themeSelect) {
        themeSelect.value = theme;
    }

    // Sync all Monaco editor instances to the new theme
    Monaco.syncTheme();
}

// ---------------------------------------------------------------------------
// Settings page
// ---------------------------------------------------------------------------

async function loadSettingsData() {
    try {
        const response = await apiCall('/api/settings');
        const data = await response.json();
        AppState.data.settings = data.settings || {};

        const languageSelect = document.getElementById('settings-language');
        const themeSelect = document.getElementById('settings-theme');

        if (languageSelect && data.settings.language) {
            languageSelect.value = data.settings.language;
        }

        if (themeSelect && data.settings.theme) {
            themeSelect.value = data.settings.theme;
        }

        applyTheme(data.settings.theme || 'light');

    } catch (error) {
        console.error('Error loading settings data:', error);
    }
}

async function saveSettings() {
    try {
        const language = document.getElementById('settings-language')?.value;
        const theme = document.getElementById('settings-theme')?.value;

        const response = await apiCall('/api/settings', {
            method: 'POST',
            body: JSON.stringify({ language, theme })
        });

        const data = await response.json();

        if (data.status === 'ok') {
            showNotification(window.i18n ? window.i18n.t('settings.saved') : 'Settings saved successfully', 'success');
            applyTheme(theme);
        } else {
            showNotification('Failed to save settings', 'error');
        }
    } catch (error) {
        console.error('Error saving settings:', error);
        showNotification('Error saving settings', 'error');
    }
}

// loadConfigurationData, _bindConfigToolbarEvents → modules/config.js

// ---------------------------------------------------------------------------
// Configuration page — tabs (message / model)
// ---------------------------------------------------------------------------

/**
 * Initialize configuration page tabs (Message / Model).
 * Idempotent — skips if already initialized.
 */
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

// ---------------------------------------------------------------------------
// Legacy configuration save (fallback when configManager is unavailable)
// ---------------------------------------------------------------------------

/**
 * Read a text input value by element ID.
 * @param {string} id
 * @returns {string}
 */
function getInputValue(id) {
    const el = document.getElementById(id);
    if (!el) {
        return '';
    }
    return String(el.value || '').trim();
}

/** Populate legacy message-configuration form fields from bot config object */
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

/** Legacy configuration save — only called when configManager is not available */
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

