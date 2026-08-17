import asyncio

import pytest

from core.adapter.adapter_info import AdapterInfo
from core.adapter.adapter_utils import IMAdapter


class DummyAdapter(IMAdapter):
    async def start(self):
        pass

    async def stop(self):
        pass

    def get_client(self):
        return None

    async def send_group_message(self, group_id, send_message_obj):
        return None

    async def send_direct_message(self, user_id, send_message_obj):
        return None


def build_adapter(config: dict) -> DummyAdapter:
    info = AdapterInfo(
        enabled=True,
        adapter_id="dummy-id",
        name="dummy",
        platform="Dummy",
        config=config,
    )
    return DummyAdapter(info, asyncio.Queue())


@pytest.mark.parametrize(
    "raw, expected",
    [
        ([123456, 789], ["123456", "789"]),
        (["123456", 789], ["123456", "789"]),
        ([" 123456 "], ["123456"]),
        ([123456, None, ""], ["123456"]),
        ([], []),
        ("", []),
        (None, []),
    ],
)
def test_normalize_id_list(raw, expected):
    assert IMAdapter._normalize_id_list(raw) == expected


def test_allow_list_matches_integer_config_entries():
    adapter = build_adapter({
        "permission_mode": "allow_list",
        "group_allow_list": [123456],
        "user_allow_list": [7890],
    })
    assert "123456" in adapter.group_list
    assert "7890" in adapter.user_list


def test_deny_list_matches_integer_config_entries():
    adapter = build_adapter({
        "permission_mode": "deny_list",
        "group_deny_list": [123456],
        "user_deny_list": [7890],
    })
    assert "123456" in adapter.group_list
    assert "7890" in adapter.user_list


def test_unknown_permission_mode_falls_back_to_allow_list():
    adapter = build_adapter({"permission_mode": "whatever"})
    assert adapter.permission_mode == "allow_list"
    assert adapter.group_list == []
    assert adapter.user_list == []
