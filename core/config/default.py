from core.utils.path_utils import get_config_path

VERSION = "v1.6.13"

DEFAULT_CONFIG = {
    "bot_config": {
        "bot": {
            "max_memory_length": "10",
            "max_message_interval": "2",
            "max_buffer_messages": "5",
            "min_message_delay": "2",
            "max_message_delay": "5"
        },
        "agent": {
            "max_tool_loop": "2"
        },
        "selfie": {
            "path": None
        }
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
    "adapters": {}  # ID: Adapter config dict
}
