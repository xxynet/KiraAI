from typing import Any, Union


class Statistics:
    _initialized = False

    _statistics: dict[str, Any] = {}

    @classmethod
    def init_instance(cls):
        if not cls._initialized:
            cls._initialized = True
            return True
        return False

    def __init__(self):
        if self.init_instance():
            self._statistics["statistics"] = True
        else:
            # instance already exists
            pass

    def get_stats(self, key: str):
        return self._statistics[key]

    def set_stats(self, key: str, content: Any):
        self._statistics[key] = content

    def to_dict(self):
        return self._statistics

    def __str__(self):
        return str(self._statistics)
