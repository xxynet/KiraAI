from core.utils.path_utils import get_config_path


VERSION = "v1.6.0"

# bot, adapters, providers, models, selfie
DEFAULT_CONFIG = {
    "bot": {
        "max_memory_length": 10,
        "max_message_interval": 2,
        "max_buffer_messages": 5,
        "min_message_delay": 2,
        "max_message_delay": 5
    },
    "selfie": None,  # path in `data` folder
    "providers": {},  # ID: Provider config dict
    "models": {
        "default_llm": None,  # Model ID
        "default_tts": None,
        "default_stt": None,
        "default_image": None,
        "default_embedding": None,
        "default_rerank": None,
        "default_video": None
    },
    "adapters": {}  # ID: Adapter config dict
}
