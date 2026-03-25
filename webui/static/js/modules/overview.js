/**
 * modules/overview.js — Homepage overview data fetching and UI updates
 * Dependencies: core/api.js (apiCall), core/state.js (AppState)
 */

async function loadOverviewData() {
    try {
        const response = await apiCall('/api/overview');
        const data = await response.json();
        AppState.data.overview = data;

        // Update statistics cards
        updateElement('stat-total-adapters', data.total_adapters || 0);
        updateElement('stat-active-adapters', data.active_adapters || 0);
        updateElement('stat-adapter-count', data.total_adapters || 0);
        updateElement('stat-total-providers', data.total_providers || 0);
        updateElement('stat-total-messages', data.total_messages || 0);

        // Update runtime duration
        const runtimeElement = document.getElementById('stat-runtime-duration');
        if (runtimeElement) {
            // Store the base timestamp for real-time updates
            AppState.data.overview.base_timestamp = Date.now();
            AppState.data.overview.runtime_duration = data.runtime_duration || 0;
            updateRuntimeDuration();
        }

        // Update memory usage
        const memoryUsage = data.memory_usage || 0;
        const totalMemory = data.total_memory || 0;
//        const memoryUsageDisplay = totalMemory > 0
//            ? `${memoryUsage} MB / ${totalMemory} MB`
//            : `${memoryUsage} MB`;
        const memoryUsageDisplay = `${memoryUsage} MB`;
        updateElement('stat-memory-usage', memoryUsageDisplay);

        // Update system status
        const statusIndicator = document.getElementById('system-status-indicator');
        const statusText = document.getElementById('system-status-text');

        if (statusIndicator && statusText) {
            const status = data.system_status || 'unknown';
            statusIndicator.className = `w-3 h-3 rounded-full mr-2 ${
                status === 'running' ? 'bg-green-500' :
                status === 'stopped' ? 'bg-red-500' : 'bg-gray-400'
            }`;

            if (window.i18n) {
                statusText.setAttribute('data-i18n', `overview.status_${status}`);
                statusText.textContent = window.i18n.t(`overview.status_${status}`);
            } else {
                statusText.textContent = status.charAt(0).toUpperCase() + status.slice(1);
            }
        }
    } catch (error) {
        console.error('Error loading overview data:', error);
    }
}

/**
 * Update runtime duration display in real-time
 */
function updateRuntimeDuration() {
    if (!AppState.data.overview || AppState.data.overview.runtime_duration === undefined) {
        return;
    }

    // Calculate elapsed time since last data fetch
    const elapsedSinceFetch = Math.floor((Date.now() - AppState.data.overview.base_timestamp) / 1000);
    const totalSeconds = AppState.data.overview.runtime_duration + elapsedSinceFetch;

    // Format the duration as HH:MM:SS
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    const formattedDuration = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;

    updateElement('stat-runtime-duration', formattedDuration);
}

/**
 * Update element text content
 * @param {string} id - Element ID
 * @param {string|number} value - Value to set
 */
function updateElement(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.textContent = value;
    }
}
