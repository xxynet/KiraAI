/**
 * Configuration page module
 * Centralises ConfigurationManager integration: load, toolbar binding,
 * and the save-button handler (no legacy fallback).
 *
 * This module replaces the legacy saveConfiguration / populateMessageConfiguration
 * / buildModelsConfiguration path — all configuration is handled by configManager.
 *
 * Dependencies (loaded before this file):
 *   core/api.js      — apiCall
 *   core/notify.js   — showNotification
 *   modules/settings.js — getTranslation
 */

/**
 * Load configuration data via ConfigurationManager.
 * Shows an inline error when the manager is unavailable instead of
 * silently falling back to a legacy code path.
 */
async function loadConfigurationData() {
    try {
        if (window.configManager) {
            await window.configManager.load();
            _bindConfigToolbarEvents();
        } else {
            console.error('ConfigurationManager not loaded');
            showNotification(getTranslation('config.load_failed', 'Configuration subsystem failed to load. Please refresh the page.'), 'error');
            const configContainer = document.getElementById('config-dynamic-container') || document.getElementById('config-container');
            if (configContainer) {
                configContainer.innerHTML = '<div class="text-center text-red-500 py-8">' + getTranslation('config.module_unavailable', 'Configuration module unavailable') + '</div>';
            }
        }
    } catch (error) {
        console.error('Error loading configuration data:', error);
        const msg = error && error.message ? error.message : String(error) || 'Unknown error';
        showNotification(getTranslation('config.load_error', 'Failed to load configuration') + ': ' + msg, 'error');
    }
}

/** Bind configuration toolbar button events (idempotent via dataset flag) */
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

/**
 * Save configuration.
 * Always delegates to configManager — legacy form-based save is removed.
 */
function saveConfigurationPage() {
    if (window.configManager) {
        window.configManager.save();
    } else {
        showNotification(getTranslation('config.manager_not_loaded', 'Configuration manager not loaded'), 'warning');
    }
}
