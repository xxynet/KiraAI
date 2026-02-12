/**
 * Custom Dropdown Component
 * A beautiful, reusable dropdown component with support for:
 * - Single and multiple selection
 * - Search functionality
 * - Custom styling
 * - Accessibility
 * - Dark mode support
 */

class CustomSelect {
    constructor(element, options = {}) {
        this.element = element;
        this.options = {
            placeholder: options.placeholder || 'Select an option...',
            searchable: options.searchable !== undefined ? options.searchable : false,
            multiple: options.multiple !== undefined ? options.multiple : false,
            disabled: options.disabled !== undefined ? options.disabled : false,
            onChange: options.onChange || null,
            onOpen: options.onOpen || null,
            onClose: options.onClose || null,
            maxHeight: options.maxHeight || 300,
            ...options
        };

        this.isOpen = false;
        this.selectedOptions = [];
        this.filteredOptions = [];
        this.searchTerm = '';

        this.options.disabled = this.element.disabled || this.options.disabled;

        this.init();
    }

    init() {
        // Get options from the original select element
        this.parseOriginalOptions();

        // Hide the original select element
        this.element.style.display = 'none';

        // Create custom dropdown structure
        this.createDropdown();

        // Store instance reference on container for external access
        this.container.__customSelect = this;

        // Bind events
        this.bindEvents();

        // Set initial value
        this.setValue(this.element.value);
    }

    parseOriginalOptions() {
        this.originalOptions = [];
        const options = this.element.querySelectorAll('option');

        options.forEach(option => {
            this.originalOptions.push({
                value: option.value,
                label: option.textContent || option.innerText,
                disabled: option.disabled,
                selected: option.selected
            });
        });

        this.filteredOptions = [...this.originalOptions];
    }

    createDropdown() {
        // Create container
        this.container = document.createElement('div');
        this.container.className = 'custom-select';
        this.container.setAttribute('data-custom-select', this.element.id);
        this.container.style.position = 'relative';

        // Create trigger
        this.trigger = document.createElement('div');
        this.trigger.className = 'custom-select-trigger';
        this.trigger.setAttribute('tabindex', this.options.disabled ? -1 : 0);
        this.trigger.setAttribute('role', 'combobox');
        this.trigger.setAttribute('aria-expanded', 'false');
        this.trigger.setAttribute('aria-haspopup', 'listbox');

        // Create trigger content
        this.triggerContent = document.createElement('div');
        this.triggerContent.className = 'custom-select-content';
        this.trigger.appendChild(this.triggerContent);

        // Create clear button
        this.clearButton = document.createElement('div');
        this.clearButton.className = 'custom-select-clear';
        this.clearButton.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
        `;
        this.trigger.appendChild(this.clearButton);

        // Create arrow
        this.arrow = document.createElement('div');
        this.arrow.className = 'custom-select-arrow';
        this.arrow.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
        `;
        this.trigger.appendChild(this.arrow);

        this.container.appendChild(this.trigger);

        // Create options container
        this.optionsContainer = document.createElement('div');
        this.optionsContainer.className = 'custom-select-options';
        this.optionsContainer.setAttribute('role', 'listbox');
        this.optionsContainer.style.maxHeight = `${this.options.maxHeight}px`;
        this.optionsContainer.style.zIndex = '9999';

        // Create search input if searchable
        if (this.options.searchable) {
            this.searchContainer = document.createElement('div');
            this.searchContainer.className = 'custom-select-search';

            this.searchInput = document.createElement('input');
            this.searchInput.type = 'text';
            this.searchInput.placeholder = 'Search...';
            this.searchInput.setAttribute('aria-label', 'Search options');

            this.searchContainer.appendChild(this.searchInput);
            this.optionsContainer.appendChild(this.searchContainer);
        }

        // Create options list
        this.optionsList = document.createElement('div');
        this.optionsList.className = 'custom-select-options-list';
        this.optionsContainer.appendChild(this.optionsList);

        // Create empty state
        this.emptyState = document.createElement('div');
        this.emptyState.className = 'custom-select-empty';
        this.emptyState.textContent = 'No options found';
        this.optionsContainer.appendChild(this.emptyState);

        this.container.appendChild(this.optionsContainer);

        // Insert before original select
        this.element.parentNode.insertBefore(this.container, this.element);

        // Render options
        this.renderOptions();
    }

    renderOptions() {
        this.optionsList.innerHTML = '';

        if (this.filteredOptions.length === 0) {
            this.emptyState.classList.add('show');
            return;
        }

        this.emptyState.classList.remove('show');

        this.filteredOptions.forEach((option, index) => {
            const optionElement = document.createElement('div');
            optionElement.className = 'custom-select-option';
            optionElement.setAttribute('role', 'option');
            optionElement.setAttribute('data-value', option.value);
            optionElement.setAttribute('aria-selected', option.selected ? 'true' : 'false');
            optionElement.textContent = option.label;

            if (option.disabled) {
                optionElement.classList.add('disabled');
            }

            if (option.selected) {
                optionElement.classList.add('selected');
            }

            optionElement.addEventListener('click', (e) => {
                e.stopPropagation();
                if (!option.disabled) {
                    this.selectOption(option);
                }
            });

            this.optionsList.appendChild(optionElement);
        });
    }

    bindEvents() {
        // Trigger click
        this.trigger.addEventListener('click', () => {
            if (!this.options.disabled) {
                this.toggle();
            }
        });

        // Trigger keyboard
        this.trigger.addEventListener('keydown', (e) => {
            if (this.options.disabled) return;

            switch (e.key) {
                case 'Enter':
                case ' ':
                    e.preventDefault();
                    e.stopPropagation();
                    if (this.isOpen) {
                        // Select currently highlighted option
                        const highlighted = this.optionsList.querySelector('.custom-select-option.selected');
                        if (highlighted) {
                            const value = highlighted.getAttribute('data-value');
                            const option = this.originalOptions.find(o => o.value === value);
                            if (option) {
                                this.selectOption(option);
                            }
                        }
                    } else {
                        this.toggle();
                    }
                    break;
                case 'Escape':
                    e.preventDefault();
                    e.stopPropagation();
                    this.close();
                    break;
                case 'ArrowDown':
                    e.preventDefault();
                    e.stopPropagation();
                    if (!this.isOpen) {
                        this.open();
                    } else {
                        this.navigateOptions(1);
                    }
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    e.stopPropagation();
                    if (this.isOpen) {
                        this.navigateOptions(-1);
                    }
                    break;
            }
        });

        // Clear button
        this.clearButton.addEventListener('click', (e) => {
            e.stopPropagation();
            this.clear();
        });

        // Search input
        if (this.searchInput) {
            this.searchInput.addEventListener('input', (e) => {
                this.searchTerm = e.target.value.toLowerCase();
                this.filterOptions();
            });

            this.searchInput.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    this.navigateOptions(e.key === 'ArrowDown' ? 1 : -1);
                }
            });
        }

        // Click outside
        document.addEventListener('click', (e) => {
            if (!this.container.contains(e.target)) {
                this.close();
            }
        });

        // Focus management
        this.trigger.addEventListener('focus', () => {
            this.container.classList.add('focused');
        });

        this.trigger.addEventListener('blur', () => {
            this.container.classList.remove('focused');
        });
    }

    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    }

    open() {
        if (this.isOpen || this.options.disabled) return;

        this.isOpen = true;
        this.trigger.classList.add('active');
        this.trigger.setAttribute('aria-expanded', 'true');
        this.optionsContainer.classList.add('show');

        // Calculate position to prevent overflow
        this.adjustPosition();

        if (this.options.onOpen) {
            this.options.onOpen();
        }

        // Focus search input if exists
        if (this.searchInput) {
            this.searchInput.focus();
        }
    }

    adjustPosition() {
        const triggerRect = this.trigger.getBoundingClientRect();
        const optionsHeight = this.optionsContainer.offsetHeight;
        const windowHeight = window.innerHeight;
        const spaceBelow = windowHeight - triggerRect.bottom;
        const spaceAbove = triggerRect.top;

        // Reset position
        this.optionsContainer.style.top = '';
        this.optionsContainer.style.bottom = '';

        // Check if there's enough space below
        if (spaceBelow < optionsHeight && spaceAbove > spaceBelow) {
            // Not enough space below, show above
            this.optionsContainer.style.top = 'auto';
            this.optionsContainer.style.bottom = 'calc(100% + 4px)';
        } else {
            // Show below (default)
            this.optionsContainer.style.top = 'calc(100% + 4px)';
            this.optionsContainer.style.bottom = 'auto';
        }
    }

    close() {
        if (!this.isOpen) return;

        this.isOpen = false;
        this.trigger.classList.remove('active');
        this.trigger.setAttribute('aria-expanded', 'false');
        this.optionsContainer.classList.remove('show');

        // Clear search
        if (this.searchInput) {
            this.searchInput.value = '';
            this.searchTerm = '';
            this.filterOptions();
        }

        if (this.options.onClose) {
            this.options.onClose();
        }
    }

    selectOption(option) {
        if (this.options.multiple) {
            // Multiple selection
            const index = this.selectedOptions.findIndex(o => o.value === option.value);
            if (index > -1) {
                // Deselect
                this.selectedOptions.splice(index, 1);
                option.selected = false;
            } else {
                // Select
                this.selectedOptions.push(option);
                option.selected = true;
            }
        } else {
            // Single selection
            this.selectedOptions = [option];
            this.originalOptions.forEach(o => o.selected = false);
            option.selected = true;
            this.close();
        }

        this.updateTrigger();
        this.renderOptions();
        this.updateOriginalSelect();

        if (this.options.onChange) {
            this.options.onChange(this.getValue(), this.selectedOptions);
        }
    }

    navigateOptions(direction) {
        const options = this.optionsList.querySelectorAll('.custom-select-option:not(.disabled)');
        const currentIndex = Array.from(options).findIndex(o => o.classList.contains('selected'));
        let nextIndex = currentIndex + direction;

        if (nextIndex < 0) nextIndex = options.length - 1;
        if (nextIndex >= options.length) nextIndex = 0;

        options.forEach(o => o.classList.remove('selected'));
        options[nextIndex].classList.add('selected');

        // Scroll into view
        options[nextIndex].scrollIntoView({ block: 'nearest' });
    }

    filterOptions() {
        this.filteredOptions = this.originalOptions.filter(option =>
            option.label.toLowerCase().includes(this.searchTerm)
        );
        this.renderOptions();
    }

    updateTrigger() {
        if (this.options.multiple) {
            // Multiple selection - show tags
            this.triggerContent.innerHTML = '';
            const tagsContainer = document.createElement('div');
            tagsContainer.className = 'custom-select-tags';

            this.selectedOptions.forEach(option => {
                const tag = document.createElement('span');
                tag.className = 'custom-select-tag';
                tag.textContent = option.label;

                const removeBtn = document.createElement('span');
                removeBtn.className = 'custom-select-tag-remove';
                removeBtn.innerHTML = '×';
                removeBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.selectOption(option);
                });

                tag.appendChild(removeBtn);
                tagsContainer.appendChild(tag);
            });

            this.triggerContent.appendChild(tagsContainer);

            if (this.selectedOptions.length === 0) {
                this.trigger.classList.add('placeholder');
                this.triggerContent.textContent = this.options.placeholder;
            } else {
                this.trigger.classList.remove('placeholder');
            }
        } else {
            // Single selection - show selected value or placeholder
            if (this.selectedOptions.length > 0) {
                this.trigger.classList.remove('placeholder');
                this.trigger.classList.add('has-value');
                this.triggerContent.textContent = this.selectedOptions[0].label;
            } else {
                this.trigger.classList.add('placeholder');
                this.trigger.classList.remove('has-value');
                this.triggerContent.textContent = this.options.placeholder;
            }
        }
    }

    updateOriginalSelect() {
        const options = this.element.querySelectorAll('option');
        options.forEach(option => {
            const isSelected = this.selectedOptions.some(o => o.value === option.value);
            option.selected = isSelected;
        });

        // Trigger change event on the original select element
        const changeEvent = new Event('change', {
            bubbles: true,
            cancelable: true
        });
        this.element.dispatchEvent(changeEvent);
    }

    getValue() {
        if (this.options.multiple) {
            return this.selectedOptions.map(o => o.value);
        }
        return this.selectedOptions.length > 0 ? this.selectedOptions[0].value : '';
    }

    setValue(value, { silent = false } = {}) {
        if (this.options.multiple) {
            const values = Array.isArray(value) ? value : [value];
            this.selectedOptions = this.originalOptions.filter(o => values.includes(o.value));
        } else {
            this.selectedOptions = this.originalOptions.filter(o => o.value === value);
        }

        this.originalOptions.forEach(o => {
            o.selected = this.selectedOptions.some(s => s.value === o.value);
        });

        this.updateTrigger();
        this.renderOptions();
        if (!silent) {
            this.updateOriginalSelect();
            if (this.options.onChange) {
                this.options.onChange(this.getValue(), this.selectedOptions);
            }
        }
    }

    clear() {
        this.selectedOptions = [];
        this.originalOptions.forEach(o => o.selected = false);
        this.updateTrigger();
        this.renderOptions();
        this.updateOriginalSelect();

        if (this.options.onChange) {
            this.options.onChange(this.getValue(), this.selectedOptions);
        }
    }

    disable() {
        this.options.disabled = true;
        this.trigger.setAttribute('tabindex', -1);
        this.container.classList.add('disabled');
    }

    enable() {
        this.options.disabled = false;
        this.trigger.setAttribute('tabindex', 0);
        this.container.classList.remove('disabled');
    }

    destroy() {
        this.container.remove();
        this.element.style.display = '';
    }

    refresh(silent = true) {
        const currentValue = this.getValue();
        this.originalOptions = [];
        this.parseOriginalOptions();
        this.filteredOptions = [...this.originalOptions];
        this.setValue(currentValue, { silent });
    }
}

// Initialize all custom selects when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const selects = document.querySelectorAll('select[data-custom-select]');
    selects.forEach(select => {
        const options = {
            placeholder: select.getAttribute('data-placeholder') || 'Select an option...',
            searchable: select.getAttribute('data-searchable') === 'true',
            multiple: select.getAttribute('data-multiple') === 'true',
            disabled: select.disabled,
            maxHeight: parseInt(select.getAttribute('data-max-height')) || 300
        };

        new CustomSelect(select, options);
    });
});

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CustomSelect;
}
