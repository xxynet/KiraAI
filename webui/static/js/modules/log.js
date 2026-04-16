/**
 * modules/log.js — Logging page
 * Dependencies: core/api.js (apiCall), core/state.js (AppState), core/notify.js (showNotification)
 * Global dependencies: escapeHtml, updateTranslations（still in app.js）
 */

async function loadLogsData() {
    try {
        // Fetch log configuration from backend to sync with MAX_QUEUE_SIZE
        try {
            const configResponse = await apiCall('/api/log-config');
            const configData = await configResponse.json();
            AppState.data.logConfig.maxQueueSize = configData.maxQueueSize || 100;
        } catch (configError) {
            console.warn('Failed to load log config, using default value:', configError);
            AppState.data.logConfig.maxQueueSize = 100;
        }

        // Initialize log level selector
        initLogLevelSelector();

        // Load log history
        const response = await apiCall('/api/log-history?limit=100');
        const data = await response.json();

        // Initialize log container with history
        const container = document.getElementById('log-container');
        if (container) {
            container.innerHTML = '';

            if (data.logs && data.logs.length > 0) {
                data.logs.forEach(log => {
                    addLogEntry(log);
                });

                // Scroll to bottom on first load to show latest logs
                container.scrollTop = container.scrollHeight;
            } else {
                container.innerHTML = `
                    <div class="flex justify-center items-center h-full">
                        <p class="text-gray-500" data-i18n="logs.no_logs">No logs available</p>
                    </div>
                `;
                if (window.i18n) {
                    updateTranslations();
                }
            }
        }

        // Initialize SSE connection for real-time logs
        initSSEConnection();
    } catch (error) {
        console.error('Error loading logs data:', error);
    }
}

/**
 * Initialize log level selector event listener
 */
function initLogLevelSelector() {
    const selector = document.getElementById('log-level-selector');
    if (!selector) return;

    // Load persisted levels from localStorage, fall back to all levels except debug
    let savedLevels = ['info', 'warning', 'error'];
    try {
        const raw = localStorage.getItem('log_filter_levels');
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length > 0) {
            savedLevels = parsed;
        }
    } catch (_) {}

    AppState.data.logFilter.levels = savedLevels;

    // Sync native <option selected> states to match saved levels,
    // then destroy and recreate CustomSelect so it picks up the correct initial state
    Array.from(selector.options).forEach(opt => {
        opt.selected = savedLevels.includes(opt.value);
    });
    const existingWrapper = document.querySelector(`.custom-select[data-custom-select="log-level-selector"]`);
    if (existingWrapper) existingWrapper.remove();
    if (typeof CustomSelect !== 'undefined') {
        new CustomSelect(selector, {
            placeholder: selector.getAttribute('data-placeholder') || 'Select Level',
            multiple: true,
            maxHeight: parseInt(selector.getAttribute('data-max-height')) || 300,
        });
    }

    // Persist on change (remove previous listener first to avoid duplicates on re-visit)
    if (selector._logLevelChangeHandler) {
        selector.removeEventListener('change', selector._logLevelChangeHandler);
    }
    selector._logLevelChangeHandler = () => {
        const selected = Array.from(selector.selectedOptions).map(o => o.value);
        AppState.data.logFilter.levels = selected.length > 0 ? selected : ['info', 'warning', 'error'];
        localStorage.setItem('log_filter_levels', JSON.stringify(AppState.data.logFilter.levels));
        applyLogFilter();
    };
    selector.addEventListener('change', selector._logLevelChangeHandler);
}

/**
 * Initialize SSE connection for real-time logs
 * Uses EventSourcePolyfill with custom headers, falls back to query parameter auth
 */
function initSSEConnection() {
    // Close existing connection if any
    if (AppState.sseEventSource) {
        AppState.sseEventSource.close();
    }

    const jwtToken = localStorage.getItem('jwt_token');
    if (!jwtToken) {
        console.error('No JWT token found for SSE connection');
        return;
    }

    try {
        // Try to use EventSourcePolyfill with custom headers first
        if (typeof EventSourcePolyfill !== 'undefined') {
            console.log('Using EventSourcePolyfill with custom headers');
            try {
                AppState.sseEventSource = new EventSourcePolyfill('/api/live-log', {
                    headers: {
                        'Authorization': `Bearer ${jwtToken}`
                    },
                    heartbeatTimeout: 300000,
                    withCredentials: true
                });

                // Set up event handlers
                setupSSEEventHandlers(AppState.sseEventSource);
                return;
            } catch (polyfillError) {
                console.warn('EventSourcePolyfill failed, falling back to query parameter auth:', polyfillError);
                // Fall through to fallback strategy
            }
        }

        // Fallback: Use standard EventSource with token in query parameter
        console.log('Using fallback strategy: token in query parameter');
        const sseUrl = `/api/live-log?token=${encodeURIComponent(jwtToken)}`;
        AppState.sseEventSource = new EventSource(sseUrl);

        // Set up event handlers
        setupSSEEventHandlers(AppState.sseEventSource);

    } catch (error) {
        console.error('Error initializing SSE connection:', error);
    }
}

/**
 * Set up event handlers for SSE connection
 * @param {EventSource} eventSource - The EventSource instance
 */
function setupSSEEventHandlers(eventSource) {
    eventSource.onopen = function() {
        console.log('SSE connection established');
    };

    eventSource.onmessage = function(event) {
        try {
            const logData = JSON.parse(event.data);
            addLogEntry(logData);
        } catch (e) {
            console.error('Error parsing log data:', e);
        }
    };

    eventSource.onerror = function(err) {
        console.error('SSE connection error:', err);

        // Check for 401 error (authentication failed)
        if (err && err.status === 401) {
            console.error('Authentication failed (401), token may have expired');
            localStorage.removeItem('jwt_token');
            window.location.href = '/login';
        }

        // Close connection on error
        if (AppState.sseEventSource) {
            AppState.sseEventSource.close();
            AppState.sseEventSource = null;
        }
    };
}

/**
 * Add a log entry to the log container
 * @param {object} log - Log data object
 */
function addLogEntry(log) {
    const container = document.getElementById('log-container');
    if (!container) return;

    // Parse log data
    const timestamp = log.time || log.timestamp || new Date().toLocaleString();
    const level = log.level || 'INFO';
    const name = log.name || '';
    const message = log.message || log.content || '';
    const color = log.color || 'blue';

    // Determine visibility based on current filter (always add to DOM so filter changes can reveal it)
    const activeLevels = AppState.data.logFilter.levels;
    const isVisible = !Array.isArray(activeLevels) || checkLogLevelMatch(level, activeLevels);

    // Remove "No logs available" message if present
    const noLogsMsg = container.querySelector('[data-i18n="logs.no_logs"]');
    if (noLogsMsg) {
        container.innerHTML = '';
    }

    // Determine color class based on level
    let levelClass = 'text-gray-600';
    if (level === 'ERROR' || level === 'CRITICAL') {
        levelClass = 'text-red-600';
    } else if (level === 'WARNING') {
        levelClass = 'text-yellow-600';
    } else if (level === 'INFO') {
        levelClass = 'text-green-600';
    } else if (level === 'DEBUG') {
        levelClass = 'text-cyan-600';
    }

    // Create log entry element - all parameters on one line, wrap when overflow
    const logEntry = document.createElement('div');
    logEntry.className = 'font-mono text-base whitespace-normal break-words';

    // Format level to 7 characters wide for alignment (WARNING is 7 chars)
    const paddedLevel = escapeHtml(level).padEnd(7, ' ');

    // Build log entry with space separators (no gaps between spans)
    let logHtml = `<span class="text-gray-500 dark:text-gray-400">[${escapeHtml(timestamp)}]</span> `;
    logHtml += `<span class="${levelClass} font-semibold whitespace-pre-wrap">${paddedLevel}</span> `;
    if (name) {
        logHtml += `<span style="color: ${color}" class="font-semibold">[${escapeHtml(name)}]</span> `;
    }
    logHtml += `<span class="text-gray-700 dark:text-gray-300 whitespace-pre-wrap">${escapeHtml(message)}</span>`;

    logEntry.innerHTML = logHtml;
    if (!isVisible) logEntry.style.display = 'none';

    // Append to container
    container.appendChild(logEntry);

    // Smart auto-scroll: only scroll to bottom if user is already at the bottom
    // Calculate scroll position ratio (0 = top, 1 = bottom)
    const scrollRatio = (container.scrollTop + container.clientHeight) / container.scrollHeight;

    // Auto-scroll only if user is near the bottom (ratio > 0.99)
    if (scrollRatio > 0.95) {
        container.scrollTop = container.scrollHeight;
    }

    // Limit number of log entries to prevent memory issues
    // Remove oldest entries when exceeding maxQueueSize to maintain performance
    // This value is synced with MAX_QUEUE_SIZE from core/logging_manager.py
    const maxEntries = AppState.data.logConfig.maxQueueSize || 100;
    while (container.children.length > maxEntries) {
        container.removeChild(container.firstChild);
    }
}

/**
 * Check if log level matches any of the active filter levels
 * @param {string} logLevel - The log level from the log entry
 * @param {string[]} activeLevels - Array of active filter level values (lowercase)
 * @returns {boolean} - True if the log should be displayed
 */
function checkLogLevelMatch(logLevel, activeLevels) {
    const lower = logLevel.toLowerCase();
    // CRITICAL is treated the same as ERROR
    const normalized = lower === 'critical' ? 'error' : lower;
    return activeLevels.includes(normalized);
}

/**
 * Apply log filter to all existing log entries in the container
 * This function is called when the filter is changed
 */
function applyLogFilter() {
    const container = document.getElementById('log-container');
    if (!container) return;

    const activeLevels = AppState.data.logFilter.levels || ['debug', 'info', 'warning', 'error'];

    Array.from(container.children).forEach(child => {
        const levelSpan = child.querySelector('span:nth-child(2)');
        if (levelSpan) {
            child.style.display = checkLogLevelMatch(levelSpan.textContent.trim(), activeLevels) ? 'block' : 'none';
        }
    });

    container.scrollTop = container.scrollHeight;
}

/**
 * Render logs (legacy function, kept for compatibility)
 */
function renderLogs() {
    // This function is now handled by loadLogsData and addLogEntry
    console.log('renderLogs called - logs are now rendered via SSE');
}

function clearLogs() {
    if (confirm('Are you sure you want to clear all logs?')) {
        const container = document.getElementById('log-container');
        if (container) {
            container.innerHTML = `
                <div class="flex justify-center items-center h-full">
                    <p class="text-gray-500" data-i18n="logs.no_logs">No logs available</p>
                </div>
            `;
            if (window.i18n) {
                updateTranslations();
            }
        }
        showNotification('Logs cleared', 'success');
    }
}

function downloadLogs() {
    const container = document.getElementById('log-container');
    if (!container) return;

    const lines = Array.from(container.children)
        .filter(el => el.style.display !== 'none')
        .map(el => el.textContent.trim())
        .join('\n');

    const blob = new Blob([lines], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `logs_${new Date().toISOString().replace(/[:.]/g, '-')}.txt`;
    a.click();
    URL.revokeObjectURL(url);
}

function refreshLogs() {
    // Close existing SSE connection
    if (AppState.sseEventSource) {
        AppState.sseEventSource.close();
        AppState.sseEventSource = null;
    }

    // Reload logs data
    loadLogsData();
    showNotification('Logs refreshed', 'success');
}
