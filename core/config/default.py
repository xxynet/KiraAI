VERSION = "v2.33.1"

DEFAULT_CONFIG = {
    "bot_config": {
        "bot": {
            "max_memory_length": 10,
            "max_message_interval": 2,
            "max_buffer_messages": 5,
            "min_message_delay": 2,
            "max_message_delay": 5,
            "dynamic_prompt_position": "latest_user",
            "memory_prompt_position": "latest_user"
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
        },
        "image_compression": {
            "enabled": False,
            "max_size": 1280,
            "quality": 95,
            "min_file_size_mb": 1
        },
        "capabilities": {
            "image_recognition": {
                "enabled": True,
                "mode": "vlm_description",
                "desc_prompt": ""
            },
            "tts": {
                "enabled": True
            },
            "stt": {
                "enabled": True
            },
            "image_generation": {
                "enabled": True
            },
            "video_generation": {
                "enabled": False
            },
            "forward_parsing": {
                "enabled": True
            }
        }
    },
    "locale": {
        "lang": None,
        "TZ": None
    },
    "onboarding": {
        "completed": False,
        "version": 1,
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
