import pytest

from core.adapter.adapter_registry import AdapterManager


def test_adapter_name_rejects_colon():
    with pytest.raises(ValueError, match="must not contain"):
        AdapterManager._validate_adapter_name("my:adapter")


def test_adapter_name_allows_regular_name():
    AdapterManager._validate_adapter_name("my-adapter")
