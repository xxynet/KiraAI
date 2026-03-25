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
    if (selector) {
        // Set initial value from state
        selector.value = AppState.data.logFilter.level || 'all';

        // Add change event listener
        selector.addEventListener('change', (e) => {
            const selectedLevel = e.target.value;
            AppState.data.logFilter.level = selectedLevel;
            applyLogFilter();
        });
    }
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

    // Apply log level filter
    const currentFilter = AppState.data.logFilter.level;
    if (currentFilter !== 'all') {
        const shouldShow = checkLogLevelMatch(level, currentFilter);
        if (!shouldShow) {
            return;  // Skip this log entry if it doesn't match the filter
        }
    }

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
 * Check if log level matches the selected filter
 * @param {string} logLevel - The log level from the log entry
 * @param {string} filterLevel - The selected filter level
 * @returns {boolean} - True if the log should be displayed
 */
function checkLogLevelMatch(logLevel, filterLevel) {
    const upperLogLevel = logLevel.toUpperCase();
    const upperFilterLevel = filterLevel.toUpperCase();

    switch (upperFilterLevel) {
        case 'ERROR':
            return upperLogLevel === 'ERROR' || upperLogLevel === 'CRITICAL';
        case 'WARNING':
            return upperLogLevel === 'WARNING';
        case 'INFO':
            return upperLogLevel === 'INFO';
        case 'DEBUG':
            return upperLogLevel === 'DEBUG';
        default:
            return false;
    }
}

/**
 * Apply log filter to all existing log entries in the container
 * This function is called when the filter is changed
 */
function applyLogFilter() {
    const container = document.getElementById('log-container');
    if (!container) return;

    // Get current filter state
    const currentFilter = AppState.data.logFilter.level;

    // If filter is 'all', show all logs
    if (currentFilter === 'all') {
        Array.from(container.children).forEach(child => {
            child.style.display = 'block';
        });
        // Scroll to bottom after showing all logs
        container.scrollTop = container.scrollHeight;
        return;
    }

    // Hide/show log entries based on filter
    // Parse each log entry to extract the log level and apply filter
    Array.from(container.children).forEach(child => {
        // Find the level span element (second span in the log entry)
        const levelSpan = child.querySelector('span:nth-child(2)');
        if (levelSpan) {
            const logLevel = levelSpan.textContent.trim();
            const shouldShow = checkLogLevelMatch(logLevel, currentFilter);
            child.style.display = shouldShow ? 'block' : 'none';
        }
    });

    // Scroll to bottom after applying filter
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
