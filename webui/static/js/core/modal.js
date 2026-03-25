/**
 * core/modal.js — Modal show/hide primitive + confirm dialog
 *
 * Modal.show(id)                         — remove hidden, add flex
 * Modal.hide(id)                         — add hidden, remove flex
 * Modal.confirm(title, msg, onConfirm)   — open delete-modal, store callback
 * Modal.confirmClose()                   — close delete-modal, clear callback
 * Modal.confirmExecute()                 — run stored callback
 */

// Tracks pending close-animation handlers so show() can cancel them
const _closeHandlers = new Map();

const Modal = {
    show(id) {
        const el = document.getElementById(id);
        if (!el) return;

        // Cancel any in-progress close animation
        const pending = _closeHandlers.get(id);
        if (pending) {
            el.removeEventListener('animationend', pending);
            _closeHandlers.delete(id);
        }

        el.classList.remove('hidden', 'modal-closing');
        el.classList.add('flex', 'modal-opening');
    },

    hide(id, onHidden) {
        const el = document.getElementById(id);
        if (!el) return;

        el.classList.remove('modal-opening');
        el.classList.add('modal-closing');

        const handler = (e) => {
            if (e.target !== el) return; // ignore child element animationend
            el.classList.remove('modal-closing', 'flex');
            el.classList.add('hidden');
            _closeHandlers.delete(id);
            el.removeEventListener('animationend', handler);
            if (typeof onHidden === 'function') onHidden();
        };
        _closeHandlers.set(id, handler);
        el.addEventListener('animationend', handler);
    }
};

// ── Confirm / Delete dialog ───────────────────────────────────────────────────

let _confirmHandler = null;

Modal.confirm = function (title, message, onConfirm) {
    const titleEl = document.getElementById('delete-modal-title');
    const messageEl = document.getElementById('delete-modal-message');
    if (titleEl) titleEl.textContent = title;
    if (messageEl) messageEl.textContent = message;
    _confirmHandler = onConfirm;
    Modal.show('delete-modal');
};

Modal.confirmClose = function () {
    Modal.hide('delete-modal');
    _confirmHandler = null;
};

Modal.confirmExecute = async function () {
    if (typeof _confirmHandler === 'function') {
        await _confirmHandler();
    }
};
