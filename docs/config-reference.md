# 配置参考（Configuration Reference）

KiraAI 的全部配置均为 **JSON** 格式，不存在 .ini 配置文件。
配置文件位于 `data/` 目录下（可用 `--data-dir` 覆盖 `data` 的位置）。

## data/config/system_config.json —— 核心配置

首次启动时若文件不存在，会自动创建（内容为默认值）。
由 `core/config/config_loader.py` 的 `KiraConfig` 加载；JSON 损坏时会抛出
`ConfigError`。保存格式：`json.dumps(indent=4, ensure_ascii=False)`。

顶层结构及各段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `bot_config` | object | 机器人行为参数 |
| `bot_config.bot` | object | `max_memory_length`、`max_message_interval`、`max_buffer_messages`、`min_message_delay`、`max_message_delay`、`dynamic_prompt_position` |
| `bot_config.agent` | object | `max_tool_loop`、`max_tool_calls_per_turn`、`tool_call_timeout` |
| `bot_config.selfie` | object | `path`（自拍/头像路径） |
| `bot_config.cache` | object | `max_size_mb`、`max_files`、`max_age_hours` |
| `bot_config.capabilities` | object | `image_recognition` / `tts` / `stt` / `image_generation` / `video_generation` / `forward_parsing` 各含 `enabled` |
| `locale` | object | `lang`、`TZ`（IANA 时区，如 `Asia/Shanghai`） |
| `onboarding` | object | `completed`、`version` |
| `providers` | object | 按 ID 存储的提供商配置字典（WebUI 中维护） |
| `models` | object | 默认模型选择器：`default_llm`、`default_fast_llm`、`default_vlm`、`default_tts`、`default_stt`、`default_image`、`default_embedding`、`default_rerank`、`default_video`（格式 `ProviderID - ModelID`） |
| `adapters` | object | 按 ID 存储的适配器配置字典（WebUI 中维护） |
| `network` | object | `pypi_mirror`、`http_proxy` |
| `telemetry` | object | `enabled`、`client_uuid`、`secret_key` |
| `database` | object | `url`（默认 None=SQLite）、`echo` |
| `logging` | object | `log_level`、`log_file_path`（None=`{data}/log.log`）、`log_file_max_size`（MB） |

完整默认值见 `core/config/default.py` 的 `DEFAULT_CONFIG`。

## data/webui.json —— WebUI 运行时配置

由 `core/launcher.py::_load_webui_config` 读取，不存在时自动创建：

```json
{
  "host": "0.0.0.0",
  "port": 5267
}
```

`main.py::_get_port` 同样读取该文件的 `port` 决定 WebUI 端口（默认 5267）。

## persona —— 遗留格式说明

旧版 `persona.txt` 为**遗留格式**：启动时若数据库 persona 表为空且文件存在，
内容会被迁移进数据库作为默认人设（见 `core/db/migrate_to_db.py`），迁移后不再
使用。新人设由 `PersonaManager` 管理，存于数据库，支持 text / markdown / json /
yaml 多种格式。
