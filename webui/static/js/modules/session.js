/**
 * modules/session.js — Session management
 * Dependencies: core/api.js (apiCall), core/state.js (AppState),
 *               core/notify.js (showNotification), core/modal.js (Modal),
 *               core/monaco.js (Monaco)
 * Global dependencies: escapeHtml, getTranslation, applyTranslations,
 *                       openDeleteModal, closeDeleteModal (still in app.js)
 */

// Session editor state
const sessionEditorState = {
    instance: null,
    currentSessionId: null,
    sessionData: null
};

async function loadSessionsData() {
    try {
        const response = await apiCall('/api/sessions');
        const data = await response.json();
        AppState.data.sessions = data.sessions || [];

        renderSessionList();
    } catch (error) {
        console.error('Error loading sessions data:', error);
    }
}

/**
 * Render session list
 */
function renderSessionList() {
    const container = document.getElementById('session-list');
    if (!container) return;

    if (!AppState.data.sessions || AppState.data.sessions.length === 0) {
        container.innerHTML = `
            <div class="flex justify-center items-center py-12">
                <div class="text-center">
                    <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"></path>
                    </svg>
                    <p class="text-gray-500" data-i18n="sessions.no_sessions">No active sessions</p>
                </div>
            </div>
        `;
        applyTranslations();
        return;
    }

    // Get session type label
    const getSessionTypeLabel = (type) => {
        const labels = {
            'dm': getTranslation('sessions.type_dm', 'Direct Message'),
            'gm': getTranslation('sessions.type_gm', 'Group Message'),
            'default': type
        };
        return labels[type] || labels['default'];
    };

    // Get session type color
    const getSessionTypeColor = (type) => {
        const colors = {
            'dm': 'bg-blue-100 text-blue-800',
            'gm': 'bg-purple-100 text-purple-800',
            'default': 'bg-gray-100 text-gray-800'
        };
        return colors[type] || colors['default'];
    };

    // Build table rows
    const rows = AppState.data.sessions.map(session => {
        const sessionId = session.id || session.session_id || '';
        const adapterName = session.adapter_name || 'Unknown';
        const sessionType = session.session_type || 'unknown';
        const sessionKeyId = session.session_id || 'Unknown';
        const messageCount = session.message_count || 0;
        const sessionTitle = session.title || '';
        const maxTitleLength = 32;
        const displayTitleSource = sessionTitle || sessionKeyId || adapterName;
        const displayTitle = displayTitleSource.length > maxTitleLength
            ? displayTitleSource.slice(0, maxTitleLength) + '...'
            : displayTitleSource;

        return `
            <tr class="hover:bg-gray-50 dark:hover:bg-gray-800">
                <td class="px-6 py-4 whitespace-nowrap">
                    <div class="text-sm font-medium text-gray-900 dark:text-gray-100" title="${escapeHtml(displayTitleSource)}">${escapeHtml(displayTitle)}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <div class="text-sm text-gray-500 dark:text-gray-400">${escapeHtml(adapterName)}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <span class="px-2 py-1 text-xs rounded-full ${getSessionTypeColor(sessionType)}">
                        ${getSessionTypeLabel(sessionType)}
                    </span>
                </td>
                <td class="px-6 py-4">
                    <div class="text-sm text-gray-500 dark:text-gray-400 font-mono break-all max-w-xs">${escapeHtml(sessionKeyId)}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <div class="text-sm text-gray-500 dark:text-gray-400">${messageCount}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
                    <button class="text-blue-600 dark:text-blue-400 hover:text-blue-900 dark:hover:text-blue-300 mr-3" data-i18n="sessions.edit" onclick="editSession('${encodeURIComponent(sessionId)}')">
                        ${getTranslation('sessions.edit', 'Edit')}
                    </button>
                    <button class="text-red-600 dark:text-red-400 hover:text-red-900 dark:hover:text-red-300" data-i18n="sessions.delete" onclick="confirmDeleteSession('${encodeURIComponent(sessionId)}')">
                        ${getTranslation('sessions.delete', 'Delete')}
                    </button>
                </td>
            </tr>
        `;
    }).join('');

    // Build table
    const table = `
        <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                <thead class="bg-gray-50 dark:bg-gray-800">
                    <tr>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider" data-i18n="sessions.name">${getTranslation('sessions.name', 'Session Name')}</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider" data-i18n="sessions.adapter_name">${getTranslation('sessions.adapter_name', 'Adapter Name')}</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider" data-i18n="sessions.session_type">${getTranslation('sessions.session_type', 'Session Type')}</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider" data-i18n="sessions.session_id">${getTranslation('sessions.session_id', 'Session ID')}</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider" data-i18n="sessions.message_count">${getTranslation('sessions.message_count', 'Messages')}</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider" data-i18n="sessions.actions">${getTranslation('sessions.actions', 'Actions')}</th>
                    </tr>
                </thead>
                <tbody class="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                    ${rows}
                </tbody>
            </table>
        </div>
    `;

    container.innerHTML = table;

    // Apply translations to data-i18n elements
    applyTranslations();
}

/**
 * Edit session - opens modal with Monaco editor
 * @param {string} encodedSessionId - URL-encoded session ID
 */
async function editSession(encodedSessionId) {
    const sessionId = decodeURIComponent(encodedSessionId);

    try {
        // Fetch session data from backend
        const response = await apiCall(`/api/sessions/${encodeURIComponent(sessionId)}`);
        const data = await response.json();

        // Store session data
        sessionEditorState.currentSessionId = sessionId;
        sessionEditorState.sessionData = data;

        const titleInput = document.getElementById('session-title');
        const descriptionInput = document.getElementById('session-description');
        if (titleInput) {
            titleInput.value = data.title || '';
        }
        if (descriptionInput) {
            descriptionInput.value = data.description || '';
        }
        document.getElementById('session-modal-subtitle').textContent = sessionId;

        // Update message count
        const messageCount = data.messages ? data.messages.length : 0;
        document.getElementById('session-message-count').textContent =
            (window.i18n ? window.i18n.t('sessions.message_count') : 'Messages') + ': ' + messageCount;

        // Show modal
        Modal.show('session-modal', closeSessionModal);

        // Initialize Monaco editor for session data
        await initializeSessionEditor(data.messages || []);

    } catch (error) {
        console.error('Error loading session:', error);
        showNotification('Failed to load session data', 'error');
    }
}

/**
 * Initialize Monaco editor for session editing
 * @param {Array} messages - Array of message objects
 */
async function initializeSessionEditor(messages) {
    await Monaco.waitForMonaco();

    const container = document.getElementById('session-editor-container');
    if (!container) return;

    // Display raw JSON content to ensure consistency with file storage
    // This allows users to see exactly what is stored (e.g., [] vs [[]])
    const formattedContent = JSON.stringify(messages, null, 2);

    Monaco.register('session', container, 'json', formattedContent, {
        fontSize: 13,
        bracketPairColorization: { enabled: true },
    });
}

/**
 * Close session modal
 */
function closeSessionModal() {
    Modal.hide('session-modal', () => {
        Monaco.dispose('session');
        sessionEditorState.currentSessionId = null;
        sessionEditorState.sessionData = null;
    });
}

/**
 * Save session data
 */
async function saveSession() {
    if (!sessionEditorState.currentSessionId) {
        showNotification('No session selected', 'error');
        return;
    }

    try {
        // Get content from editor
        const content = Monaco.getValue('session');

        // Parse JSON
        let messages;
        try {
            // Check if content is empty or whitespace only
            const trimmedContent = content.trim();
            if (!trimmedContent) {
                messages = [];
            } else if (trimmedContent === '[]') {
                // Special case: User explicitly entered [] or it was loaded as [] to represent empty memory
                messages = [];
            } else {
                // Smart parsing logic:
                // 1. Try to parse directly first (in case user entered a full JSON array [[...]])
                // 2. If that fails or isn't a list of lists, try wrapping in [] (assuming user entered chunks list [...], [...])

                let parsed = null;
                let directParseSuccess = false;

                try {
                    parsed = JSON.parse(trimmedContent);
                    // Check if it's a valid list of lists
                    if (Array.isArray(parsed) && parsed.every(item => Array.isArray(item))) {
                        messages = parsed;
                        directParseSuccess = true;
                    }
                } catch (e) {
                    // Direct parse failed, proceed to wrapped parse
                }

                if (!directParseSuccess) {
                    // Try wrapping in brackets
                    messages = JSON.parse(`[${content}]`);
                }
            }
        } catch (parseError) {
            console.error('JSON Parse Error:', parseError);
            showNotification('Invalid JSON format: ' + parseError.message, 'error');
            return;
        }

        // Validate messages array
        if (!Array.isArray(messages)) {
            showNotification('Messages must be an array', 'error');
            return;
        }

        // Validate that every item in the array is also an array (chunk)
        if (!messages.every(item => Array.isArray(item))) {
            showNotification('Invalid structure: content must be a list of message lists (chunks)', 'error');
            return;
        }

        const titleInput = document.getElementById('session-title');
        const descriptionInput = document.getElementById('session-description');
        const title = titleInput ? titleInput.value.trim() : '';
        const description = descriptionInput ? descriptionInput.value.trim() : '';

        const response = await apiCall(`/api/sessions/${encodeURIComponent(sessionEditorState.currentSessionId)}`, {
            method: 'PUT',
            body: JSON.stringify({ messages, title, description })
        });

        if (response.ok) {
            showNotification('Session saved successfully', 'success');
            closeSessionModal();
            // Reload session list
            await loadSessionsData();
        } else {
            showNotification('Failed to save session', 'error');
        }
    } catch (error) {
        console.error('Error saving session:', error);
        showNotification('Failed to save session', 'error');
    }
}

/**
 * Confirm delete session - shows confirmation modal
 * @param {string} encodedSessionId - URL-encoded session ID
 */
function confirmDeleteSession(encodedSessionId) {
    const sessionId = decodeURIComponent(encodedSessionId);
    const title = window.i18n ? window.i18n.t('sessions.delete_confirm_title') : 'Delete Session';
    const message = window.i18n ? window.i18n.t('sessions.delete_confirm_message') : 'Are you sure you want to delete this session? This action cannot be undone.';
    openDeleteModal(title, message, async () => {
        try {
            const response = await apiCall(`/api/sessions/${encodeURIComponent(sessionId)}`, {
                method: 'DELETE'
            });
            if (response.ok) {
                showNotification(window.i18n ? window.i18n.t('sessions.deleted') : 'Session deleted successfully', 'success');
                closeDeleteModal();
                await loadSessionsData();
            } else {
                showNotification(window.i18n ? window.i18n.t('sessions.delete_failed') : 'Failed to delete session', 'error');
            }
        } catch (error) {
            console.error('Error deleting session:', error);
            showNotification(window.i18n ? window.i18n.t('sessions.delete_failed') : 'Failed to delete session', 'error');
        }
    });
}
