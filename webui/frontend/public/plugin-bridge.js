/**
 * PluginPageContext Bridge SDK
 *
 * Injected automatically into plugin page iframes. Establishes a
 * postMessage channel with the parent WebUI so plugin pages can receive
 * context (theme, locale, plugin identity) and call plugin APIs.
 *
 * Usage in plugin HTML:
 *   <script src="/plugin-bridge.js"></script>
 *   <script>
 *     window.PluginPageContext.ready().then(ctx => {
 *       console.log(ctx.pluginId, ctx.isDark);
 *     });
 *   </script>
 */
;(function () {
  'use strict'

  var CHANNEL = 'kira-plugin-page'
  var context = null
  var readyPromise = null
  var readyResolve = null
  var contextHandlers = []
  var themeHandlers = []
  var idCounter = 0

  // ── Helpers ─────────────────────────────────────────────────────────────

  function sendToParent(msg) {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage(Object.assign({ channel: CHANNEL }, msg), '*')
    }
  }

  function applyContext(next) {
    var prevTheme = context ? context.isDark : null
    context = next
    // Set data-theme on <html> so plugin pages can use [data-theme="dark"] CSS
    if (typeof next.isDark === 'boolean') {
      document.documentElement.setAttribute('data-theme', next.isDark ? 'dark' : 'light')
    }
    // Notify all context listeners
    for (var i = 0; i < contextHandlers.length; i++) {
      try { contextHandlers[i](context) } catch (_) {}
    }
    // Notify theme listeners only if theme actually changed
    if (prevTheme !== null && prevTheme !== next.isDark) {
      for (var j = 0; j < themeHandlers.length; j++) {
        try { themeHandlers[j](next.isDark) } catch (_) {}
      }
    }
  }

  // ── Message listener ────────────────────────────────────────────────────

  window.addEventListener('message', function (e) {
    var data = e.data
    if (!data || data.channel !== CHANNEL) return

    if (data.kind === 'context') {
      applyContext(data.context)
      if (readyResolve) {
        readyResolve(context)
        readyResolve = null
      }
    }
  })

  // ── Public API ──────────────────────────────────────────────────────────

  /**
   * Returns a Promise that resolves with the context object once the
   * parent has sent the initial context. Calling ready() after context
   * is already available resolves immediately.
   */
  function ready() {
    if (context) return Promise.resolve(context)
    if (!readyPromise) {
      readyPromise = new Promise(function (resolve) {
        readyResolve = resolve
      })
    }
    return readyPromise
  }

  /** Synchronous access to the current context (null if not yet received). */
  function getContext() {
    return context
  }

  /**
   * Subscribe to any context change (theme, locale, etc.).
   * Returns an unsubscribe function.
   */
  function onContext(handler) {
    contextHandlers.push(handler)
    return function () {
      var idx = contextHandlers.indexOf(handler)
      if (idx !== -1) contextHandlers.splice(idx, 1)
    }
  }

  /**
   * Subscribe to theme changes only.
   * handler(isDark: boolean) — called when dark mode toggles.
   * Returns an unsubscribe function.
   */
  function onThemeChange(handler) {
    themeHandlers.push(handler)
    return function () {
      var idx = themeHandlers.indexOf(handler)
      if (idx !== -1) themeHandlers.splice(idx, 1)
    }
  }

  // ── API helpers (same-origin fetch, cookie auth automatic) ──────────────

  function buildPluginApiUrl(endpoint) {
    var pluginId = context ? context.pluginId : ''
    var normalized = endpoint.replace(/^\/+/, '')
    return '/api/plugin/' + encodeURIComponent(pluginId) + '/' + normalized
  }

  function apiGet(endpoint, params) {
    var url = buildPluginApiUrl(endpoint)
    if (params) {
      var qs = new URLSearchParams(params).toString()
      if (qs) url += '?' + qs
    }
    return fetch(url, { credentials: 'same-origin' }).then(function (r) {
      return r.json()
    })
  }

  function apiPost(endpoint, body) {
    return fetch(buildPluginApiUrl(endpoint), {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    }).then(function (r) {
      return r.json()
    })
  }

  function apiUpload(endpoint, file, fieldName) {
    var fd = new FormData()
    fd.append(fieldName || 'file', file)
    return fetch(buildPluginApiUrl(endpoint), {
      method: 'POST',
      credentials: 'same-origin',
      body: fd,
    }).then(function (r) {
      return r.json()
    })
  }

  function apiDelete(endpoint) {
    return fetch(buildPluginApiUrl(endpoint), {
      method: 'DELETE',
      credentials: 'same-origin',
    }).then(function (r) {
      return r.json()
    })
  }

  // ── Expose global ───────────────────────────────────────────────────────

  window.PluginPageContext = {
    ready: ready,
    getContext: getContext,
    onContext: onContext,
    onThemeChange: onThemeChange,
    api: {
      get: apiGet,
      post: apiPost,
      upload: apiUpload,
      delete: apiDelete,
    },
  }

  // Signal the parent that the bridge is loaded
  sendToParent({ kind: 'ready' })
})()
