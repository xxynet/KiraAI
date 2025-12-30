from core.utils.path_utils import get_config_path


VERSION = "v1.5.3"

# bot, adapters, providers, models, selfie
DEFAULT_CONFIG = {
    "bot": {
        "max_memory_length": 10,
        "max_message_interval": 2,
        "max_buffer_messages": 5,
        "min_message_delay": 2,
        "max_message_delay": 5
    }
}
