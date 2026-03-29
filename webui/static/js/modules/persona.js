/**
 * modules/persona.js — Persona management
 * Dependencies: core/api.js (apiCall), core/state.js (AppState),
 *               core/notify.js (showNotification), core/modal.js (Modal),
 *               core/monaco.js (Monaco)
 * Global dependencies: escapeHtml, updateTranslations (still in app.js)
 */

async function loadPersonaData() {
    try {
        // Fetch current persona content from backend
        const response = await apiCall('/api/personas/current/content');
        const data = await response.json();

        // Store persona content
        AppState.data.personaContent = data.content || '';
        AppState.data.personaFormat = data.format || 'text';

        // Render default persona card
        renderDefaultPersonaCard();

        // Update editor content if already open, otherwise do nothing —
        // the editor is created in openPersonaModal() when the container is visible.
        Monaco.get('persona')?.setValue(AppState.data.personaContent);

        // Update format selector
        const formatSelector = document.getElementById('persona-format');
        if (formatSelector) {
            formatSelector.value = AppState.data.personaFormat || 'text';
        }
    } catch (error) {
        console.error('Error loading persona data:', error);
    }
}

function renderDefaultPersonaCard() {
    const container = document.getElementById('persona-list');
    if (!container) return;

    const description = AppState.data.personaContent
        ? AppState.data.personaContent.substring(0, 150) + (AppState.data.personaContent.length > 150 ? '...' : '')
        : 'No persona content';

    const card = `
        <div class="bg-white border border-gray-200 rounded-lg p-6 glass-card cursor-pointer hover:shadow-lg transition-shadow" onclick="editPersona('default')">
            <div class="flex justify-between items-start mb-4">
                <div>
                    <h4 class="text-lg font-semibold text-gray-900">default</h4>
                    <p class="text-sm text-gray-500 mt-1">${escapeHtml(description)}</p>
                </div>
                <div class="flex space-x-2">
                    <button class="text-blue-600 hover:text-blue-900 text-sm" onclick="event.stopPropagation(); editPersona('default')">Edit</button>
                </div>
            </div>
        </div>
    `;

    container.innerHTML = `<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">${card}</div>`;
}

/**
 * Render persona list
 */
function renderPersonaList() {
    const container = document.getElementById('persona-list');
    if (!container) return;

    if (AppState.data.personas.length === 0) {
        container.innerHTML = `
            <div class="flex justify-center items-center py-12">
                <div class="text-center">
                    <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                    </svg>
                    <p class="text-gray-500" data-i18n="persona.no_personas">No personas configured</p>
                </div>
            </div>
        `;
        if (window.i18n) {
            updateTranslations();
        }
        return;
    }

    const cards = AppState.data.personas.map(persona => `
        <div class="bg-white border border-gray-200 rounded-lg p-6 glass-card">
            <div class="flex justify-between items-start mb-4">
                <div>
                    <h4 class="text-lg font-semibold text-gray-900">${escapeHtml(persona.name || 'Unnamed Persona')}</h4>
                    <p class="text-sm text-gray-500 mt-1">${escapeHtml(persona.description || 'No description')}</p>
                </div>
                <div class="flex space-x-2">
                    <button class="text-blue-600 hover:text-blue-900 text-sm" onclick="editPersona('${persona.id || ''}')">Edit</button>
                    <button class="text-red-600 hover:text-red-900 text-sm" onclick="deletePersona('${persona.id || ''}')">Delete</button>
                </div>
            </div>
        </div>
    `).join('');

    container.innerHTML = `<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">${cards}</div>`;
}

function editPersona(id) {
    // Open persona modal for editing
    openPersonaModal();
}

function deletePersona(id) {
    if (confirm('Are you sure you want to delete this persona?')) {
        showNotification('Delete persona functionality coming soon', 'info');
    }
}

function openPersonaModal() {
    Modal.show('persona-modal', closePersonaModal);
    document.getElementById('persona-format').value = AppState.data.personaFormat || 'text';
    Monaco.load().then(() => createPersonaEditor());
}

/**
 * Close persona modal
 */
function closePersonaModal() {
    Modal.hide('persona-modal', () => {
        Monaco.dispose('persona');
    });
}

/**
 * Create Monaco Editor instance for persona
 */
function createPersonaEditor() {
    const container = document.getElementById('persona-editor-container');
    if (!container) return;

    const editor = Monaco.register('persona', container,
        AppState.data.personaFormat || 'text',
        AppState.data.personaContent || '',
        { renderWhitespace: 'selection' }
    );

    // The modal just became visible; trigger layout on the next paint so Monaco
    // measures the correct container dimensions instead of zero.
    requestAnimationFrame(() => editor.layout());

    // Set up format selector change event
    const formatSelector = document.getElementById('persona-format');
    if (formatSelector) {
        formatSelector.addEventListener('change', (e) => {
            AppState.data.personaFormat = e.target.value;
            Monaco.setLanguage('persona', AppState.data.personaFormat);
        });
    }
}

/**
 * Save persona
 */
async function savePersona() {
    // Get content from editor
    const content = Monaco.getValue('persona');

    if (!content.trim()) {
        showNotification('Please enter persona content', 'error');
        return;
    }

    try {
        // Save persona content to backend
        const response = await apiCall('/api/personas/current/content', {
            method: 'PUT',
            body: JSON.stringify({
                content: content
            })
        });

        if (response.ok) {
            // Update local state
            AppState.data.personaContent = content;

            // Show success notification and close modal
            showNotification('Persona saved successfully', 'success');
            closePersonaModal();
        } else {
            showNotification('Failed to save persona', 'error');
        }
    } catch (error) {
        console.error('Error saving persona:', error);
        showNotification('Error saving persona', 'error');
    }
}
