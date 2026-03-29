/**
 * Provider domain module
 * Handles provider list rendering, create/delete modal, provider config panel,
 * model group management (load, add, edit, delete), and provider status toggle.
 *
 * Dependencies (loaded before this file):
 *   core/state.js    — AppState
 *   core/api.js      — apiCall
 *   core/notify.js   — showNotification
 *   core/modal.js    — Modal
 *   shared/render-config-fields.js — renderConfigFields, collectConfigFromContainer,
 *                                    validateConfigFieldInput
 *   app.js (global)  — escapeHtml, getTranslation, updateTranslations,
 *                       openDeleteModal, closeDeleteModal
 */

// ---------------------------------------------------------------------------
// Data loader
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Provider list rendering
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Add provider modal
// ---------------------------------------------------------------------------

async function openProviderModal() {
    Modal.show('provider-modal', closeProviderModal);

    // Clear form fields
    document.getElementById('provider-name').value = '';
    const typeSelect = document.getElementById('provider-type');

    const configContainer = document.getElementById('provider-config-container');
    if (configContainer) {
        configContainer.innerHTML = '';
    }

    if (typeSelect) {
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
                if (typeof CustomSelect !== 'undefined') {
                    new CustomSelect(currentTypeSelect, {
                        placeholder: 'Select provider type...'
                    });
                }
            }

            // Use onchange property to avoid stacking listeners
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

// ---------------------------------------------------------------------------
// Provider model configuration helpers (used by the legacy config page)
// ---------------------------------------------------------------------------

/**
 * Parse a "providerId:modelId" reference string.
 * @param {string} ref
 * @returns {{ providerId: string, modelId: string }}
 */
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

/**
 * Populate the model-configuration dropdowns on the legacy config page.
 * @param {object} modelsConfig   - Current model reference values
 * @param {Array}  providers      - Provider list from AppState
 * @param {object} providerModels - Cached provider model configs
 */
function populateModelConfiguration(modelsConfig, providers, providerModels) {
    const modelTypes = [
        { key: 'default_llm',       providerSelectId: 'config-model-default-llm-provider',       modelSelectId: 'config-model-default-llm-model',       typeKey: 'llm' },
        { key: 'default_vlm',       providerSelectId: 'config-model-default-vlm-provider',       modelSelectId: 'config-model-default-vlm-model',       typeKey: 'llm' },
        { key: 'default_fast_llm',  providerSelectId: 'config-model-default-fast-llm-provider',  modelSelectId: 'config-model-default-fast-llm-model',  typeKey: 'llm' },
        { key: 'default_tts',       providerSelectId: 'config-model-default-tts-provider',       modelSelectId: 'config-model-default-tts-model',       typeKey: 'tts' },
        { key: 'default_stt',       providerSelectId: 'config-model-default-stt-provider',       modelSelectId: 'config-model-default-stt-model',       typeKey: 'stt' },
        { key: 'default_image',     providerSelectId: 'config-model-default-image-provider',     modelSelectId: 'config-model-default-image-model',     typeKey: 'image' },
        { key: 'default_embedding', providerSelectId: 'config-model-default-embedding-provider', modelSelectId: 'config-model-default-embedding-model', typeKey: 'embedding' },
        { key: 'default_rerank',    providerSelectId: 'config-model-default-rerank-provider',    modelSelectId: 'config-model-default-rerank-model',    typeKey: 'rerank' },
        { key: 'default_video',     providerSelectId: 'config-model-default-video-provider',     modelSelectId: 'config-model-default-video-model',     typeKey: 'video' }
    ];
    const fillProviderOptions = (select, selectedProviderId) => {
        if (!select) return;
        select.innerHTML = '';
        const emptyOption = document.createElement('option');
        emptyOption.value = '';
        emptyOption.textContent = '';
        select.appendChild(emptyOption);
        providers.forEach((p) => {
            const option = document.createElement('option');
            option.value = p.id;
            option.textContent = p.name || p.id;
            if (p.id === selectedProviderId) option.selected = true;
            select.appendChild(option);
        });
    };
    const fillModelOptions = (select, providerId, typeKey, selectedModelId) => {
        if (!select) return;
        select.innerHTML = '';
        const emptyOption = document.createElement('option');
        emptyOption.value = '';
        emptyOption.textContent = '';
        select.appendChild(emptyOption);
        if (!providerId) return;
        const providerConfig = providerModels[providerId] || {};
        const typeConfig = providerConfig[typeKey] || {};
        Object.keys(typeConfig).forEach((modelId) => {
            const option = document.createElement('option');
            option.value = modelId;
            option.textContent = modelId;
            if (modelId === selectedModelId) option.selected = true;
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

/** Collect model configuration from legacy config page dropdowns */
function buildModelsConfiguration() {
    const modelTypes = [
        { key: 'default_llm',       providerSelectId: 'config-model-default-llm-provider',       modelSelectId: 'config-model-default-llm-model' },
        { key: 'default_vlm',       providerSelectId: 'config-model-default-vlm-provider',       modelSelectId: 'config-model-default-vlm-model' },
        { key: 'default_fast_llm',  providerSelectId: 'config-model-default-fast-llm-provider',  modelSelectId: 'config-model-default-fast-llm-model' },
        { key: 'default_tts',       providerSelectId: 'config-model-default-tts-provider',       modelSelectId: 'config-model-default-tts-model' },
        { key: 'default_stt',       providerSelectId: 'config-model-default-stt-provider',       modelSelectId: 'config-model-default-stt-model' },
        { key: 'default_image',     providerSelectId: 'config-model-default-image-provider',     modelSelectId: 'config-model-default-image-model' },
        { key: 'default_embedding', providerSelectId: 'config-model-default-embedding-provider', modelSelectId: 'config-model-default-embedding-model' },
        { key: 'default_rerank',    providerSelectId: 'config-model-default-rerank-provider',    modelSelectId: 'config-model-default-rerank-model' },
        { key: 'default_video',     providerSelectId: 'config-model-default-video-provider',     modelSelectId: 'config-model-default-video-model' }
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

// ---------------------------------------------------------------------------
// Schema helpers
// ---------------------------------------------------------------------------

/**
 * Fetch provider schema from the API.
 * @param {string} providerType
 * @returns {Promise<object|null>}
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
 * Load provider schema and render config fields into the provider modal container.
 * @param {string} providerType
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

/** Thin wrapper so call sites keep a meaningful name */
function renderProviderConfigFields(schema, container, currentConfig = {}) {
    renderConfigFields(schema, container, currentConfig);
}

// ---------------------------------------------------------------------------
// Provider modal close / save
// ---------------------------------------------------------------------------

function closeProviderModal() {
    Modal.hide('provider-modal');
}

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
    const jsonError = validateConfigContainer(configContainer);
    if (jsonError) { showNotification(jsonError, 'error'); return; }
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
            await loadProviderData();
            closeProviderModal();
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

// Expose modal functions used from HTML onclick attributes
window.openProviderModal = openProviderModal;
window.closeProviderModal = closeProviderModal;
window.saveProvider = saveProvider;

// ---------------------------------------------------------------------------
// Provider selection & config panel
// ---------------------------------------------------------------------------

/**
 * Select a provider and show its configuration panel.
 * @param {string} providerId
 */
function selectProvider(providerId) {
    AppState.selectedProviderId = providerId;
    renderProviderList();
    const provider = AppState.data.providers.find(p => p.id === providerId);
    if (provider) {
        displayProviderConfig(provider);
    }
}

/**
 * Render the provider configuration panel (right-hand side).
 * @param {object} provider
 */
async function displayProviderConfig(provider) {
    const configContainer = document.getElementById('provider-config');
    if (!configContainer) return;

    const modelGroups = ['LLM', 'TTS', 'STT', 'Image', 'Video', 'Embedding', 'Rerank'];
    const groupTypeMapping = {
        LLM: 'llm', TTS: 'tts', STT: 'stt',
        Image: 'image', Video: 'video', Embedding: 'embedding', Rerank: 'rerank'
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
 * Save provider configuration from the details panel.
 * @param {string} providerId
 */
async function saveProviderConfig(providerId) {
    const detailsContainer = document.getElementById('provider-details-config');
    if (!detailsContainer) return;

    const provider = AppState.data.providers.find(p => p.id === providerId);
    if (!provider) {
        showNotification(window.i18n ? window.i18n.t('provider.not_found') : 'Provider not found', 'error');
        return;
    }

    const jsonError = validateConfigContainer(detailsContainer);
    if (jsonError) { showNotification(jsonError, 'error'); return; }
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
            await loadProviderData();
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

// ---------------------------------------------------------------------------
// Provider model management
// ---------------------------------------------------------------------------

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

/** Re-render all model group content panels from the cached model config */
function renderModelGroupModels(modelConfig) {
    modelConfig = modelConfig || {};
    const groups = {
        LLM: 'llm', TTS: 'tts', STT: 'stt',
        Image: 'image', Video: 'video', Embedding: 'embedding', Rerank: 'rerank'
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

/** Toggle the collapse state of a model group panel */
function toggleModelGroup(groupName) {
    const content = document.getElementById(`model-group-content-${groupName}`);
    const icon = document.getElementById(`model-group-icon-${groupName}`);

    if (content && icon) {
        content.classList.toggle('hidden');
        icon.classList.toggle('rotate-180');
    }
}

// ---------------------------------------------------------------------------
// Model modal
// ---------------------------------------------------------------------------

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
    Modal.show('model-modal', closeModelModal);
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
        // Replace node to drop stale event listeners
        const currentValue = modelIdInput.value;
        const currentDisabled = modelIdInput.disabled;
        const newInput = modelIdInput.cloneNode(true);
        modelIdInput.parentNode.replaceChild(newInput, modelIdInput);
        newInput.value = currentValue;
        newInput.disabled = currentDisabled;
        newInput.addEventListener('input', function() { validateModelIdInput(this); });
        newInput.addEventListener('blur',  function() { validateModelIdInput(this); });
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
        const initialConfig = existingConfig || {};
        renderProviderConfigFields(modelConfigSchema, configContainer, initialConfig);
    } catch (error) {
        console.error('Error loading model schema:', error);
        showNotification(getTranslation('model.schema_load_failed', 'Failed to load model config schema'), 'error');
    }
}

/**
 * Validate the model ID input in real-time.
 * @param {HTMLInputElement} input
 * @returns {boolean} true if valid
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
        if (!key) return;
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
                body: JSON.stringify({ config: config })
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

/** Open the model modal for adding a new model to a group */
function addModel(groupName) {
    const providerId = AppState.selectedProviderId;
    if (!providerId) {
        showNotification(getTranslation('model.select_provider_first', 'Please select a provider first'), 'error');
        return;
    }
    const modelType = groupName.toLowerCase();
    openModelModal(providerId, modelType, groupName);
}

/** Reload a single provider from the API and refresh the config panel */
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
 * Toggle provider active/inactive status (local only — no API call).
 * @param {string} providerId
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

// Expose functions called via HTML onclick attributes
window.selectProvider = selectProvider;
window.toggleProviderStatus = toggleProviderStatus;
window.toggleModelGroup = toggleModelGroup;
window.addModel = addModel;
window.deleteModel = deleteModel;
window.openModelModal = openModelModal;
window.closeModelModal = closeModelModal;
window.saveModel = saveModel;
