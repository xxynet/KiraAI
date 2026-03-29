/**
 * Application state
 */
const AppState = {
    currentPage: 'overview',
    refreshInterval: null,
    selectedProviderId: null,
    sseEventSource: null,
    configTab: 'message',
    configurationTabsInitialized: false,
    pluginTab: 'plugins',
    pluginTabsInitialized: false,
    data: {
        overview: null,
        providers: [],
        adapters: [],
        personas: [],
        stickers: [],
        mcpServers: [],
        settings: {},
        providerModels: {},
        configuration: null,
        configProviders: [],
        configProviderModels: {},
        logConfig: {
            maxQueueSize: 100
        },
        logFilter: {
            levels: ['debug', 'info', 'warning', 'error']
        }
    },
    personaEditor: {
        format: 'json'
    }
};
