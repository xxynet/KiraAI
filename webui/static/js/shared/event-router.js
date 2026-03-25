/**
 * Data-action event router
 * Provides a declarative alternative to button-text matching in event handlers.
 *
 * Usage:
 *   // Register a handler
 *   EventRouter.on('clear-logs', clearLogs);
 *   EventRouter.on('add-provider', () => openProviderModal());
 *
 *   // HTML
 *   <button data-action="clear-logs">Clear Logs</button>
 *
 * The router sets up a single delegated click listener on document.
 * Handlers are called with (event, targetElement).
 */

const EventRouter = (() => {
    const _handlers = {};

    // Single delegated listener — installed once at parse time
    document.addEventListener('click', (e) => {
        const target = e.target.closest('[data-action]');
        if (!target) return;
        const action = target.getAttribute('data-action');
        const handler = _handlers[action];
        if (handler) {
            e.preventDefault();
            handler(e, target);
        }
    });

    return {
        /**
         * Register a handler for an action.
         * @param {string}   action  - Value of the data-action attribute
         * @param {Function} handler - Called with (event, element)
         */
        on(action, handler) {
            _handlers[action] = handler;
        },

        /**
         * Remove a handler.
         * @param {string} action
         */
        off(action) {
            delete _handlers[action];
        }
    };
})();
