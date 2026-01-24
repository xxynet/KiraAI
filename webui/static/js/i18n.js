/**
 * i18next configuration and initialization
 * Handles internationalization for the KiraAI admin panel
 */

// Translation resources
const resources = {
    en: {
        translation: {
            app: {
                title: "KiraAI",
                subtitle: "Admin Panel"
            },
            nav: {
                overview: "Overview",
                provider: "Provider",
                adapter: "Adapter",
                persona: "Persona",
                plugin: "Plugin",
                sticker: "Sticker",
                configuration: "Configuration",
                sessions: "Sessions",
                logs: "System Logs",
                settings: "Settings"
            },
            pages: {
                overview: {
                    title: "Overview"
                },
                provider: {
                    title: "LLM Providers"
                },
                adapter: {
                    title: "Adapters"
                },
                persona: {
                    title: "Personas"
                },
                configuration: {
                    title: "Configuration"
                },
                sessions: {
                    title: "Session Management"
                },
                logs: {
                    title: "System Logs"
                },
                settings: {
                    title: "Settings"
                }
            },
            overview: {
                runtime_duration: "Runtime Duration",
                total_messages: "Total Messages",
                adapter_count: "Adapter Count",
                memory_usage: "Memory Usage",
                system_status: "System Status",
                status_unknown: "Unknown",
                status_running: "Running",
                status_stopped: "Stopped"
            },
            provider: {
                title: "LLM Providers",
                add: "Add Provider",
                add_short: "New",
                add_coming_soon: "Add provider functionality coming soon",
                no_providers: "No providers configured",
                name: "Name",
                type: "Type",
                status: "Status",
                actions: "Actions",
                modal_title: "Add Provider",
                modal_name_label: "Provider Name",
                modal_type_label: "Provider Type",
                modal_cancel: "Cancel",
                modal_save: "Save",
                select_provider: "Select a provider to configure",
                config_api_key: "API Key",
                config_base_url: "Base URL",
                config_model: "Model",
                config_status: "Status",
                model_groups: "Model Groups",
                model_group_llm: "LLM",
                model_group_tts: "TTS",
                model_group_stt: "STT",
                model_group_image: "Image",
                model_group_video: "Video",
                model_group_embedding: "Embedding",
                model_group_rerank: "Rerank",
                add_model: "Add Model",
                no_models: "No models configured",
                remove_model: "Remove Model",
                delete: "Delete"
            },
            adapter: {
                title: "Adapters",
                add: "Add Adapter",
                add_coming_soon: "Add adapter functionality coming soon",
                no_adapters: "No adapters configured",
                name: "Name",
                platform: "Platform",
                status: "Status",
                actions: "Actions"
            },
            persona: {
                title: "Personas",
                add: "Add Persona",
                add_coming_soon: "Add persona functionality coming soon",
                no_personas: "No personas configured",
                name: "Name",
                description: "Description",
                actions: "Actions",
                modal_title: "Add Persona",
                modal_name_label: "Persona Name",
                modal_content_label: "Persona Content",
                modal_cancel: "Cancel",
                modal_save: "Save",
                format_json: "JSON",
                format_yaml: "YAML",
                format_markdown: "Markdown",
                format_text: "Plain Text"
            },
            plugin: {
                title: "Plugins",
                add: "Add Plugin",
                add_coming_soon: "Add plugin functionality coming soon",
                no_plugins: "No plugins configured",
                name: "Name",
                version: "Version",
                status: "Status",
                actions: "Actions"
            },
            sticker: {
                title: "Stickers",
                add: "Add Sticker",
                add_coming_soon: "Add sticker functionality coming soon",
                no_stickers: "No stickers configured",
                name: "Name",
                category: "Category",
                status: "Status",
                actions: "Actions"
            },
            configuration: {
                title: "Configuration",
                save: "Save",
                new_file: "New File",
                file_select: "Select File",
                select_file: "Select a file...",
                format_select: "File Format",
                format_ini: "INI",
                format_json: "JSON",
                format_md: "Markdown",
                format_xml: "XML",
                editor_ready: "Editor ready",
                no_file: "No file selected",
                saved: "File saved successfully",
                copied: "Content copied to clipboard",
                downloaded: "File downloaded",
                enter_filename: "Enter filename:",
                unsupported_format: "Unsupported file format",
                refreshed: "File list refreshed",
                api_settings: "API Settings",
                api_endpoint: "API Endpoint",
                api_key: "API Key",
                system_settings: "System Settings",
                auto_refresh: "Auto Refresh",
                debug_mode: "Debug Mode"
            },
            sessions: {
                title: "Session Management",
                new: "New Session",
                no_sessions: "No active sessions",
                name: "Session Name",
                created_at: "Created At",
                type_dm: "Direct Message",
                type_gm: "Group Message",
                message_count: "Messages",
                adapter_name: "Adapter Name",
                session_type: "Session Type",
                session_id: "Session ID",
                session_data: "Session Messages",
                actions: "Actions",
                edit: "Edit",
                delete: "Delete",
                modal_title: "Edit Session",
                modal_cancel: "Cancel",
                modal_save: "Save",
                delete_confirm_title: "Confirm Delete",
                delete_confirm_message: "Are you sure you want to delete this session? This action cannot be undone.",
                saved: "Session saved successfully",
                deleted: "Session deleted successfully",
                load_failed: "Failed to load session data",
                save_failed: "Failed to save session",
                delete_failed: "Failed to delete session",
                invalid_json: "Invalid JSON format",
                invalid_array: "Messages must be an array"
            },
            logs: {
                title: "System Logs",
                clear: "Clear Logs",
                refresh: "Refresh",
                level_all: "All Levels",
                level_info: "Info",
                level_warning: "Warning",
                level_error: "Error",
                search_placeholder: "Search logs...",
                no_logs: "No logs available"
            },
            settings: {
                title: "System Settings",
                language: "Language",
                theme: "Theme",
                theme_light: "Light",
                theme_dark: "Dark",
                save: "Save Settings",
                saved: "Settings saved successfully"
            }
        }
    },
    zh: {
        translation: {
            app: {
                title: "KiraAI",
                subtitle: "管理面板"
            },
            nav: {
                overview: "概览",
                provider: "提供商",
                adapter: "适配器",
                persona: "人设",
                plugin: "插件",
                sticker: "表情包",
                configuration: "配置项",
                sessions: "会话管理",
                logs: "系统日志",
                settings: "设置"
            },
            pages: {
                overview: {
                    title: "概览"
                },
                provider: {
                    title: "LLM 提供商"
                },
                adapter: {
                    title: "适配器"
                },
                persona: {
                    title: "人设"
                },
                plugin: {
                    title: "插件"
                },
                sticker: {
                    title: "表情包"
                },
                configuration: {
                    title: "配置项"
                },
                sessions: {
                    title: "会话管理"
                },
                logs: {
                    title: "系统日志"
                },
                settings: {
                    title: "设置"
                }
            },
            overview: {
                runtime_duration: "运行时长",
                total_messages: "消息总数",
                adapter_count: "适配器数量",
                memory_usage: "内存占用",
                system_status: "系统状态",
                status_unknown: "未知",
                status_running: "运行中",
                status_stopped: "已停止"
            },
            provider: {
                title: "LLM 提供商",
                add: "添加提供商",
                add_short: "添加",
                add_coming_soon: "添加提供商功能即将推出",
                no_providers: "未配置提供商",
                name: "名称",
                type: "类型",
                status: "状态",
                actions: "操作",
                modal_title: "添加提供商",
                modal_name_label: "提供商名称",
                modal_type_label: "提供商类型",
                modal_cancel: "取消",
                modal_save: "保存",
                select_provider: "选择一个提供商进行配置",
                config_api_key: "API 密钥",
                config_base_url: "基础 URL",
                config_model: "模型",
                config_status: "状态",
                model_groups: "模型组",
                model_group_llm: "大语言模型",
                model_group_tts: "语音合成",
                model_group_stt: "语音识别",
                model_group_image: "图像",
                model_group_video: "视频",
                model_group_embedding: "向量嵌入",
                model_group_rerank: "重排序",
                add_model: "添加模型",
                no_models: "未配置模型",
                remove_model: "移除模型",
                delete: "删除"
            },
            adapter: {
                title: "适配器",
                add: "添加适配器",
                add_coming_soon: "添加适配器功能即将推出",
                no_adapters: "未配置适配器",
                name: "名称",
                platform: "平台",
                status: "状态",
                actions: "操作"
            },
            persona: {
                title: "人设",
                add: "添加人设",
                add_coming_soon: "添加人设功能即将推出",
                no_personas: "未配置人设",
                name: "名称",
                description: "描述",
                actions: "操作",
                modal_title: "添加人设",
                modal_name_label: "人设名称",
                modal_content_label: "人设内容",
                modal_cancel: "取消",
                modal_save: "保存",
                format_json: "JSON",
                format_yaml: "YAML",
                format_markdown: "Markdown",
                format_text: "纯文本"
            },
            plugin: {
                title: "插件",
                add: "添加插件",
                add_coming_soon: "添加插件功能即将推出",
                no_plugins: "未配置插件",
                name: "名称",
                version: "版本",
                status: "状态",
                actions: "操作"
            },
            sticker: {
                title: "表情包",
                add: "添加表情包",
                add_coming_soon: "添加表情包功能即将推出",
                no_stickers: "未配置表情包",
                name: "名称",
                category: "分类",
                status: "状态",
                actions: "操作"
            },
            configuration: {
                title: "配置项",
                save: "保存",
                new_file: "新建文件",
                file_select: "选择文件",
                select_file: "选择文件...",
                format_select: "文件格式",
                format_ini: "INI",
                format_json: "JSON",
                format_md: "Markdown",
                format_xml: "XML",
                editor_ready: "编辑器就绪",
                no_file: "未选择文件",
                saved: "文件保存成功",
                copied: "内容已复制到剪贴板",
                downloaded: "文件已下载",
                enter_filename: "输入文件名:",
                unsupported_format: "不支持的文件格式",
                refreshed: "文件列表已刷新",
                api_settings: "API 设置",
                api_endpoint: "API 端点",
                api_key: "API 密钥",
                system_settings: "系统设置",
                auto_refresh: "自动刷新",
                debug_mode: "调试模式"
            },
            sessions: {
                title: "会话管理",
                new: "新建会话",
                no_sessions: "无活跃会话",
                name: "会话名称",
                created_at: "创建时间",
                type_dm: "私聊",
                type_gm: "群聊",
                message_count: "消息数",
                adapter_name: "适配器名称",
                session_type: "会话类型",
                session_id: "会话 ID",
                session_data: "会话消息",
                actions: "操作",
                edit: "编辑",
                delete: "删除",
                modal_title: "编辑会话",
                modal_cancel: "取消",
                modal_save: "保存",
                delete_confirm_title: "确认删除",
                delete_confirm_message: "确定要删除此会话吗？此操作无法撤销。",
                saved: "会话保存成功",
                deleted: "会话删除成功",
                load_failed: "加载会话数据失败",
                save_failed: "保存会话失败",
                delete_failed: "删除会话失败",
                invalid_json: "JSON 格式无效",
                invalid_array: "消息必须是数组"
            },
            logs: {
                title: "系统日志",
                clear: "清除日志",
                refresh: "刷新",
                level_all: "所有级别",
                level_info: "信息",
                level_warning: "警告",
                level_error: "错误",
                search_placeholder: "搜索日志...",
                no_logs: "无可用日志"
            },
            settings: {
                title: "系统设置",
                language: "语言",
                theme: "主题",
                theme_light: "浅色",
                theme_dark: "深色",
                save: "保存设置",
                saved: "设置保存成功"
            }
        }
    }
};

// Initialize i18next
i18next
    .use(i18nextBrowserLanguageDetector)
    .init({
        resources: resources,
        fallbackLng: 'en',
        debug: false,
        interpolation: {
            escapeValue: false
        }
    })
    .then(() => {
        // Update all elements with data-i18n attribute
        updateTranslations();
        
        // Sync language selector with current language
        const languageSelector = document.getElementById('language-selector');
        if (languageSelector) {
            languageSelector.value = i18next.language;
        }
        
        // Listen for language changes
        document.getElementById('language-selector').addEventListener('change', (e) => {
            i18next.changeLanguage(e.target.value).then(() => {
                updateTranslations();
            });
        });
    });

/**
 * Update all elements with data-i18n attribute
 */
function updateTranslations() {
    document.querySelectorAll('[data-i18n]').forEach(element => {
        const key = element.getAttribute('data-i18n');
        const translation = i18next.t(key);
        if (translation && translation !== key) {
            if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
                element.placeholder = translation;
            } else {
                element.textContent = translation;
            }
        }
    });
}

// Export for use in other scripts
window.i18n = {
    t: (key) => i18next.t(key),
    changeLanguage: (lng) => i18next.changeLanguage(lng).then(() => updateTranslations())
};

