/**
 * Adapter domain module
 * Handles adapter list rendering, create/edit/delete modal, status toggle,
 * and dynamic schema-driven config fields.
 *
 * Dependencies (loaded before this file):
 *   core/state.js    — AppState
 *   core/api.js      — apiCall
 *   core/notify.js   — showNotification
 *   core/modal.js    — Modal
 *   shared/render-config-fields.js — renderConfigFields, collectConfigFromContainer
 *   app.js (global)  — escapeHtml, getTranslation, updateTranslations,
 *                       openDeleteModal, closeDeleteModal
 */

// Tracks the adapter modal state (create vs edit)
const AdapterModalState = {
    mode: 'create',
    adapterId: null
};

// ---------------------------------------------------------------------------
// Data loader
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// List rendering
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Status toggle (active / inactive)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Schema helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Modal — open / close / save
// ---------------------------------------------------------------------------

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

    Modal.show('adapter-modal', closeAdapterModal);

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

// Status toggle switch inside the adapter modal (delegated from document)
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
    const jsonError = validateConfigContainer(configContainer);
    if (jsonError) { showNotification(jsonError, 'error'); return; }
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

// ---------------------------------------------------------------------------
// Edit / delete actions (called from rendered card buttons)
// ---------------------------------------------------------------------------

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
