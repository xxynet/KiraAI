/**
 * ConfigurationManager - Enhanced configuration management for KiraAI WebUI
 * Features: collapsible groups, search filtering, undo/redo, real-time validation
 */

class ConfigurationManager {
    constructor() {
        this.originalData = {};
        this.currentData = {};
        this.providers = [];
        this.providerModels = {};
        this.undoStack = [];
        this.redoStack = [];
        this.searchTerm = '';
        this.collapsedGroups = new Set();
        this.modifiedFields = new Set();
        this.validationErrors = {};
        this.container = null;
        this.initialized = false;
        this._boundKeyHandler = this._handleKeyboard.bind(this);
    }

    /**
     * Configuration schema definition
     */
    getSchema() {
        return [
            {
                id: 'bot',
                labelKey: 'configuration.groups.bot',
                labelFallback: 'Bot Settings',
                descKey: 'configuration.groups.bot_desc',
                descFallback: 'Core bot behavior parameters',
                icon: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>`,
                fields: [
                    {
                        key: 'bot_config.bot.max_memory_length',
                        labelKey: 'configuration.message.max_memory_length',
                        labelFallback: 'Max Memory Length',
                        hintKey: 'configuration.hints.max_memory_length',
                        hintFallback: 'Maximum number of messages retained in context window',
                        type: 'integer',
                        default: 50,
                        validation: { min: 1, max: 9999, required: true }
                    },
                    {
                        key: 'bot_config.bot.max_message_interval',
                        labelKey: 'configuration.message.max_message_interval',
                        labelFallback: 'Max Message Interval',
                        hintKey: 'configuration.hints.max_message_interval',
                        hintFallback: 'Maximum seconds to wait before processing buffered messages',
                        type: 'float',
                        default: 5,
                        validation: { min: 0.1, max: 300, required: true }
                    },
                    {
                        key: 'bot_config.bot.max_buffer_messages',
                        labelKey: 'configuration.message.max_buffer_messages',
                        labelFallback: 'Max Buffer Messages',
                        hintKey: 'configuration.hints.max_buffer_messages',
                        hintFallback: 'Maximum number of messages to buffer before processing',
                        type: 'integer',
                        default: 5,
                        validation: { min: 1, max: 100, required: true }
                    },
                    {
                        key: 'bot_config.bot.min_message_delay',
                        labelKey: 'configuration.message.min_message_delay',
                        labelFallback: 'Min Message Delay',
                        hintKey: 'configuration.hints.min_message_delay',
                        hintFallback: 'Minimum delay in seconds before sending a reply',
                        type: 'float',
                        default: 1,
                        validation: { min: 0, max: 60, required: true }
                    },
                    {
                        key: 'bot_config.bot.max_message_delay',
                        labelKey: 'configuration.message.max_message_delay',
                        labelFallback: 'Max Message Delay',
                        hintKey: 'configuration.hints.max_message_delay',
                        hintFallback: 'Maximum delay in seconds before sending a reply',
                        type: 'float',
                        default: 5,
                        validation: { min: 0, max: 60, required: true }
                    }
                ]
            },
            {
                id: 'agent',
                labelKey: 'configuration.groups.agent',
                labelFallback: 'Agent Settings',
                descKey: 'configuration.groups.agent_desc',
                descFallback: 'Agent and tool execution parameters',
                icon: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>`,
                fields: [
                    {
                        key: 'bot_config.agent.max_tool_loop',
                        labelKey: 'configuration.message.max_tool_loop',
                        labelFallback: 'Max Tool Loop',
                        hintKey: 'configuration.hints.max_tool_loop',
                        hintFallback: 'Maximum number of tool call iterations per response',
                        type: 'integer',
                        default: 5,
                        validation: { min: 1, max: 50, required: true }
                    }
                ]
            },
            {
                id: 'selfie',
                labelKey: 'configuration.groups.selfie',
                labelFallback: 'Appearance',
                descKey: 'configuration.groups.selfie_desc',
                descFallback: 'Bot appearance reference settings',
                icon: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>`,
                fields: [
                    {
                        key: 'bot_config.selfie.path',
                        labelKey: 'configuration.message.selfie_path',
                        labelFallback: 'Selfie Path',
                        hintKey: 'configuration.hints.selfie_path',
                        hintFallback: 'Path to the bot appearance reference image',
                        type: 'string',
                        default: '',
                        validation: { required: false }
                    }
                ]
            },
            {
                id: 'models',
                labelKey: 'configuration.groups.models',
                labelFallback: 'Default Models',
                descKey: 'configuration.groups.models_desc',
                descFallback: 'Select default provider and model for each capability',
                icon: `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"></path></svg>`,
                fields: [
                    {
                        key: 'models.default_llm',
                        labelKey: 'configuration.model.default_llm',
                        labelFallback: 'Default LLM',
                        hintKey: 'configuration.model.default_llm_desc',
                        hintFallback: 'Main chat model.',
                        type: 'model_select',
                        modelType: 'llm'
                    },
                    {
                        key: 'models.default_fast_llm',
                        labelKey: 'configuration.model.default_fast_llm',
                        labelFallback: 'Default Fast LLM',
                        hintKey: 'configuration.model.default_fast_llm_desc',
                        hintFallback: 'Fast reply model.',
                        type: 'model_select',
                        modelType: 'llm'
                    },
                    {
                        key: 'models.default_vlm',
                        labelKey: 'configuration.model.default_vlm',
                        labelFallback: 'Default VLM',
                        hintKey: 'configuration.model.default_vlm_desc',
                        hintFallback: 'Vision-language model.',
                        type: 'model_select',
                        modelType: 'llm'
                    },
                    {
                        key: 'models.default_tts',
                        labelKey: 'configuration.model.default_tts',
                        labelFallback: 'Default TTS',
                        hintKey: 'configuration.model.default_tts_desc',
                        hintFallback: 'Text to speech.',
                        type: 'model_select',
                        modelType: 'tts'
                    },
                    {
                        key: 'models.default_stt',
                        labelKey: 'configuration.model.default_stt',
                        labelFallback: 'Default STT',
                        hintKey: 'configuration.model.default_stt_desc',
                        hintFallback: 'Speech to text.',
                        type: 'model_select',
                        modelType: 'stt'
                    },
                    {
                        key: 'models.default_image',
                        labelKey: 'configuration.model.default_image',
                        labelFallback: 'Default Image',
                        hintKey: 'configuration.model.default_image_desc',
                        hintFallback: 'Image generation.',
                        type: 'model_select',
                        modelType: 'image'
                    },
                    {
                        key: 'models.default_embedding',
                        labelKey: 'configuration.model.default_embedding',
                        labelFallback: 'Default Embedding',
                        hintKey: 'configuration.model.default_embedding_desc',
                        hintFallback: 'Embedding model.',
                        type: 'model_select',
                        modelType: 'embedding'
                    },
                    {
                        key: 'models.default_rerank',
                        labelKey: 'configuration.model.default_rerank',
                        labelFallback: 'Default Rerank',
                        hintKey: 'configuration.model.default_rerank_desc',
                        hintFallback: 'Rerank model.',
                        type: 'model_select',
                        modelType: 'rerank'
                    },
                    {
                        key: 'models.default_video',
                        labelKey: 'configuration.model.default_video',
                        labelFallback: 'Default Video',
                        hintKey: 'configuration.model.default_video_desc',
                        hintFallback: 'Video generation.',
                        type: 'model_select',
                        modelType: 'video'
                    }
                ]
            }
        ];
    }

    // ========== Nested value helpers ==========

    _getNestedValue(obj, path) {
        return path.split('.').reduce((o, k) => (o && o[k] !== undefined) ? o[k] : undefined, obj);
    }

    _setNestedValue(obj, path, value) {
        const keys = path.split('.');
        const lastKey = keys.pop();
        const target = keys.reduce((o, k) => {
            if (!(k in o) || typeof o[k] !== 'object' || o[k] === null) o[k] = {};
            return o[k];
        }, obj);
        target[lastKey] = value;
    }

    /**
     * Walk a dot-separated path on obj; if every segment exists, apply transform
     * to the leaf value. Returns silently if any segment is missing.
     */
    _transformNestedValue(obj, path, transform) {
        const parts = path.split('.');
        let cursor = obj;
        for (let i = 0; i < parts.length - 1; i++) {
            const segment = parts[i];
            if (!cursor || typeof cursor !== 'object' || !(segment in cursor)) {
                return;
            }
            cursor = cursor[segment];
        }
        const leaf = parts[parts.length - 1];
        if (!cursor || typeof cursor !== 'object' || !(leaf in cursor)) {
            return;
        }
        cursor[leaf] = transform(cursor[leaf]);
    }

    _deepClone(obj) {
        return JSON.parse(JSON.stringify(obj));
    }

    /**
     * Ensure all schema fields with defaults are populated in currentData.
     * Does NOT mark them as modified — this is for load-time initialisation only.
     */
    _ensureDefaults() {
        const schema = this.getSchema();
        schema.forEach(group => {
            group.fields.forEach(field => {
                this._ensureDefaultForField(field, true);
            });
        });
    }

    /**
     * If a field's value is null/undefined in currentData and the schema
     * defines a default, write the default into currentData silently
     * (no undo record, no modifiedFields entry).
     */
    _ensureDefaultForField(field, writeOriginal = false) {
        if (field.default == null) return;
        const current = this._getNestedValue(this.currentData, field.key);
        if (current == null) {
            this._setNestedValue(this.currentData, field.key, field.default);
            if (writeOriginal) {
                this._setNestedValue(this.originalData, field.key, field.default);
            }
        }
    }

    _t(key, fallback) {
        if (window.i18n) {
            const val = window.i18n.t(key);
            return (val && val !== key) ? val : fallback;
        }
        return fallback;
    }

    // ========== Data loading ==========

    async load() {
        try {
            if (typeof window.apiCall !== 'function') {
                throw new Error('apiCall is not available');
            }
            const response = await window.apiCall('/api/configuration');
            if (!response.ok) {
                throw new Error(`API returned ${response.status} ${response.statusText}`);
            }
            const data = await response.json();
            const configuration = data.configuration || {};
            this.originalData = this._deepClone(configuration);
            this.currentData = this._deepClone(configuration);
            this.providers = data.providers || [];
            this.providerModels = data.provider_models || {};

            // Store in AppState for compatibility
            if (window.AppState) {
                AppState.data.configuration = configuration;
                AppState.data.configProviders = this.providers;
                AppState.data.configProviderModels = this.providerModels;
            }

            this.undoStack = [];
            this.redoStack = [];
            this.modifiedFields = new Set();
            this.validationErrors = {};

            // Ensure schema defaults are present in currentData
            this._ensureDefaults();

            this.render();
            this._bindKeyboard();
            this.initialized = true;
        } catch (error) {
            console.error('Error loading configuration:', error);
            if (typeof window.showNotification === 'function') {
                window.showNotification('Failed to load configuration', 'error');
            }
        }
    }

    // ========== Rendering ==========

    render() {
        this.container = document.getElementById('config-dynamic-container');
        if (!this.container) return;

        this.container.innerHTML = '';
        const schema = this.getSchema();
        const fragment = document.createDocumentFragment();

        schema.forEach(group => {
            const groupEl = this._renderGroup(group);
            if (groupEl) fragment.appendChild(groupEl);
        });

        this.container.appendChild(fragment);
        this._updateToolbar();
    }

    _renderGroup(group) {
        const isCollapsed = this.collapsedGroups.has(group.id);
        const matchingFields = this._getFilteredFields(group.fields);

        // If searching and no fields match, hide the group
        if (this.searchTerm && matchingFields.length === 0) return null;

        const wrapper = document.createElement('div');
        wrapper.className = 'config-group mb-4';
        wrapper.setAttribute('data-group-id', group.id);

        // Check if any field in this group is modified
        const hasModified = group.fields.some(f => this.modifiedFields.has(f.key));
        const hasErrors = group.fields.some(f => this.validationErrors[f.key]);
        const labelHtml = this._highlightSearch(this._t(group.labelKey, group.labelFallback));
        const descHtml = this._highlightSearch(this._t(group.descKey, group.descFallback));

        // Group header
        const header = document.createElement('div');
        header.className = `config-group-header flex items-center justify-between px-4 py-3 cursor-pointer rounded-t-lg select-none transition-colors duration-150 ${
            isCollapsed ? 'rounded-b-lg' : ''
        } bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-750 border border-gray-200 dark:border-gray-700`;
        header.innerHTML = `
            <div class="flex items-center space-x-3">
                <span class="text-gray-500 dark:text-gray-400">${group.icon}</span>
                <div>
                    <h4 class="text-sm font-semibold text-gray-800 dark:text-gray-100">
                        ${labelHtml}
                        ${hasModified ? '<span class="ml-2 inline-block w-2 h-2 bg-amber-400 rounded-full" title="Modified"></span>' : ''}
                        ${hasErrors ? '<span class="ml-1 inline-block w-2 h-2 bg-red-500 rounded-full" title="Has errors"></span>' : ''}
                    </h4>
                    <p class="text-xs text-gray-500 dark:text-gray-400">${descHtml}</p>
                </div>
            </div>
            <svg class="w-5 h-5 text-gray-400 dark:text-gray-500 transform transition-transform duration-200 ${isCollapsed ? '' : 'rotate-180'}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
            </svg>
        `;

        header.addEventListener('click', () => {
            if (this.collapsedGroups.has(group.id)) {
                this.collapsedGroups.delete(group.id);
            } else {
                this.collapsedGroups.add(group.id);
            }
            this.render();
        });

        // Group body
        const body = document.createElement('div');
        body.className = `config-group-body border border-t-0 border-gray-200 dark:border-gray-700 rounded-b-lg bg-white dark:bg-gray-900 overflow-hidden transition-all duration-200 ${
            isCollapsed ? 'max-h-0 opacity-0 py-0 border-0' : 'max-h-[2000px] opacity-100'
        }`;

        if (!isCollapsed) {
            const fieldsContainer = document.createElement('div');
            fieldsContainer.className = 'p-4 space-y-4';

            if (group.id === 'models') {
                // Model fields use a different layout
                matchingFields.forEach(field => {
                    fieldsContainer.appendChild(this._renderModelField(field));
                });
            } else {
                // Regular fields in a responsive grid
                const grid = document.createElement('div');
                grid.className = 'grid grid-cols-1 md:grid-cols-2 gap-4';
                matchingFields.forEach(field => {
                    grid.appendChild(this._renderField(field));
                });
                fieldsContainer.appendChild(grid);
            }

            body.appendChild(fieldsContainer);
        }

        wrapper.appendChild(header);
        wrapper.appendChild(body);
        return wrapper;
    }

    _renderField(field) {
        const value = this._getNestedValue(this.currentData, field.key);
        const isModified = this.modifiedFields.has(field.key);
        const error = this.validationErrors[field.key];
        const label = this._t(field.labelKey, field.labelFallback);
        const hint = this._t(field.hintKey, field.hintFallback);

        const wrapper = document.createElement('div');
        wrapper.className = 'config-field-wrapper';
        wrapper.setAttribute('data-field-key', field.key);

        // Label
        const labelEl = document.createElement('label');
        const safeFieldKey = field.key.replace(/[^a-zA-Z0-9_-]/g, '-');
        const labelId = `config-field-label-${safeFieldKey}`;
        const hintId = `config-field-hint-${safeFieldKey}`;
        labelEl.id = labelId;
        labelEl.className = `block text-sm font-medium mb-1 ${
            error ? 'text-red-600 dark:text-red-400' : 'text-gray-700 dark:text-gray-300'
        }`;
        labelEl.innerHTML = this._highlightSearch(label);
        if (isModified) {
            const badge = document.createElement('span');
            badge.className = 'ml-2 text-xs text-amber-500 font-normal';
            badge.textContent = this._t('configuration.modified', 'modified');
            labelEl.appendChild(badge);
        }

        // Input
        let input;
        if (field.type === 'integer') {
            input = document.createElement('input');
            input.type = 'number';
            input.step = '1';
            input.className = this._getInputClass(error);
            if (field.validation) {
                if (field.validation.min !== undefined) input.min = field.validation.min;
                if (field.validation.max !== undefined) input.max = field.validation.max;
            }
            input.value = value === null ? '' : (value !== undefined ? value : (field.default !== undefined && field.default !== null ? field.default : ''));
        } else if (field.type === 'float') {
            input = document.createElement('input');
            input.type = 'number';
            input.step = '0.1';
            input.className = this._getInputClass(error);
            if (field.validation) {
                if (field.validation.min !== undefined) input.min = field.validation.min;
                if (field.validation.max !== undefined) input.max = field.validation.max;
            }
            input.value = value === null ? '' : (value !== undefined ? value : (field.default !== undefined && field.default !== null ? field.default : ''));
        } else if (field.type === 'switch') {
            input = document.createElement('button');
            input.type = 'button';
            const isOn = !!value;
            const applySwitchState = (state) => {
                input.className = `relative inline-flex items-center h-6 w-11 rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                    state ? 'bg-blue-600 dark:bg-blue-500' : 'bg-gray-300 dark:bg-gray-600'
                }`;
                input.innerHTML = `<span class="inline-block h-4 w-4 bg-white rounded-full shadow transform transition-transform duration-200 ${
                    state ? 'translate-x-6' : 'translate-x-1'
                }"></span>`;
                input.setAttribute('aria-checked', state ? 'true' : 'false');
            };
            input.setAttribute('role', 'switch');
            input.setAttribute('aria-labelledby', `${labelId} ${hintId}`);
            input.setAttribute('aria-label', label);
            applySwitchState(isOn);

            const toggleSwitch = () => {
                const newVal = !this._getNestedValue(this.currentData, field.key);
                this._recordChange(field.key, this._getNestedValue(this.currentData, field.key), newVal);
                this._setNestedValue(this.currentData, field.key, newVal);
                this._updateModifiedState(field.key);
                this.render();
            };
            input.addEventListener('click', toggleSwitch);
            input.addEventListener('keydown', (e) => {
                if (e.key === ' ' || e.key === 'Enter') {
                    e.preventDefault();
                    toggleSwitch();
                }
            });
        } else {
            // String type
            input = document.createElement('input');
            input.type = 'text';
            input.className = this._getInputClass(error);
            input.value = value === null ? '' : (value !== undefined ? String(value) : (field.default !== undefined && field.default !== null ? String(field.default) : ''));
        }

        if (input.tagName !== 'BUTTON') {
            input.setAttribute('data-config-key', field.key);
            input.setAttribute('data-config-type', field.type);
            if (hint) {
                input.placeholder = hint;
            }

            // Real-time validation and change tracking
            input.addEventListener('input', (e) => {
                const oldVal = this._getNestedValue(this.currentData, field.key);
                let newVal = e.target.value;

                if (field.type === 'integer') {
                    newVal = newVal === '' ? null : Number(newVal);
                } else if (field.type === 'float') {
                    newVal = newVal === '' ? null : Number(newVal);
                }

                this._recordChange(field.key, oldVal, newVal);
                this._setNestedValue(this.currentData, field.key, newVal);
                this._validateField(field, newVal);
                this._updateModifiedState(field.key);
                this._updateToolbar();
                this._updateFieldVisuals(field.key);
            });

            // Validate on blur
            input.addEventListener('blur', () => {
                const val = this._getNestedValue(this.currentData, field.key);
                this._validateField(field, val);
                this._updateFieldVisuals(field.key);
            });
        }

        // Hint text
        const hintEl = document.createElement('p');
        hintEl.id = hintId;
        hintEl.className = `text-xs mt-1 ${error ? 'text-red-500 dark:text-red-400' : 'text-gray-500 dark:text-gray-400'}`;
        hintEl.innerHTML = error ? this._escapeHtml(error) : this._highlightSearch(hint || '');

        wrapper.appendChild(labelEl);
        wrapper.appendChild(input);
        wrapper.appendChild(hintEl);

        return wrapper;
    }

    _renderModelField(field) {
        const value = this._getNestedValue(this.currentData, field.key);
        const isModified = this.modifiedFields.has(field.key);
        const label = this._t(field.labelKey, field.labelFallback);
        const hint = this._t(field.hintKey, field.hintFallback);
        const parsed = this._parseModelRef(value);

        const wrapper = document.createElement('div');
        wrapper.className = 'config-field-wrapper flex flex-col md:flex-row md:items-center md:justify-between gap-3 py-3 border-b border-gray-100 dark:border-gray-800 last:border-0';
        wrapper.setAttribute('data-field-key', field.key);

        // Label side
        const labelSide = document.createElement('div');
        labelSide.className = 'flex-shrink-0';
        labelSide.innerHTML = `
            <div class="text-sm font-medium text-gray-800 dark:text-gray-100">
                ${this._highlightSearch(label)}
                ${isModified ? '<span class="ml-2 text-xs text-amber-500 font-normal">' + this._t('configuration.modified', 'modified') + '</span>' : ''}
            </div>
            <div class="text-xs text-gray-500 dark:text-gray-400">${this._highlightSearch(hint)}</div>
        `;

        // Selects side
        const selectSide = document.createElement('div');
        selectSide.className = 'flex flex-col sm:flex-row gap-2 md:gap-3';

        // Provider select
        const providerSelect = document.createElement('select');
        providerSelect.className = 'w-full sm:w-40 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500';
        providerSelect.setAttribute('data-model-provider', field.key);

        const emptyOpt = document.createElement('option');
        emptyOpt.value = '';
        emptyOpt.textContent = '';
        providerSelect.appendChild(emptyOpt);

        this.providers.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name || p.id;
            if (p.id === parsed.providerId) opt.selected = true;
            providerSelect.appendChild(opt);
        });

        // Model select
        const modelSelect = document.createElement('select');
        modelSelect.className = 'w-full sm:w-48 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500';
        modelSelect.setAttribute('data-model-select', field.key);

        this._fillModelOptions(modelSelect, parsed.providerId, field.modelType, parsed.modelId);

        // Event handlers
        providerSelect.addEventListener('change', () => {
            const oldVal = this._getNestedValue(this.currentData, field.key);
            const providerId = providerSelect.value;
            this._fillModelOptions(modelSelect, providerId, field.modelType, '');
            const selectedModel = modelSelect.value;
            const newVal = (providerId && selectedModel) ? (providerId + ':' + selectedModel) : null;
            this._recordChange(field.key, oldVal, newVal);
            this._setNestedValue(this.currentData, field.key, newVal);
            this._updateModifiedState(field.key);
            this._updateToolbar();
        });

        modelSelect.addEventListener('change', () => {
            const oldVal = this._getNestedValue(this.currentData, field.key);
            const providerId = providerSelect.value;
            const modelId = modelSelect.value;
            const newVal = (providerId && modelId) ? (providerId + ':' + modelId) : null;
            this._recordChange(field.key, oldVal, newVal);
            this._setNestedValue(this.currentData, field.key, newVal);
            this._updateModifiedState(field.key);
            this._updateToolbar();
        });

        selectSide.appendChild(providerSelect);
        selectSide.appendChild(modelSelect);

        wrapper.appendChild(labelSide);
        wrapper.appendChild(selectSide);
        return wrapper;
    }

    _fillModelOptions(select, providerId, typeKey, selectedModelId) {
        select.innerHTML = '';
        const emptyOpt = document.createElement('option');
        emptyOpt.value = '';
        emptyOpt.textContent = '';
        select.appendChild(emptyOpt);

        if (!providerId) return;

        const providerConfig = this.providerModels[providerId] || {};
        const typeConfig = providerConfig[typeKey] || {};
        Object.keys(typeConfig).forEach(modelId => {
            const opt = document.createElement('option');
            opt.value = modelId;
            opt.textContent = modelId;
            if (modelId === selectedModelId) opt.selected = true;
            select.appendChild(opt);
        });
    }

    _parseModelRef(ref) {
        if (typeof ref !== 'string' || !ref) return { providerId: '', modelId: '' };
        const parts = ref.split(':');
        if (parts.length === 1) return { providerId: parts[0], modelId: '' };
        return { providerId: parts[0], modelId: parts.slice(1).join(':') };
    }

    // ========== Styling helpers ==========

    _getInputClass(error) {
        const base = 'w-full border rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 transition-colors duration-150';
        if (error) {
            return `${base} border-red-400 dark:border-red-500 focus:ring-red-500`;
        }
        return `${base} border-gray-300 dark:border-gray-600 focus:ring-blue-500`;
    }

    _highlightSearch(text) {
        if (!this.searchTerm || !text) return this._escapeHtml(text);
        const escaped = this._escapeHtml(text);
        const searchEscaped = this.searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`(${searchEscaped})`, 'gi');
        return escaped.replace(regex, '<mark class="bg-yellow-200 dark:bg-yellow-700 px-0.5 rounded">$1</mark>');
    }

    _escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ========== Search ==========

    _getFilteredFields(fields) {
        if (!this.searchTerm) return fields;
        const term = this.searchTerm.toLowerCase();
        return fields.filter(f => {
            const label = this._t(f.labelKey, f.labelFallback).toLowerCase();
            const hint = this._t(f.hintKey, f.hintFallback).toLowerCase();
            const key = f.key.toLowerCase();
            return label.includes(term) || hint.includes(term) || key.includes(term);
        });
    }

    setSearch(term) {
        this.searchTerm = term.trim();
        this.render();
    }

    // ========== Validation ==========

    _validateField(field, value) {
        const v = field.validation;
        if (!v) {
            delete this.validationErrors[field.key];
            return true;
        }

        if (v.required && (value === null || value === undefined || value === '')) {
            this.validationErrors[field.key] = this._t('configuration.validation.required', 'This field is required');
            return false;
        }

        if ((field.type === 'integer' || field.type === 'float') && value !== null && value !== undefined && value !== '') {
            const num = Number(value);
            if (isNaN(num)) {
                this.validationErrors[field.key] = this._t('configuration.validation.invalid_number', 'Please enter a valid number');
                return false;
            }
            if (field.type === 'integer' && !Number.isInteger(num)) {
                this.validationErrors[field.key] = this._t('configuration.validation.integer', 'Please enter a whole number');
                return false;
            }
            if (v.min !== undefined && num < v.min) {
                this.validationErrors[field.key] = this._t('configuration.validation.min', 'Minimum value is') + ' ' + v.min;
                return false;
            }
            if (v.max !== undefined && num > v.max) {
                this.validationErrors[field.key] = this._t('configuration.validation.max', 'Maximum value is') + ' ' + v.max;
                return false;
            }
        }

        delete this.validationErrors[field.key];
        return true;
    }

    validateAll() {
        const schema = this.getSchema();
        let valid = true;
        schema.forEach(group => {
            group.fields.forEach(field => {
                if (field.type !== 'model_select') {
                    const val = this._getNestedValue(this.currentData, field.key);
                    if (!this._validateField(field, val)) {
                        valid = false;
                    }
                }
            });
        });
        return valid;
    }

    _updateFieldVisuals(key) {
        const wrapper = this.container?.querySelector(`[data-field-key="${key}"]`);
        if (!wrapper) return;

        const error = this.validationErrors[key];
        const input = wrapper.querySelector('input, select, textarea');
        const hint = wrapper.querySelector('p');
        const label = wrapper.querySelector('label');

        if (input && input.tagName !== 'BUTTON') {
            input.className = this._getInputClass(error);
        }
        if (hint) {
            if (hint.dataset.originalHintHtml === undefined) {
                hint.dataset.originalHintHtml = hint.innerHTML;
            }
            hint.className = `text-xs mt-1 ${error ? 'text-red-500 dark:text-red-400' : 'text-gray-500 dark:text-gray-400'}`;
            if (error) {
                hint.textContent = error;
            } else {
                hint.innerHTML = hint.dataset.originalHintHtml;
            }
        }
        if (label) {
            const isModified = this.modifiedFields.has(key);
            const badges = label.querySelectorAll('.text-amber-500');
            if (isModified && badges.length === 0) {
                const badge = document.createElement('span');
                badge.className = 'ml-2 text-xs text-amber-500 font-normal';
                badge.textContent = this._t('configuration.modified', 'modified');
                label.appendChild(badge);
            } else if (!isModified) {
                badges.forEach(b => { b.remove(); });
            }
        }
    }

    // ========== Change tracking & Undo/Redo ==========

    _updateModifiedState(key) {
        const original = this._getNestedValue(this.originalData, key);
        const current = this._getNestedValue(this.currentData, key);
        const originalStr = JSON.stringify(original ?? null);
        const currentStr = JSON.stringify(current ?? null);

        if (originalStr !== currentStr) {
            this.modifiedFields.add(key);
        } else {
            this.modifiedFields.delete(key);
        }
    }

    _recordChange(key, oldValue, newValue) {
        if (JSON.stringify(oldValue ?? null) === JSON.stringify(newValue ?? null)) return;

        this.undoStack.push({
            key,
            oldValue: this._deepClone(oldValue ?? null),
            newValue: this._deepClone(newValue ?? null),
            timestamp: Date.now()
        });

        // Limit stack size
        if (this.undoStack.length > 100) {
            this.undoStack.shift();
        }

        // Clear redo stack on new change
        this.redoStack = [];
    }

    _findFieldByKey(key) {
        for (const group of this.getSchema()) {
            for (const field of group.fields) {
                if (field.key === key) return field;
            }
        }
        return null;
    }

    undo() {
        if (this.undoStack.length === 0) return;
        const change = this.undoStack.pop();
        this.redoStack.push(change);
        this._setNestedValue(this.currentData, change.key, this._deepClone(change.oldValue));
        this._updateModifiedState(change.key);
        const field = this._findFieldByKey(change.key);
        if (field) {
            this._validateField(field, this._getNestedValue(this.currentData, change.key));
        }
        this.render();
    }

    redo() {
        if (this.redoStack.length === 0) return;
        const change = this.redoStack.pop();
        this.undoStack.push(change);
        this._setNestedValue(this.currentData, change.key, this._deepClone(change.newValue));
        this._updateModifiedState(change.key);
        const field = this._findFieldByKey(change.key);
        if (field) {
            this._validateField(field, this._getNestedValue(this.currentData, change.key));
        }
        this.render();
    }

    // ========== Toolbar ==========

    _updateToolbar() {
        const undoBtn = document.getElementById('config-undo-btn');
        const redoBtn = document.getElementById('config-redo-btn');
        const saveBtn = document.getElementById('configuration-save-button');
        const changeCount = document.getElementById('config-change-count');

        if (undoBtn) {
            const undoEmpty = this.undoStack.length === 0;
            undoBtn.disabled = undoEmpty;
            undoBtn.setAttribute('aria-disabled', String(undoEmpty));
            undoBtn.classList.toggle('opacity-40', undoEmpty);
            undoBtn.classList.toggle('cursor-not-allowed', undoEmpty);
        }
        if (redoBtn) {
            const redoEmpty = this.redoStack.length === 0;
            redoBtn.disabled = redoEmpty;
            redoBtn.setAttribute('aria-disabled', String(redoEmpty));
            redoBtn.classList.toggle('opacity-40', redoEmpty);
            redoBtn.classList.toggle('cursor-not-allowed', redoEmpty);
        }
        if (changeCount) {
            const count = this.modifiedFields.size;
            if (count > 0) {
                changeCount.textContent = count + ' ' + this._t('configuration.changes', 'change(s)');
                changeCount.classList.remove('hidden');
            } else {
                changeCount.classList.add('hidden');
            }
        }
        if (saveBtn) {
            const hasChanges = this.modifiedFields.size > 0;
            saveBtn.disabled = !hasChanges;
            saveBtn.setAttribute('aria-disabled', String(!hasChanges));
            saveBtn.classList.toggle('opacity-60', !hasChanges);
            saveBtn.classList.toggle('cursor-not-allowed', !hasChanges);
        }
    }

    // ========== Keyboard shortcuts ==========

    _bindKeyboard() {
        document.removeEventListener('keydown', this._boundKeyHandler);
        document.addEventListener('keydown', this._boundKeyHandler);
    }

    _handleKeyboard(e) {
        // Only active when configuration page is visible
        const page = document.getElementById('page-configuration');
        if (!page || page.classList.contains('hidden')) return;

        // Ctrl+Z = Undo
        if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
            e.preventDefault();
            this.undo();
        }
        // Ctrl+Shift+Z or Ctrl+Y = Redo
        if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey) || (e.key === 'Z' && e.shiftKey))) {
            e.preventDefault();
            this.redo();
        }
        // Ctrl+S = Save
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            if (this.modifiedFields.size > 0) {
                this.save();
            }
        }
        // Ctrl+F or / = Focus search (when not in input)
        if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
            e.preventDefault();
            const searchInput = document.getElementById('config-search-input');
            if (searchInput) searchInput.focus();
        }
    }

    // ========== Save ==========

    async save() {
        // Validate all fields
        if (!this.validateAll()) {
            if (typeof window.showNotification === 'function') {
                window.showNotification(this._t('configuration.validation_failed', 'Please fix validation errors before saving'), 'error');
            }
            // Expand groups with errors
            const schema = this.getSchema();
            schema.forEach(group => {
                if (group.fields.some(f => this.validationErrors[f.key])) {
                    this.collapsedGroups.delete(group.id);
                }
            });
            this.render();
            return;
        }

        try {
            // Build the payload matching the existing API format
            const botConfig = this._getNestedValue(this.currentData, 'bot_config') || {};
            const models = this._getNestedValue(this.currentData, 'models') || {};

            // Parse numeric values based on schema types
            const numericFieldKeys = new Set();
            this.getSchema().forEach(group => {
                group.fields.forEach(field => {
                    if (field.type === 'integer' || field.type === 'float') {
                        numericFieldKeys.add(field.key);
                    }
                });
            });

            const parsedBotConfig = this._deepClone(botConfig);
            for (const key of numericFieldKeys) {
                if (!key.startsWith('bot_config.')) {
                    continue;
                }
                const relativePath = key.slice('bot_config.'.length);
                this._transformNestedValue(parsedBotConfig, relativePath, (value) => {
                    if (value === null || value === undefined || value === '') {
                        return value;
                    }
                    return Number(value);
                });
            }

            const response = await (typeof window.apiCall === 'function'
                ? window.apiCall('/api/configuration', {
                    method: 'POST',
                    body: JSON.stringify({
                        bot_config: parsedBotConfig,
                        models: models
                    })
                })
                : Promise.reject(new Error('apiCall is not available'))
            );

            if (!response.ok) {
                let errorMsg = `API returned ${response.status} ${response.statusText}`;
                try {
                    const errBody = await response.json();
                    if (errBody && errBody.message) errorMsg = errBody.message;
                } catch (_) { /* ignore parse error */ }
                throw new Error(errorMsg);
            }

            const data = await response.json();

            if (data.status === 'ok') {
                // Update original data to match saved state
                this.originalData = this._deepClone(this.currentData);
                this.modifiedFields = new Set();
                this.undoStack = [];
                this.redoStack = [];

                if (typeof window.showNotification === 'function') {
                    window.showNotification(
                        this._t('configuration.saved', 'Configuration saved successfully'),
                        'success'
                    );
                }
                this.render();
            } else {
                if (typeof window.showNotification === 'function') {
                    window.showNotification(this._t('configuration.save_failed', 'Failed to save configuration'), 'error');
                }
            }
        } catch (error) {
            console.error('Error saving configuration:', error);
            if (typeof window.showNotification === 'function') {
                window.showNotification(this._t('configuration.save_error', 'Error saving configuration'), 'error');
            }
        }
    }

    // ========== Reset ==========

    reset() {
        this.currentData = this._deepClone(this.originalData);
        this.modifiedFields = new Set();
        this.validationErrors = {};
        this.undoStack = [];
        this.redoStack = [];
        this.render();
        if (typeof window.showNotification === 'function') {
            window.showNotification(this._t('configuration.reset', 'Configuration reset to saved state'), 'info');
        }
    }

    // ========== Expand/Collapse All ==========

    expandAll() {
        this.collapsedGroups.clear();
        this.render();
    }

    collapseAll() {
        const schema = this.getSchema();
        schema.forEach(g => { this.collapsedGroups.add(g.id); });
        this.render();
    }
}

// Global instance
window.configManager = new ConfigurationManager();
