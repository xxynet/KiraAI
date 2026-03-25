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

// ---------------------------------------------------------------------------
// Monaco file editor (within the configuration page)
// ---------------------------------------------------------------------------

/** Initialize Monaco editor — attaches callback for when Monaco is ready */
function initializeMonacoEditor() {
    Monaco.load().then(() => {
        if (AppState.currentPage === 'configuration') {
            createEditor();
        }
    });
}

/** Create the Monaco editor instance for the file editor */
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
        updateEditorStatus(true); // true = unsaved changes
    });
}

/** Set up file-editor toolbar event listeners */
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
 * Load a file into the Monaco editor.
 * @param {string} fileName
 */
function loadFile(fileName) {
    if (!AppState.editor.files[fileName]) return;

    AppState.editor.currentFile = fileName;
    AppState.editor.currentFormat = AppState.editor.files[fileName].format;

    const formatSelector = document.getElementById('format-selector');
    if (formatSelector) {
        formatSelector.value = AppState.editor.currentFormat;
    }

    if (Monaco.get('config')) {
        Monaco.get('config').setValue(AppState.editor.files[fileName].content);
        Monaco.setLanguage('config', AppState.editor.currentFormat);
    }

    updateEditorStatus();
}

/** Save the current file content from the editor back to AppState */
function saveCurrentFile() {
    if (!Monaco.get('config') || !AppState.editor.currentFile) return;

    const content = Monaco.getValue('config');
    AppState.editor.files[AppState.editor.currentFile].content = content;

    updateEditorStatus(false);
    showNotification(window.i18n ? window.i18n.t('configuration.saved') : 'File saved successfully', 'success');
}

/** Prompt for a filename and create a new file with default content */
function createNewFile() {
    const fileName = prompt(window.i18n ? window.i18n.t('configuration.enter_filename') : 'Enter filename:');
    if (!fileName) return;

    const format = fileName.split('.').pop().toLowerCase();
    const supportedFormats = ['ini', 'json', 'md', 'xml'];

    if (!supportedFormats.includes(format)) {
        showNotification(window.i18n ? window.i18n.t('configuration.unsupported_format') : 'Unsupported file format', 'error');
        return;
    }

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

    AppState.editor.files[fileName] = { content: defaultContent, format };
    updateFileSelector();
    loadFile(fileName);
}

/** Refresh file list (placeholder — currently shows notification only) */
function refreshFileList() {
    showNotification(window.i18n ? window.i18n.t('configuration.refreshed') : 'File list refreshed', 'info');
}

/** Rebuild file selector dropdown from AppState.editor.files */
function updateFileSelector() {
    const fileSelector = document.getElementById('file-selector');
    if (!fileSelector) return;

    // Remove all options except the first placeholder
    while (fileSelector.children.length > 1) {
        fileSelector.removeChild(fileSelector.lastChild);
    }

    Object.keys(AppState.editor.files).forEach(fileName => {
        const option = document.createElement('option');
        option.value = fileName;
        option.textContent = fileName;
        option.setAttribute('data-format', AppState.editor.files[fileName].format);
        fileSelector.appendChild(option);
    });

    if (AppState.editor.currentFile) {
        fileSelector.value = AppState.editor.currentFile;
    }
}

/**
 * Update the editor status bar text.
 * @param {boolean} hasChanges - Whether there are unsaved changes
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
