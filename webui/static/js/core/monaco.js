/**
 * core/monaco.js — Unified Monaco Editor registry
 *
 * Manages all Monaco editor instances in one place so theme syncing,
 * disposal, and waiting-for-load logic are not duplicated across modules.
 *
 * API:
 *   Monaco.init()                                          — configure loader and start loading eagerly; returns the load Promise
 *   Monaco.load()                                          — returns the singleton load Promise (safe to call multiple times)
 *   Monaco.waitForMonaco()                                 — async, awaits the singleton load Promise
 *   Monaco.register(key, container, lang, val, extraOpts)  — dispose old + create new instance; returns instance
 *   Monaco.get(key)                                        — returns registered instance or null
 *   Monaco.getValue(key)                                   — returns editor value, or '' if not found
 *   Monaco.dispose(key)                                    — dispose instance and remove from registry
 *   Monaco.setLanguage(key, language)                      — update model language of a registered instance
 *   Monaco.syncTheme()                                     — push current dark/light theme to all instances
 */
const Monaco = (() => {
    const _instances = {};
    let _loadPromise = null;  // singleton — created once in init()

    const _defaultOptions = {
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        folding: true,
        lineNumbers: 'on',
        fontSize: 14,
    };

    function _isDark() {
        return document.documentElement.classList.contains('dark');
    }

    /**
     * Configure the AMD loader and start fetching Monaco from CDN immediately.
     * Call once at startup (DOMContentLoaded). Returns the load Promise so callers
     * can chain .then() without a separate load() call.
     */
    function init() {
        require.config({ paths: { 'vs': 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs' } });
        if (!_loadPromise) {
            _loadPromise = new Promise(resolve => {
                require(['vs/editor/editor.main'], resolve);
            });
        }
        return _loadPromise;
    }

    /**
     * Returns the singleton load Promise. Safe to call multiple times —
     * Monaco is only fetched from CDN once.
     */
    function load() {
        return _loadPromise || init();
    }

    /**
     * Await this before calling register() from an async context.
     * Resolves immediately if Monaco is already loaded.
     */
    async function waitForMonaco() {
        await load();
    }

    /**
     * Create (or replace) a Monaco editor instance under the given key.
     * If an instance already exists for this key it is disposed first.
     * Requires the global `monaco` to already be available.
     *
     * @param {string}      key          - Unique identifier (e.g. 'config', 'persona', 'session', 'mcp')
     * @param {HTMLElement} container    - DOM container for the editor
     * @param {string}      language     - Monaco language id (e.g. 'json', 'text')
     * @param {string}      initialValue - Initial editor content
     * @param {object}      extraOptions - Options merged on top of defaults
     * @returns {monaco.editor.IStandaloneCodeEditor}
     */
    function register(key, container, language, initialValue, extraOptions) {
        if (_instances[key]) {
            _instances[key].dispose();
        }
        const editor = monaco.editor.create(container, {
            value: initialValue || '',
            language: language || 'plaintext',
            theme: _isDark() ? 'vs-dark' : 'vs',
            ..._defaultOptions,
            ...(extraOptions || {}),
        });
        _instances[key] = editor;
        return editor;
    }

    /** Return the registered instance for key, or null. */
    function get(key) {
        return _instances[key] || null;
    }

    /** Return the current value of the editor, or '' if not found. */
    function getValue(key) {
        const inst = _instances[key];
        return inst ? inst.getValue() : '';
    }

    /** Dispose the instance and remove it from the registry. */
    function dispose(key) {
        const inst = _instances[key];
        if (inst) {
            inst.dispose();
            delete _instances[key];
        }
    }

    /** Update the model language of a registered instance. */
    function setLanguage(key, language) {
        const inst = _instances[key];
        if (inst && typeof monaco !== 'undefined') {
            monaco.editor.setModelLanguage(inst.getModel(), language);
        }
    }

    /**
     * Sync dark/light theme to ALL Monaco editor instances globally.
     * Uses monaco.editor.setTheme() so unregistered instances (e.g. config
     * field editors in render-config-fields.js) are covered too.
     */
    function syncTheme() {
        if (typeof monaco === 'undefined') return;
        monaco.editor.setTheme(_isDark() ? 'vs-dark' : 'vs');
    }

    return { init, load, waitForMonaco, register, get, getValue, dispose, setLanguage, syncTheme };
})();

// Start loading Monaco from CDN immediately when this script is parsed,
// before DOMContentLoaded, so it's ready by the time any editor is needed.
Monaco.init();
