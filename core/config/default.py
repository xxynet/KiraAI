VERSION = "v2.24.0"

DEFAULT_CONFIG = {
    "bot_config": {
        "bot": {
            "max_memory_length": 10,
            "max_message_interval": 2,
            "max_buffer_messages": 5,
            "min_message_delay": 2,
            "max_message_delay": 5
        },
        "agent": {
            "max_tool_loop": 5,
            "max_tool_calls_per_turn": 5,
            "tool_call_timeout": 60
        },
        "selfie": {
            "path": None
        },
        "cache": {
            "max_size_mb": 50,
            "max_files": 50,
            "max_age_hours": 24
        }
    },
    "locale": {
        "lang": None,
        "TZ": None
    },
    "providers": {},  # ID: Provider config dict
    "models": {
        "default_llm": None,  # Provider ID - Model ID
        "default_fast_llm": None,
        "default_vlm": None,
        "default_tts": None,
        "default_stt": None,
        "default_image": None,
        "default_embedding": None,
        "default_rerank": None,
        "default_video": None
    },
    "adapters": {},  # ID: Adapter config dict
    "network": {
        "pypi_mirror": None,
        "http_proxy": None
    },
    "telemetry": {
        "enabled": True,
        "client_uuid": None,
        "secret_key": None
    },
    "database": {
        "url": None,
        "echo": False
    },
    "logging": {
        "log_level": "INFO",
        "log_file_path": None,  # None = {data_path}/log.log
        "log_file_max_size": 10  # MB
    }
}
