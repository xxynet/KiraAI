import pytest

from core.config.config_loader import KiraConfig
from core.prompt_manager import PromptManager


class MockConfig(KiraConfig):
    """KiraConfig that skips file I/O for unit testing."""

    def __init__(self, data: dict):
        object.__setattr__(self, "default_config", data)
        self.update(data)

    def _load_config(self):
        pass


class MockPersonaManager:
    async def get_persona(self):
        return type("Persona", (), {"content": "Test persona"})()


CHAT_ENV = {
    "platform": "test",
    "adapter": "test_adapter",
    "chat_type": "dm",
    "self_id": "bot",
    "session_title": "Test",
    "session_description": "",
}


def make_config(lang):
    return MockConfig({
        "locale": {"lang": lang},
        "bot_config": {"agent": {"max_tool_loop": 3, "max_tool_calls_per_turn": 2}},
        "adapters": {},
    })


@pytest.mark.asyncio
@pytest.mark.parametrize(("lang", "expected"), [("en", "## Role"), ("zh", "## 角色设定")])
async def test_agent_prompt_uses_configured_language(lang, expected):
    manager = PromptManager(make_config(lang), MockPersonaManager())

    prompts = await manager.get_agent_prompt(CHAT_ENV)

    assert expected in prompts[0].to_string()
    assert "Test persona" in prompts[1].to_string()


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", [None, "de"])
async def test_agent_prompt_defaults_to_english_for_empty_or_unknown_language(lang):
    manager = PromptManager(make_config(lang), MockPersonaManager())

    prompts = await manager.get_agent_prompt(CHAT_ENV)

    assert "## Role" in prompts[0].to_string()
