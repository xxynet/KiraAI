class ImageDropzone {
    constructor(container, options = {}) {
        this.container = container;
        this.options = {
            inputId: options.inputId || null,
            onFileChange: options.onFileChange || null
        };
        this.input = this.options.inputId ? document.getElementById(this.options.inputId) : null;
        this.hasFile = false;
        this.init();
    }

    getText(key, fallback) {
        if (window.i18n && typeof window.i18n.t === "function") {
            const value = window.i18n.t(key);
            if (value && value !== key) {
                return value;
            }
        }
        return fallback;
    }

    init() {
        if (!this.container) return;
        this.container.classList.add(
            "border",
            "border-dashed",
            "border-gray-300",
            "dark:border-gray-600",
            "rounded-lg",
            "px-4",
            "py-6",
            "flex",
            "flex-col",
            "items-center",
            "justify-center",
            "space-y-2",
            "cursor-pointer",
            "bg-gray-50",
            "dark:bg-gray-800",
            "hover:bg-gray-100",
            "dark:hover:bg-gray-700",
            "transition-colors"
        );
        this.renderContent();
        this.bindEvents();
    }

    renderContent() {
        this.container.innerHTML = "";
        this.icon = document.createElement("div");
        this.icon.innerHTML = `
            <svg class="w-10 h-10 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 16l4-4a1 1 0 011.414 0L13 16m-2-2l1.586-1.586a1 1 0 011.414 0L21 16M5 20h14a2 2 0 002-2V7a2 2 0 00-2-2h-3.5M9 5H5a2 2 0 00-2 2v11a2 2 0 002 2z"></path>
            </svg>
        `;
        this.text = document.createElement("p");
        this.text.className = "text-sm text-gray-600 dark:text-gray-300";
        this.text.innerText = this.getText("dropzone.title", "拖拽图片到此处，或点击选择文件");
        this.hint = document.createElement("p");
        this.hint.className = "text-xs text-gray-400 dark:text-gray-500";
        this.hint.innerText = this.getText("dropzone.subtitle", "支持常见图片格式，如 JPG、PNG");
        this.container.appendChild(this.icon);
        this.container.appendChild(this.text);
        this.container.appendChild(this.hint);
    }

    bindEvents() {
        this.container.addEventListener("click", () => {
            if (this.input) {
                this.input.click();
            }
        });
        this.container.addEventListener("dragover", (e) => {
            e.preventDefault();
            this.container.classList.add("bg-gray-100", "dark:bg-gray-700");
        });
        this.container.addEventListener("dragleave", (e) => {
            e.preventDefault();
            this.container.classList.remove("bg-gray-100", "dark:bg-gray-700");
        });
        this.container.addEventListener("drop", (e) => {
            e.preventDefault();
            this.container.classList.remove("bg-gray-100", "dark:bg-gray-700");
            const files = e.dataTransfer.files;
            if (!files || !files[0]) return;
            const file = files[0];
            if (this.input) {
                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(file);
                this.input.files = dataTransfer.files;
            }
            this.setFile(file);
            if (typeof this.options.onFileChange === "function") {
                this.options.onFileChange(file);
            }
        });
        if (this.input) {
            this.input.addEventListener("change", () => {
                const file = this.input.files && this.input.files[0];
                if (file) {
                    this.setFile(file);
                    if (typeof this.options.onFileChange === "function") {
                        this.options.onFileChange(file);
                    }
                } else {
                    this.reset();
                }
            });
        }
    }

    setFile(file) {
        this.hasFile = true;
        this.container.classList.remove("border-gray-300", "dark:border-gray-600");
        this.container.classList.add("border-green-400", "dark:border-green-500", "bg-green-50", "dark:bg-green-900/20");
        if (this.icon) {
            this.icon.innerHTML = `
                <svg class="w-10 h-10 text-green-500 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                </svg>
            `;
        }
        if (this.text) {
            this.text.className = "text-sm text-green-700 dark:text-green-300";
            if (file && file.name) {
                const prefix = this.getText("dropzone.selected_prefix", "已选择文件：");
                this.text.innerText = `${prefix}${file.name}`;
            } else {
                this.text.innerText = this.getText("dropzone.selected", "已选择文件");
            }
        }
        if (this.hint) {
            this.hint.className = "text-xs text-gray-500 dark:text-gray-400";
            this.hint.innerText = this.getText("dropzone.selected_hint", "点击或拖拽可重新选择图片");
        }
    }

    reset() {
        this.hasFile = false;
        this.container.classList.remove("border-green-400", "dark:border-green-500", "bg-green-50", "dark:bg-green-900/20");
        this.container.classList.add("border-gray-300", "dark:border-gray-600", "bg-gray-50", "dark:bg-gray-800");
        this.renderContent();
    }
}

window.ImageDropzone = ImageDropzone;
