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
// Stack of open modal IDs (most recently opened last)
const _openStack = [];
// ESC close handlers per modal ID
const _escHandlers = new Map();

const Modal = {
    show(id, onEscape) {
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

        if (!_openStack.includes(id)) _openStack.push(id);
        if (onEscape) _escHandlers.set(id, onEscape);
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

        const idx = _openStack.indexOf(id);
        if (idx !== -1) _openStack.splice(idx, 1);
        _escHandlers.delete(id);
    }
};

// Close the topmost open modal on Escape
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || _openStack.length === 0) return;
    const id = _openStack[_openStack.length - 1];
    const handler = _escHandlers.get(id);
    if (handler) handler();
    else Modal.hide(id);
});

// ── Confirm / Delete dialog ───────────────────────────────────────────────────

let _confirmHandler = null;

Modal.confirm = function (title, message, onConfirm) {
    const titleEl = document.getElementById('delete-modal-title');
    const messageEl = document.getElementById('delete-modal-message');
    if (titleEl) titleEl.textContent = title;
    if (messageEl) messageEl.textContent = message;
    _confirmHandler = onConfirm;
    Modal.show('delete-modal', Modal.confirmClose);
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
