from dataclasses import dataclass, field


@dataclass
class AdapterInfo:
    """Dataclass of adapter info"""

    """Marks if the adapter is enabled"""
    enabled: bool

    """ID of the adapter"""
    adapter_id: str

    """Name of the adapter defined by user"""
    name: str

    """Platform of the adapter, e.g. Telegram"""
    platform: str

    """Description of the adapter"""
    description: str = ""

    """Adapter config dict"""
    config: dict = field(default_factory=dict)
