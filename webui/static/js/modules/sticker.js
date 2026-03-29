/**
 * modules/sticker.js — sticker management module
 * Dependencies: core/api.js (apiCall), core/state.js (AppState),
 *       core/notify.js (showNotification), core/modal.js (Modal)
 * Global dependencies: escapeHtml, updateTranslations, openDeleteModal, closeDeleteModal（still in app.js）
 */

async function loadStickerData() {
    try {
        const response = await apiCall('/api/stickers');
        const data = await response.json();
        AppState.data.stickers = Array.isArray(data) ? data : (data.stickers || []);
        renderStickerList();
    } catch (error) {
        console.error('Error loading sticker data:', error);
    }
}

function renderStickerList() {
    const container = document.getElementById('sticker-list');
    if (!container) return;

    if (!AppState.data.stickers || AppState.data.stickers.length === 0) {
        container.innerHTML = `
            <div class="flex justify-center items-center py-12">
                <div class="text-center">
                    <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                    </svg>
                    <p class="text-gray-500" data-i18n="sticker.no_stickers">No stickers configured</p>
                </div>
            </div>
        `;
        if (window.i18n) {
            updateTranslations();
        }
        return;
    }

    const cards = AppState.data.stickers.map(sticker => {
        const id = sticker.id || '';
        const path = sticker.path || '';
        const desc = sticker.desc || '';
        const imgSrc = path ? `/sticker/${encodeURIComponent(path)}` : '';
        const titleText = id ? `Sticker ${id}` : 'Sticker';
        const altText = desc || titleText;
        return `
            <div class="bg-white dark:bg-gray-900 rounded-lg shadow overflow-hidden flex flex-col">
                <div class="relative bg-gray-100 dark:bg-gray-800 flex items-center justify-center pt-[100%]">
                    ${imgSrc
                        ? `<img src="${imgSrc}" alt="${escapeHtml(altText)}" class="absolute inset-0 w-full h-full object-contain">`
                        : `<div class="text-gray-400 text-sm" data-i18n="sticker.no_stickers">No stickers configured</div>`}
                </div>
                <div class="p-4 flex-1 flex flex-col">
                    <div class="flex items-center justify-between mb-2">
                        <span class="text-sm font-semibold text-gray-800 dark:text-gray-100">#${escapeHtml(String(id))}</span>
                    </div>
                    <p class="text-sm text-gray-600 dark:text-gray-300 overflow-hidden text-ellipsis whitespace-nowrap" title="${escapeHtml(desc || '')}">${escapeHtml(desc || '')}</p>
                    <div class="mt-3 flex items-center justify-end space-x-3">
                        <button class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800" type="button" data-i18n="sticker.edit" onclick="openStickerModal('${escapeHtml(String(id))}')">
                            Edit
                        </button>
                        <button class="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30" type="button" data-i18n="sticker.delete" onclick="deleteSticker('${escapeHtml(String(id))}')">
                            Delete
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = `
        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
            ${cards}
        </div>
    `;
    if (window.i18n) {
        updateTranslations();
    }
}

async function openStickerModal(id) {
    const modal = document.getElementById('sticker-modal');
    if (!modal) return;

    const idInput = document.getElementById('sticker-id');
    const pathInput = document.getElementById('sticker-path');
    const descInput = document.getElementById('sticker-desc');
    const fileInput = document.getElementById('sticker-file');
    const fileGroup = document.getElementById('sticker-file-group');
    const titleEl = document.getElementById('sticker-modal-title');

    if (!id) {
        showNotification('Sticker ID is required', 'error');
        return;
    }

    try {
        const response = await apiCall(`/api/stickers/${encodeURIComponent(id)}`);
        if (!response.ok) {
            throw new Error(`Failed to load sticker: ${response.status}`);
        }
        const data = await response.json();

        if (idInput) idInput.value = data.id || '';
        if (pathInput) pathInput.value = data.path || '';
        if (descInput) descInput.value = data.desc || '';
        if (fileInput) fileInput.value = '';
        if (fileGroup) {
            fileGroup.style.display = 'none';
        }
        if (pathInput && pathInput.parentElement) {
            pathInput.parentElement.style.display = '';
        }
        if (titleEl) {
            titleEl.setAttribute('data-i18n', 'sticker.modal_title_edit');
            if (window.i18n) {
                titleEl.textContent = window.i18n.t('sticker.modal_title_edit');
            }
        }

        modal.dataset.mode = 'edit';
        Modal.show('sticker-modal', closeStickerModal);
    } catch (error) {
        console.error('Error loading sticker:', error);
        showNotification('Failed to load sticker', 'error');
    }
}

function closeStickerModal() {
    const modal = document.getElementById('sticker-modal');
    if (!modal) return;
    Modal.hide('sticker-modal');
    delete modal.dataset.mode;
}

function openAddStickerModal() {
    const modal = document.getElementById('sticker-modal');
    if (!modal) return;

    const idInput = document.getElementById('sticker-id');
    const pathInput = document.getElementById('sticker-path');
    const descInput = document.getElementById('sticker-desc');
    const fileInput = document.getElementById('sticker-file');
    const fileGroup = document.getElementById('sticker-file-group');
    const titleEl = document.getElementById('sticker-modal-title');

    if (idInput) idInput.value = '';
    if (pathInput) pathInput.value = '';
    if (descInput) descInput.value = '';
    if (fileInput) fileInput.value = '';
    if (window.__stickerDropzoneInstance && typeof window.__stickerDropzoneInstance.reset === 'function') {
        window.__stickerDropzoneInstance.reset();
    }
    if (fileGroup) {
        fileGroup.style.display = '';
    }
    if (pathInput && pathInput.parentElement) {
        pathInput.parentElement.style.display = 'none';
    }
    if (titleEl) {
        titleEl.setAttribute('data-i18n', 'sticker.modal_title_add');
        if (window.i18n) {
            titleEl.textContent = window.i18n.t('sticker.modal_title_add');
        }
    }

    modal.dataset.mode = 'add';
    Modal.show('sticker-modal', closeStickerModal);
}

async function saveSticker() {
    const modal = document.getElementById('sticker-modal');
    const mode = modal && modal.dataset.mode ? modal.dataset.mode : 'edit';
    const idInput = document.getElementById('sticker-id');
    const pathInput = document.getElementById('sticker-path');
    const descInput = document.getElementById('sticker-desc');
    const fileInput = document.getElementById('sticker-file');

    const id = idInput ? idInput.value.trim() : '';
    const path = pathInput ? pathInput.value.trim() : '';
    const desc = descInput ? descInput.value.trim() : '';

    if (mode === 'edit' && !id) {
        showNotification('Sticker ID is required', 'error');
        return;
    }

    if (mode === 'add') {
        if (!fileInput || !fileInput.files || !fileInput.files[0]) {
            showNotification('Sticker image is required', 'error');
            return;
        }
        try {
            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            if (id) {
                formData.append('id', id);
            }
            if (desc) {
                formData.append('description', desc);
            }
            const response = await apiCall('/api/stickers', {
                method: 'POST',
                body: formData,
            });
            if (!response.ok) {
                throw new Error(`Failed to save sticker: ${response.status}`);
            }
            showNotification('Sticker saved', 'success');
            closeStickerModal();
            await loadStickerData();
        } catch (error) {
            console.error('Error saving sticker:', error);
            showNotification('Failed to save sticker', 'error');
        }
        return;
    }

    try {
        const response = await apiCall(`/api/stickers/${encodeURIComponent(id)}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ desc })
        });

        if (!response.ok) {
            throw new Error(`Failed to save sticker: ${response.status}`);
        }

        showNotification('Sticker saved', 'success');
        closeStickerModal();
        await loadStickerData();
    } catch (error) {
        console.error('Error saving sticker:', error);
        showNotification('Failed to save sticker', 'error');
    }
}

async function deleteSticker(id) {
    const sid = String(id || '').trim();
    if (!sid) {
        showNotification('Sticker ID is required', 'error');
        return;
    }
    const title = window.i18n ? window.i18n.t('sticker.delete_confirm_title') : 'Delete Sticker';
    const message = window.i18n ? window.i18n.t('sticker.delete_confirm_message') : 'Are you sure you want to delete this sticker? This action cannot be undone.';
    openDeleteModal(title, message, async () => {
        try {
            const response = await apiCall(`/api/stickers/${encodeURIComponent(sid)}?delete_file=true`, {
                method: 'DELETE'
            });
            if (!response.ok && response.status !== 204) {
                throw new Error(`Failed to delete sticker: ${response.status}`);
            }
            showNotification(window.i18n ? window.i18n.t('sticker.delete_success') : 'Sticker deleted successfully', 'success');
            closeDeleteModal();
            await loadStickerData();
        } catch (error) {
            console.error('Error deleting sticker:', error);
            showNotification(window.i18n ? window.i18n.t('sticker.delete_failed') : 'Failed to delete sticker', 'error');
        }
    });
}
