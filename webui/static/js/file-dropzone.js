class FileDropzone {
    constructor(container, options = {}) {
        this.container = typeof container === 'string'
            ? document.getElementById(container)
            : container;
        this.options = {
            inputId: options.inputId || null,
            titleKey: options.titleKey || 'dropzone.file_title',
            titleFallback: options.titleFallback || 'Drop a file here or click to select',
            reselectKey: options.reselectKey || 'dropzone.file_reselect',
            reselectFallback: options.reselectFallback || 'Click or drag to reselect',
            iconSvg: options.iconSvg || null,
            onFileChange: options.onFileChange || null,
        };
        this.input = this.options.inputId
            ? document.getElementById(this.options.inputId)
            : null;
        this.iconEl = null;
        this.textEl = null;
        this.hintEl = null;
        this.init();
    }

    getText(key, fallback) {
        if (window.i18n && typeof window.i18n.t === 'function') {
            const value = window.i18n.t(key);
            if (value && value !== key) return value;
        }
        return fallback;
    }

    init() {
        if (!this.container) return;
        this.container.classList.add(
            'border', 'border-dashed', 'border-gray-300', 'dark:border-gray-600',
            'rounded-lg', 'px-4', 'py-6',
            'flex', 'flex-col', 'items-center', 'justify-center', 'space-y-2',
            'cursor-pointer', 'bg-gray-50', 'dark:bg-gray-800',
            'hover:bg-gray-100', 'dark:hover:bg-gray-700', 'transition-colors'
        );
        this.renderContent();
        this.bindEvents();
    }

    renderContent() {
        this.container.innerHTML = '';

        this.iconEl = document.createElement('div');
        this.iconEl.innerHTML = this.options.iconSvg || `
            <svg class="w-10 h-10 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path>
            </svg>`;

        this.textEl = document.createElement('p');
        this.textEl.className = 'text-sm text-gray-600 dark:text-gray-300';
        this.textEl.textContent = this.getText(this.options.titleKey, this.options.titleFallback);

        this.hintEl = document.createElement('p');
        this.hintEl.className = 'text-xs text-gray-400 dark:text-gray-500';
        this.hintEl.textContent = this.getText(this.options.reselectKey, this.options.reselectFallback);
        this.hintEl.style.display = 'none';

        this.container.appendChild(this.iconEl);
        this.container.appendChild(this.textEl);
        this.container.appendChild(this.hintEl);
    }

    bindEvents() {
        this.container.addEventListener('click', () => {
            if (this.input) this.input.click();
        });
        this.container.addEventListener('dragover', (e) => {
            e.preventDefault();
            this.container.classList.add('bg-gray-100', 'dark:bg-gray-700');
        });
        this.container.addEventListener('dragleave', (e) => {
            e.preventDefault();
            this.container.classList.remove('bg-gray-100', 'dark:bg-gray-700');
        });
        this.container.addEventListener('drop', (e) => {
            e.preventDefault();
            this.container.classList.remove('bg-gray-100', 'dark:bg-gray-700');
            const file = e.dataTransfer?.files?.[0];
            if (!file) return;
            if (this.input) {
                const dt = new DataTransfer();
                dt.items.add(file);
                this.input.files = dt.files;
            }
            this.setFile(file);
            if (typeof this.options.onFileChange === 'function') {
                this.options.onFileChange(file);
            }
        });
        if (this.input) {
            this.input.addEventListener('change', () => {
                const file = this.input.files?.[0];
                if (file) {
                    this.setFile(file);
                    if (typeof this.options.onFileChange === 'function') {
                        this.options.onFileChange(file);
                    }
                } else {
                    this.reset();
                }
            });
        }
    }

    setFile(file) {
        this.container.classList.remove('border-gray-300', 'dark:border-gray-600', 'bg-gray-50', 'dark:bg-gray-800');
        this.container.classList.add('border-green-400', 'dark:border-green-500', 'bg-green-50', 'dark:bg-green-900/20');
        if (this.iconEl) {
            this.iconEl.innerHTML = `
                <svg class="w-10 h-10 text-green-500 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                </svg>`;
        }
        if (this.textEl) {
            this.textEl.className = 'text-sm text-green-700 dark:text-green-300 font-medium';
            this.textEl.textContent = file && file.name ? file.name : this.getText('dropzone.file_selected', 'File selected');
        }
        if (this.hintEl) {
            this.hintEl.style.display = '';
            this.hintEl.textContent = this.getText(this.options.reselectKey, this.options.reselectFallback);
        }
    }

    reset() {
        this.container.classList.remove('border-green-400', 'dark:border-green-500', 'bg-green-50', 'dark:bg-green-900/20');
        this.container.classList.add('border-gray-300', 'dark:border-gray-600', 'bg-gray-50', 'dark:bg-gray-800');
        this.renderContent();
        if (this.input) this.input.value = '';
    }

    getFile() {
        return this.input?.files?.[0] || null;
    }
}

window.FileDropzone = FileDropzone;
