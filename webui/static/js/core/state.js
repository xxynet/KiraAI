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
            level: 'all'
        }
    },
    editor: {
        currentFile: null,
        currentFormat: 'ini',
        files: {
            'config.ini': { content: '; Configuration file\n[database]\nhost = localhost\nport = 5432\nusername = admin\npassword = secret', format: 'ini' },
            'settings.json': { content: '{\n  "name": "KiraAI",\n  "version": "1.0.0",\n  "debug": true,\n  "features": {\n    "logging": true,\n    "metrics": false\n  }\n}', format: 'json' },
            'README.md': { content: '# KiraAI\n\n## Description\nKiraAI is an advanced AI system.\n\n## Installation\n```bash\nnpm install\n```\n\n## Usage\n```javascript\nconst kira = new KiraAI();\nkira.initialize();\n```', format: 'md' },
            'app.xml': { content: '<?xml version="1.0" encoding="UTF-8"?>\n<application>\n  <name>KiraAI</name>\n  <version>1.0.0</version>\n  <settings>\n    <debug>true</debug>\n    <logging>\n      <level>info</level>\n      <file>app.log</file>\n    </logging>\n  </settings>\n</application>', format: 'xml' }
        }
    },
    personaEditor: {
        format: 'json'
    }
};
