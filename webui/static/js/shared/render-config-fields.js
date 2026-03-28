/**
 * Config field rendering and collection utilities
 * Dependencies: core/notify.js (via getTranslation from i18n.js)
 */

function renderConfigFields(schema, containerOrId, currentConfig = {}) {
    const container = typeof containerOrId === 'string' ? document.getElementById(containerOrId) : containerOrId;
    if (!container) return;

    container.innerHTML = '';

    // Support nested provider_config schema format
    const fields = (schema && schema.provider_config) ? schema.provider_config : schema;

    if (!fields || Object.keys(fields).length === 0) {
        container.innerHTML = '<div class="text-gray-500 dark:text-gray-400 py-2">' + getTranslation('model.no_config_required', 'No configuration required') + '</div>';
        return;
    }

    const inputClass = 'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors';

    Object.entries(fields).forEach(([key, field]) => {
        if (!field || key.startsWith('_')) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'mb-4';

        const label = document.createElement('label');
        label.className = 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1';
        label.textContent = field.name || key;
        wrapper.appendChild(label);

        const fieldType = field.type || 'string';
        const currentValue = currentConfig[key] !== undefined ? currentConfig[key] : field.default;
        const hasOptions = Array.isArray(field.options) && field.options.length > 0;

        let input;

        if (fieldType === 'switch') {
            input = document.createElement('input');
            input.type = 'checkbox';
            input.className = 'sr-only';
            input.setAttribute('data-config-key', key);
            input.setAttribute('data-config-type', fieldType);
            const isChecked = currentValue === true || currentValue === 'true';
            input.checked = isChecked;

            const toggleBg = document.createElement('span');
            toggleBg.className = `relative inline-flex items-center h-5 w-9 rounded-full ${isChecked ? 'bg-green-500' : 'bg-gray-300'} transition-colors cursor-pointer`;
            const toggleKnob = document.createElement('span');
            toggleKnob.className = `inline-block h-4 w-4 bg-white rounded-full shadow transform ${isChecked ? 'translate-x-5' : 'translate-x-0'} transition-transform`;
            toggleBg.appendChild(toggleKnob);
            toggleBg.addEventListener('click', () => {
                input.checked = !input.checked;
                toggleBg.className = `relative inline-flex items-center h-5 w-9 rounded-full ${input.checked ? 'bg-green-500' : 'bg-gray-300'} transition-colors cursor-pointer`;
                toggleKnob.className = `inline-block h-4 w-4 bg-white rounded-full shadow transform ${input.checked ? 'translate-x-5' : 'translate-x-0'} transition-transform`;
            });

            const toggleRow = document.createElement('div');
            toggleRow.className = 'flex items-center';
            toggleRow.appendChild(input);
            toggleRow.appendChild(toggleBg);
            wrapper.appendChild(toggleRow);

        } else if (hasOptions) {
            input = document.createElement('select');
            input.className = inputClass;
            if (fieldType === 'list') input.multiple = true;
            if (!input.multiple) {
                const placeholder = document.createElement('option');
                placeholder.value = '';
                placeholder.textContent = '';
                input.appendChild(placeholder);
            }
            field.options.forEach(optionValue => {
                const option = document.createElement('option');
                option.value = optionValue;
                option.textContent = optionValue;
                input.appendChild(option);
            });
            input.setAttribute('data-config-key', key);
            input.setAttribute('data-config-type', fieldType);
            if (currentValue !== undefined && currentValue !== null) {
                if (input.multiple && Array.isArray(currentValue)) {
                    Array.from(input.options).forEach(o => { o.selected = currentValue.includes(o.value); });
                } else {
                    input.value = String(currentValue);
                }
            }
            wrapper.appendChild(input);

        } else if (fieldType === 'list') {
            input = document.createElement('textarea');
            input.className = inputClass;
            input.rows = 3;
            input.setAttribute('data-config-key', key);
            input.setAttribute('data-config-type', fieldType);
            if (field.hint) input.placeholder = field.hint;
            if (currentValue !== undefined && currentValue !== null) {
                input.value = Array.isArray(currentValue) ? currentValue.join('\n') : String(currentValue);
            }
            wrapper.appendChild(input);

        } else if (fieldType === 'textarea') {
            input = document.createElement('textarea');
            input.className = inputClass;
            input.rows = 4;
            input.setAttribute('data-config-key', key);
            input.setAttribute('data-config-type', fieldType);
            if (field.hint) input.placeholder = field.hint;
            if (currentValue !== undefined && currentValue !== null) input.value = String(currentValue);
            wrapper.appendChild(input);

        } else if (fieldType === 'model_select') {
            input = document.createElement('select');
            input.className = inputClass;
            input.setAttribute('data-config-key', key);
            input.setAttribute('data-config-type', fieldType);
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = getTranslation('config.select_model', '— Select model —');
            input.appendChild(placeholder);
            loadModelSelectOptions(input, field.model_type, currentValue);
            wrapper.appendChild(input);

        } else if (['json', 'markdown', 'yaml', 'editor'].includes(fieldType)) {
            // Hidden textarea as value store for collectConfigFromContainer
            input = document.createElement('textarea');
            input.className = 'hidden';
            input.setAttribute('data-config-key', key);
            input.setAttribute('data-config-type', fieldType);
            let initialText = '';
            if (currentValue !== undefined && currentValue !== null) {
                initialText = (fieldType === 'json' && typeof currentValue === 'object')
                    ? JSON.stringify(currentValue, null, 2)
                    : String(currentValue);
            }
            input.value = initialText;

            const monacoContainer = document.createElement('div');
            monacoContainer.className = 'border border-gray-300 dark:border-gray-600 rounded-lg overflow-hidden';
            monacoContainer.style.height = '200px';

            wrapper.appendChild(input);
            wrapper.appendChild(monacoContainer);

            const langMap = { json: 'json', markdown: 'markdown', yaml: 'yaml', editor: field.language || 'plaintext' };
            const monacoLang = langMap[fieldType];
            // Defer initialization until the element is in the DOM
            setTimeout(() => initConfigMonacoEditor(monacoContainer, input, monacoLang), 0);

        } else {
            // string, integer, float, sensitive
            input = document.createElement('input');
            if (fieldType === 'sensitive') {
                input.type = 'password';
            } else if (fieldType === 'integer') {
                input.type = 'number';
                input.step = '1';
            } else if (fieldType === 'float') {
                input.type = 'number';
                input.step = 'any';
            } else {
                input.type = 'text';
            }
            input.className = inputClass + (fieldType === 'sensitive' ? ' pr-10' : '');
            input.setAttribute('data-config-key', key);
            input.setAttribute('data-config-type', fieldType);
            if (field.name) input.setAttribute('data-config-name', field.name);
            if (field.min !== undefined) input.setAttribute('data-config-min', field.min);
            if (field.hint) input.placeholder = field.hint;
            if (currentValue !== undefined && currentValue !== null) input.value = currentValue;
            if (fieldType === 'integer' || fieldType === 'float') {
                input.addEventListener('input', function() { validateConfigFieldInput(this); });
                input.addEventListener('blur', function() { validateConfigFieldInput(this); });
            }
            if (fieldType === 'sensitive') {
                const inputWrapper = document.createElement('div');
                inputWrapper.className = 'relative';
                inputWrapper.appendChild(input);
                const eyeBtn = document.createElement('button');
                eyeBtn.type = 'button';
                eyeBtn.className = 'absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 focus:outline-none';
                eyeBtn.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>`;
                eyeBtn.addEventListener('click', () => {
                    const visible = input.type === 'text';
                    input.type = visible ? 'password' : 'text';
                    eyeBtn.innerHTML = visible
                        ? `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>`
                        : `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"/></svg>`;
                });
                inputWrapper.appendChild(eyeBtn);
                wrapper.appendChild(inputWrapper);
            } else {
                wrapper.appendChild(input);
            }
        }

        // Error message placeholder (for numeric validation)
        const errorEl = document.createElement('p');
        errorEl.className = 'text-xs text-red-500 dark:text-red-400 mt-1 hidden';
        errorEl.setAttribute('data-error-for', key);
        wrapper.appendChild(errorEl);

        // Hint text below input
        if (field.hint) {
            const hintEl = document.createElement('p');
            hintEl.className = 'text-xs text-gray-500 dark:text-gray-400 mt-1';
            hintEl.textContent = field.hint;
            wrapper.appendChild(hintEl);
        }

        container.appendChild(wrapper);
    });
}

/**
 * Initialize a Monaco editor inside a config field container.
 * Syncs changes back to the hidden textarea used by collectConfigFromContainer.
 */
function initConfigMonacoEditor(editorContainer, hiddenTextarea, language) {
    const doInit = () => {
        const isDark = document.documentElement.classList.contains('dark');
        const editor = monaco.editor.create(editorContainer, {
            value: hiddenTextarea.value,
            language: language,
            theme: isDark ? 'vs-dark' : 'vs',
            automaticLayout: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            fontSize: 13,
            wordWrap: 'on',
            folding: false,
            lineNumbers: 'on',
            renderWhitespace: 'selection',
        });
        editor.onDidChangeModelContent(() => {
            hiddenTextarea.value = editor.getValue();
        });
        editorContainer._monacoInstance = editor;
    };

    if (typeof monaco !== 'undefined') {
        doInit();
    } else if (typeof require !== 'undefined') {
        require(['vs/editor/editor.main'], doInit);
    }
}

function collectConfigFromContainer(container) {
    const config = {};
    if (!container) {
        return config;
    }
    const inputs = container.querySelectorAll('[data-config-key]');
    inputs.forEach((input) => {
        const key = input.getAttribute('data-config-key');
        const fieldType = input.getAttribute('data-config-type');
        if (!key) {
            return;
        }
        let value;
        if (input.type === 'checkbox') {
            value = input.checked;
        } else if (input.tagName === 'SELECT') {
            const selectElement = input;
            if (selectElement.multiple) {
                value = Array.from(selectElement.selectedOptions)
                    .map((o) => o.value)
                    .filter((v) => v !== '');
            } else {
                value = selectElement.value;
            }
        } else if (input.tagName === 'TEXTAREA' && fieldType === 'list') {
            const raw = input.value || '';
            value = raw
                .split('\n')
                .map((s) => s.trim())
                .filter((s) => s.length > 0);
        } else {
            value = input.value;
        }
        if (fieldType === 'integer') {
            value = value === '' ? null : parseInt(value, 10);
        } else if (fieldType === 'float') {
            value = value === '' ? null : parseFloat(value);
        } else if (fieldType === 'list' && !Array.isArray(value)) {
            const raw = value || '';
            value = raw
                .split('\n')
                .flatMap((s) => s.split(','))
                .map((s) => s.trim())
                .filter((s) => s.length > 0);
        } else if (fieldType === 'json') {
            try { value = JSON.parse(value); } catch (e) { value = value; /* validated before save */ }
        }
        config[key] = value;
    });
    return config;
}

/**
 * Validate all fields in a config container before saving.
 * Returns null if valid, or an error string describing the first invalid field.
 */
function validateConfigContainer(container) {
    if (!container) return null;
    const inputs = container.querySelectorAll('[data-config-key][data-config-type="json"]');
    for (const input of inputs) {
        const value = input.value.trim();
        if (!value) continue;
        try {
            JSON.parse(value);
        } catch (e) {
            const key = input.getAttribute('data-config-key');
            const label = input.closest('.mb-4')?.querySelector('label')?.textContent?.trim() || key;
            return getTranslation('config.json_invalid', 'Invalid JSON in field "{field}": {error}')
                .replace('{field}', label)
                .replace('{error}', e.message);
        }
    }
    return null;
}

/**
 * Validate a config field input in real-time
 * @param {HTMLInputElement} input
 * @returns {boolean}
 */
function validateConfigFieldInput(input) {
    const key = input.getAttribute('data-config-key');
    const fieldType = input.getAttribute('data-config-type');
    const fieldName = input.getAttribute('data-config-name') || key;
    const value = input.value.trim();
    const errorEl = input.parentElement.querySelector(`[data-error-for="${key}"]`);

    let errorMsg = '';

    if (value !== '') {
        if (fieldType === 'integer') {
            if (!/^-?\d+$/.test(value)) {
                errorMsg = getTranslation('model.validation_integer', '{field} must be an integer').replace('{field}', fieldName);
            } else if (input.hasAttribute('data-config-min') && parseInt(value, 10) < parseInt(input.getAttribute('data-config-min'), 10)) {
                const min = input.getAttribute('data-config-min');
                errorMsg = getTranslation('model.validation_min', '{field} must be at least {min}')
                    .replace('{field}', fieldName)
                    .replace('{min}', min);
            }
        } else if (fieldType === 'float') {
            if (!/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(value)) {
                errorMsg = getTranslation('model.validation_number', '{field} must be a valid number').replace('{field}', fieldName);
            } else if (input.hasAttribute('data-config-min') && parseFloat(value) < parseFloat(input.getAttribute('data-config-min'))) {
                const min = input.getAttribute('data-config-min');
                errorMsg = getTranslation('model.validation_min', '{field} must be at least {min}')
                    .replace('{field}', fieldName)
                    .replace('{min}', min);
            }
        }
    }

    if (errorMsg) {
        input.classList.remove('border-gray-300', 'dark:border-gray-600', 'focus:ring-blue-500');
        input.classList.add('border-red-500', 'dark:border-red-400', 'focus:ring-red-500');
        if (errorEl) { errorEl.textContent = errorMsg; errorEl.classList.remove('hidden'); }
        return false;
    } else {
        input.classList.remove('border-red-500', 'dark:border-red-400', 'focus:ring-red-500');
        input.classList.add('border-gray-300', 'dark:border-gray-600', 'focus:ring-blue-500');
        if (errorEl) { errorEl.textContent = ''; errorEl.classList.add('hidden'); }
        return true;
    }
}

/**
 * Populate a model_select <select> element with options fetched from the provider API.
 * Options are grouped by provider and filtered to the requested model_type.
 * Display format: "model_id (Provider Name)"
 * Value format:   "provider_id/model_type/model_id"
 */
async function loadModelSelectOptions(selectEl, modelType, currentValue) {
    try {
        const res = await apiCall('/api/providers');
        if (!res.ok) return;
        const providers = await res.json();
        for (const provider of (providers || [])) {
            const mRes = await apiCall(`/api/providers/${provider.id}/models`);
            if (!mRes.ok) continue;
            const modelConfig = await mRes.json();
            const typeModels = (modelConfig && modelConfig[modelType]) || {};
            Object.keys(typeModels).forEach(modelId => {
                const opt = document.createElement('option');
                opt.value = `${provider.id}:${modelId}`;
                opt.textContent = `${modelId} (${provider.name})`;
                selectEl.appendChild(opt);
            });
        }
        if (currentValue) selectEl.value = currentValue;
    } catch (e) {
        console.warn('Failed to load model options:', e);
    }
}
