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
            header: {
                logout: "Logout",
                theme_toggle: "Toggle theme"
            },
            nav: {
                overview: "Overview",
                provider: "Provider",
                adapter: "Adapter",
                persona: "Persona",
                plugin: "Add-ons",
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
                    title: "Providers"
                },
                adapter: {
                    title: "Adapters"
                },
                persona: {
                    title: "Personas"
                },
                plugin: {
                    title: "Add-ons"
                },
                configuration: {
                    title: "Configuration"
                },
                sessions: {
                    title: "Sessions"
                },
                logs: {
                    title: "System Logs"
                },
                settings: {
                    title: "Settings"
                }
            },
            overview: {
                runtime_duration: "Uptime",
                total_messages: "Total Messages",
                adapter_count: "Adapter Count",
                memory_usage: "Memory Usage",
                system_status: "System Status",
                status_unknown: "Unknown",
                status_running: "Running",
                status_stopped: "Stopped"
            },
            provider: {
                title: "Providers",
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
                actions: "Actions",
                edit: "Edit",
                delete: "Delete",
                platform_placeholder: "Select adapter platform...",
                modal_title: "Adapter",
                modal_name_label: "Adapter Name",
                modal_platform_label: "Platform",
                modal_desc_label: "Description",
                modal_status_label: "Status",
                modal_cancel: "Cancel",
                modal_save: "Save"
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
                title: "Add-ons",
                add: "Add Add-on",
                add_coming_soon: "Add add-on functionality coming soon",
                no_plugins: "No plugins configured",
                name: "Name",
                version: "Version",
                status: "Status",
                actions: "Actions",
                tab_plugins: "Plugins",
                tab_mcp: "MCP",
                mcp_coming_soon: "MCP functionality coming soon",
                toggle_label: "Enable plugin",
                toggle_error: "Failed to update plugin state",
                configure: "Configure",
                uninstall: "Uninstall",
                config_modal_title: "Configure Plugin",
                config_modal_cancel: "Cancel",
                config_modal_save: "Save"
            },
            sticker: {
                title: "Stickers",
                add: "Add Sticker",
                add_coming_soon: "Add sticker functionality coming soon",
                no_stickers: "No stickers configured",
                name: "Name",
                category: "Category",
                status: "Status",
                actions: "Actions",
                edit: "Edit",
                delete: "Delete",
                modal_title_add: "Add Sticker",
                modal_title_edit: "Edit Sticker",
                modal_cancel: "Cancel",
                modal_save: "Save"
            },
            configuration: {
                title: "Configuration",
                save: "Save",
                loading: "Loading configuration...",
                saved: "Configuration saved successfully",
                save_failed: "Failed to save configuration",
                save_error: "Error saving configuration",
                reset: "Configuration reset to saved state",
                modified: "modified",
                changes: "change(s)",
                search_placeholder: "Search settings... ( / )",
                search_aria_label: "Search settings",
                undo_aria: "Undo (Ctrl+Z)",
                redo_aria: "Redo (Ctrl+Shift+Z)",
                reset_aria: "Reset",
                expand_all_aria: "Expand All",
                collapse_all_aria: "Collapse All",
                validation_failed: "Please fix validation errors before saving",
                shortcut_undo: "Undo",
                shortcut_redo: "Redo",
                shortcut_save: "Save",
                shortcut_search: "Search",
                groups: {
                    bot: "Bot Settings",
                    bot_desc: "Core bot behavior parameters",
                    agent: "Agent Settings",
                    agent_desc: "Agent and tool execution parameters",
                    selfie: "Appearance",
                    selfie_desc: "Bot appearance reference settings",
                    models: "Default Models",
                    models_desc: "Select default provider and model for each capability"
                },
                hints: {
                    max_memory_length: "Maximum number of messages retained in context window",
                    max_message_interval: "Maximum seconds to wait before processing buffered messages",
                    max_buffer_messages: "Maximum number of messages to buffer before processing",
                    min_message_delay: "Minimum delay in seconds before sending a reply",
                    max_message_delay: "Maximum delay in seconds before sending a reply",
                    max_tool_loop: "Maximum number of tool call iterations per response",
                    selfie_path: "Path to the bot appearance reference image"
                },
                validation: {
                    required: "This field is required",
                    invalid_number: "Please enter a valid number",
                    integer: "Please enter a whole number",
                    min: "Minimum value is",
                    max: "Maximum value is"
                },
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
                debug_mode: "Debug Mode",
                tab_message: "Message",
                tab_model: "Model",
                message: {
                    bot_section: "Bot Settings",
                    max_memory_length: "Max Memory Length",
                    max_message_interval: "Max Message Interval",
                    max_buffer_messages: "Max Buffer Messages",
                    min_message_delay: "Min Message Delay",
                    max_message_delay: "Max Message Delay",
                    agent_section: "Agent Settings",
                    max_tool_loop: "Max Tool Loop",
                    selfie_section: "Selfie",
                    selfie_path: "Selfie Path"
                },
                model: {
                    section_title: "Default Models",
                    section_desc: "Select provider and model for each default type.",
                    default_llm: "Default LLM",
                    default_llm_desc: "Main chat model.",
                    default_fast_llm: "Default Fast LLM",
                    default_fast_llm_desc: "Fast reply model.",
                    default_vlm: "Default VLM",
                    default_vlm_desc: "Vision-language model.",
                    default_tts: "Default TTS",
                    default_tts_desc: "Text to speech.",
                    default_stt: "Default STT",
                    default_stt_desc: "Speech to text.",
                    default_image: "Default Image",
                    default_image_desc: "Image generation.",
                    default_embedding: "Default Embedding",
                    default_embedding_desc: "Embedding model.",
                    default_rerank: "Default Rerank",
                    default_rerank_desc: "Rerank model.",
                    default_video: "Default Video",
                    default_video_desc: "Video generation."
                }
            },
            sessions: {
                title: "Sessions",
                new: "New Session",
                no_sessions: "No active sessions",
                name: "Session Name",
                description: "Session Description",
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
            },
            dropzone: {
                title: "Drag image here or click to select file",
                subtitle: "Common image formats such as JPG and PNG are supported",
                selected_prefix: "Selected file: ",
                selected: "File selected",
                selected_hint: "Click or drag to select another image"
            },
            model: {
                modal_title: "Add Model",
                modal_id_label: "Model ID",
                modal_id_placeholder: "Enter model ID...",
                modal_id_hint: "Use the model ID from your provider (e.g. text-embedding-3-small)",
                modal_id_tooltip: "The model identifier from your provider, e.g. text-embedding-3-small",
                modal_id_help_aria: "Model ID help",
                modal_cancel: "Cancel",
                modal_save: "Save",
                no_config_required: "No configuration required",
                validation_id_required: "Model ID is required",
                validation_id_too_long: "Model ID must be 128 characters or less",
                validation_id_format: "Model ID must start with a letter or number and contain only letters, numbers, hyphens, underscores, dots, colons, or slashes",
                validation_integer: "{field} must be an integer",
                validation_number: "{field} must be a valid number",
                validation_min: "{field} must be at least {min}",
                validation_positive: "{field} must be a positive number",
                validation_failed: "Please fix validation errors before saving"
            },
            config: {
                load_failed: "Configuration subsystem failed to load. Please refresh the page.",
                module_unavailable: "Configuration module unavailable",
                load_error: "Failed to load configuration",
                fallback_save_warning: "Configuration manager not loaded, falling back to legacy save",
                manager_not_loaded: "Configuration manager not loaded"
            }
        }
    },
    zh: {
        translation: {
            app: {
                title: "KiraAI",
                subtitle: "管理面板"
            },
            header: {
                logout: "退出登录",
                theme_toggle: "切换主题"
            },
            nav: {
                overview: "概览",
                provider: "提供商",
                adapter: "适配器",
                persona: "人设",
                plugin: "附加功能",
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
                    title: "提供商"
                },
                adapter: {
                    title: "适配器"
                },
                persona: {
                    title: "人设"
                },
                plugin: {
                    title: "附加功能"
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
                title: "提供商",
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
                actions: "操作",
                edit: "编辑",
                delete: "删除",
                platform_placeholder: "选择适配器平台...",
                modal_title: "适配器",
                modal_name_label: "适配器名称",
                modal_platform_label: "平台",
                modal_desc_label: "描述",
                modal_status_label: "状态",
                modal_cancel: "取消",
                modal_save: "保存"
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
                title: "附加功能",
                add: "添加附加功能",
                add_coming_soon: "添加附加功能功能即将推出",
                no_plugins: "未配置插件",
                name: "名称",
                version: "版本",
                status: "状态",
                actions: "操作",
                tab_plugins: "插件",
                tab_mcp: "MCP",
                mcp_coming_soon: "MCP 功能即将推出",
                toggle_label: "启用插件",
                toggle_error: "更新插件状态失败",
                configure: "配置",
                uninstall: "卸载",
                config_modal_title: "配置插件",
                config_modal_cancel: "取消",
                config_modal_save: "保存"
            },
            sticker: {
                title: "表情包",
                add: "添加表情包",
                add_coming_soon: "添加表情包功能即将推出",
                no_stickers: "未配置表情包",
                name: "名称",
                category: "分类",
                status: "状态",
                actions: "操作",
                edit: "编辑",
                delete: "删除",
                modal_title_add: "添加表情包",
                modal_title_edit: "编辑表情包",
                modal_cancel: "取消",
                modal_save: "保存"
            },
            configuration: {
                title: "配置项",
                save: "保存",
                loading: "加载配置中...",
                saved: "配置保存成功",
                save_failed: "保存配置失败",
                save_error: "保存配置出错",
                reset: "配置已重置为已保存状态",
                modified: "已修改",
                changes: "项修改",
                search_placeholder: "搜索设置... ( / )",
                search_aria_label: "搜索设置",
                undo_aria: "撤销 (Ctrl+Z)",
                redo_aria: "重做 (Ctrl+Shift+Z)",
                reset_aria: "重置",
                expand_all_aria: "展开全部",
                collapse_all_aria: "折叠全部",
                validation_failed: "请先修复验证错误后再保存",
                shortcut_undo: "撤销",
                shortcut_redo: "重做",
                shortcut_save: "保存",
                shortcut_search: "搜索",
                groups: {
                    bot: "机器人设置",
                    bot_desc: "核心机器人行为参数",
                    agent: "代理设置",
                    agent_desc: "代理和工具执行参数",
                    selfie: "外观",
                    selfie_desc: "机器人外观参考设置",
                    models: "默认模型",
                    models_desc: "为每种能力选择默认提供商和模型"
                },
                hints: {
                    max_memory_length: "上下文窗口中保留的最大消息数",
                    max_message_interval: "处理缓冲消息前的最大等待秒数",
                    max_buffer_messages: "处理前缓冲的最大消息数",
                    min_message_delay: "发送回复前的最小延迟秒数",
                    max_message_delay: "发送回复前的最大延迟秒数",
                    max_tool_loop: "每次响应的最大工具调用迭代次数",
                    selfie_path: "机器人外观参考图片路径"
                },
                validation: {
                    required: "此字段为必填项",
                    invalid_number: "请输入有效的数字",
                    integer: "请输入整数",
                    min: "最小值为",
                    max: "最大值为"
                },
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
                debug_mode: "调试模式",
                tab_message: "消息",
                tab_model: "模型",
                message: {
                    bot_section: "机器人设置",
                    max_memory_length: "最大记忆长度",
                    max_message_interval: "最大消息间隔",
                    max_buffer_messages: "最大缓冲消息数",
                    min_message_delay: "最小消息延迟",
                    max_message_delay: "最大消息延迟",
                    agent_section: "代理设置",
                    max_tool_loop: "最大工具循环次数",
                    selfie_section: "形象",
                    selfie_path: "形象参考图路径"
                },
                model: {
                    section_title: "默认模型",
                    section_desc: "为每种默认类型选择提供商和模型。",
                    default_llm: "默认大语言模型",
                    default_llm_desc: "主要聊天模型。",
                    default_fast_llm: "默认快速大语言模型",
                    default_fast_llm_desc: "用于快速回复的模型。",
                    default_vlm: "默认多模态模型",
                    default_vlm_desc: "视觉语言模型。",
                    default_tts: "默认语音合成",
                    default_tts_desc: "文本转语音模型。",
                    default_stt: "默认语音识别",
                    default_stt_desc: "语音转文本模型。",
                    default_image: "默认图片模型",
                    default_image_desc: "图片生成模型。",
                    default_embedding: "默认向量嵌入",
                    default_embedding_desc: "向量嵌入模型。",
                    default_rerank: "默认重排序模型",
                    default_rerank_desc: "用于重排序的模型。",
                    default_video: "默认视频模型",
                    default_video_desc: "视频生成模型。"
                }
            },
            sessions: {
                title: "会话管理",
                new: "新建会话",
                no_sessions: "无活跃会话",
                name: "会话名称",
                description: "会话描述",
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
            },
            dropzone: {
                title: "拖拽图片到此处，或点击选择文件",
                subtitle: "支持常见图片格式，如 JPG、PNG",
                selected_prefix: "已选择文件：",
                selected: "已选择文件",
                selected_hint: "点击或拖拽可重新选择图片"
            },
            model: {
                modal_title: "添加模型",
                modal_id_label: "模型 ID",
                modal_id_placeholder: "输入模型 ID...",
                modal_id_hint: "填写提供商提供的模型 ID（如 text-embedding-3-small）",
                modal_id_tooltip: "提供商提供的模型标识符，例如 text-embedding-3-small",
                modal_id_help_aria: "模型 ID 帮助",
                modal_cancel: "取消",
                modal_save: "保存",
                no_config_required: "无需额外配置",
                validation_id_required: "模型 ID 不能为空",
                validation_id_too_long: "模型 ID 最多 128 个字符",
                validation_id_format: "模型 ID 必须以字母或数字开头，仅可包含字母、数字、连字符、下划线、点、冒号或斜杠",
                validation_integer: "{field}必须为整数",
                validation_number: "{field}必须为有效数字",
                validation_min: "{field}最小值为{min}",
                validation_positive: "{field}必须为正数",
                validation_failed: "请先修正验证错误再保存"
            },
            config: {
                load_failed: "配置子系统加载失败，请刷新页面。",
                module_unavailable: "配置模块不可用",
                load_error: "加载配置失败",
                fallback_save_warning: "配置管理器未加载，已回退到旧版保存",
                manager_not_loaded: "配置管理器未加载"
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
        if (languageSelector) {
            languageSelector.addEventListener('change', (e) => {
                if (window.i18n && typeof window.i18n.changeLanguage === 'function') {
                    window.i18n.changeLanguage(e.target.value).catch((error) => {
                        console.error('Failed to change language:', error);
                    });
                } else {
                    i18next.changeLanguage(e.target.value).then(() => {
                        updateTranslations();
                    }).catch((error) => {
                        console.error('Failed to change language:', error);
                    });
                }
            });
        }
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

    document.querySelectorAll('[data-i18n-placeholder]').forEach(element => {
        const key = element.getAttribute('data-i18n-placeholder');
        const translation = i18next.t(key);
        if (translation && translation !== key) {
            element.placeholder = translation;
            // Only set aria-label if a dedicated i18n key is provided, or if it was previously empty
            const ariaKey = element.getAttribute('data-i18n-aria-label');
            if (ariaKey) {
                const ariaTranslation = i18next.t(ariaKey);
                if (ariaTranslation && ariaTranslation !== ariaKey) {
                    element.setAttribute('aria-label', ariaTranslation);
                    element.setAttribute('data-i18n-aria-generated', 'false');
                } else {
                    element.setAttribute('aria-label', translation);
                    element.setAttribute('data-i18n-aria-generated', 'true');
                }
            } else if (!element.getAttribute('aria-label') || element.getAttribute('data-i18n-aria-generated') === 'true') {
                element.setAttribute('aria-label', translation);
                element.setAttribute('data-i18n-aria-generated', 'true');
            }
        }
    });

    // Standalone aria-label translations for elements without data-i18n-placeholder
    document.querySelectorAll('[data-i18n-aria-label]:not([data-i18n-placeholder])').forEach(element => {
        const ariaKey = element.getAttribute('data-i18n-aria-label');
        const ariaTranslation = i18next.t(ariaKey);
        if (ariaTranslation && ariaTranslation !== ariaKey) {
            element.setAttribute('aria-label', ariaTranslation);
            element.setAttribute('title', ariaTranslation);
            element.setAttribute('data-i18n-aria-generated', 'false');
        } else {
            const fallbackLabel = element.placeholder || '';
            if (fallbackLabel) {
                element.setAttribute('aria-label', fallbackLabel);
                element.setAttribute('title', fallbackLabel);
                element.setAttribute('data-i18n-aria-generated', 'true');
            } else if (element.getAttribute('data-i18n-aria-generated') === 'true') {
                element.removeAttribute('aria-label');
                element.removeAttribute('title');
                element.removeAttribute('data-i18n-aria-generated');
            }
        }
    });
}

// Export for use in other scripts
window.i18n = {
    t: (key) => i18next.t(key),
    changeLanguage: (lng) => i18next.changeLanguage(lng).then(() => {
        try {
            updateTranslations();
            const page = document.getElementById('page-configuration');
            if (page && !page.classList.contains('hidden') && window.configManager && typeof window.configManager.render === 'function') {
                window.configManager.render();
            }
        } catch (error) {
            console.error('Failed to update translations after language change:', error);
        }
    })
};
