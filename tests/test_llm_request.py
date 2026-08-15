from core.prompt_manager import Prompt
from core.prompts.agent_tmpl import get_agent_templates
from core.provider.llm_model import LLMRequest
from jinja2 import UndefinedError

DYNAMIC_BLOCKS = ("SESSIONS", "CHATENV", "TIME")
MEMORY_BLOCK = "MEMORY"
STATIC_BLOCKS = ("ROLE", "TOOLS")


def test_prompt_renders_jinja2_placeholders():
    prompt = Prompt(
        "Hello {{ message }}",
        render_template=True,
        message="Kira",
    )

    assert prompt.to_string() == "Hello Kira\n"


def test_prompt_preserves_literal_braces():
    prompt = Prompt('{"message": "example"}')

    assert prompt.to_string() == '{"message": "example"}\n'


def test_prompt_rejects_undefined_jinja2_variables():
    prompt = Prompt("Hello {{ message }}", render_template=True)

    try:
        prompt.to_string()
    except UndefinedError:
        pass
    else:
        raise AssertionError("Undefined Jinja2 variables must fail rendering")


def test_format_templates_render_dynamic_tag_placeholders():
    for lang in ("zh", "en"):
        prompt = Prompt(
            get_agent_templates(lang)["format"],
            render_template=True,
            message_types="<text>TEXT</text>",
            root_tags="<control>CONTROL</control>",
        )

        rendered = prompt.to_string()
        assert "<text>TEXT</text>" in rendered
        assert "<control>CONTROL</control>" in rendered
        assert "{{ message_types }}" not in rendered
        assert "{{ root_tags }}" not in rendered


def test_non_template_prompt_never_renders_user_content():
    prompt = Prompt("User text: {{ 7 * 7 }}")

    assert prompt.to_string() == "User text: {{ 7 * 7 }}\n"


def test_external_plugin_can_opt_in_to_template_rendering():
    prompt = Prompt(
        "{{ time }} | {{ message }}",
        render_template=True,
        time="12:00",
        message="Hello",
    )

    assert prompt.to_string() == "12:00 | Hello\n"


def make_request():
    return LLMRequest(
        messages=[{"role": "user", "content": "history"}],
        system_prompt=[
            Prompt("ROLE", name="role", source="system"),
            Prompt("SESSIONS", name="sessions", source="system"),
            Prompt("CHATENV", name="chat_env", source="system"),
            Prompt("MEMORY", name="memory", source="system"),
            Prompt("TOOLS", name="tools", source="system"),
            Prompt("TIME", name="time", source="system"),
        ],
        user_prompt=[Prompt("hello", name="message", source="system")],
    )


def test_dynamic_blocks_are_relocated_by_default():
    req = make_request()
    req.assemble_prompt()

    assert req.messages[0].role == "system"
    assert "SESSIONS" not in req.messages[0].content
    assert "SESSIONS" in req.messages[-1].content


def test_system_position_keeps_dynamic_blocks_inline():
    req = make_request()
    req.assemble_prompt("system")

    system_content = req.messages[0].content
    for block in (*STATIC_BLOCKS, MEMORY_BLOCK, *DYNAMIC_BLOCKS):
        assert block in system_content
    assert req.messages[-1].content.strip() == "hello"


def test_unknown_position_falls_back_to_system():
    req = make_request()
    req.assemble_prompt("nonsense")

    assert "SESSIONS" in req.messages[0].content
    assert "SESSIONS" not in req.messages[-1].content


def test_latest_user_moves_dynamic_blocks_out_of_system_prompt():
    req = make_request()
    req.assemble_prompt("latest_user")

    system_content = req.messages[0].content
    for block in (*STATIC_BLOCKS, MEMORY_BLOCK):
        assert block in system_content
    for block in DYNAMIC_BLOCKS:
        assert block not in system_content

    user_content = req.messages[-1].content
    assert req.messages[-1].role == "user"
    for block in DYNAMIC_BLOCKS:
        assert block in user_content
    for block in (*STATIC_BLOCKS, MEMORY_BLOCK):
        assert block not in user_content
    # Environment context precedes the actual user message.
    assert user_content.index("SESSIONS") < user_content.index("hello")


def test_relocated_blocks_are_wrapped_in_system_reminder():
    req = make_request()
    req.assemble_prompt("latest_user")

    user_content = req.messages[-1].content
    start = user_content.index("<system_reminder>")
    end = user_content.index("</system_reminder>")
    for block in DYNAMIC_BLOCKS:
        assert start < user_content.index(block) < end
    # The user's own message stays outside the wrapper.
    assert end < user_content.index("hello")


def test_latest_user_moves_memory_when_configured():
    req = make_request()
    req.assemble_prompt("system", "latest_user")

    assert MEMORY_BLOCK not in req.messages[0].content
    assert MEMORY_BLOCK in req.messages[-1].content
    assert req.messages[-1].content.index(MEMORY_BLOCK) < req.messages[-1].content.index("hello")


def test_memory_position_is_independent_from_dynamic_position():
    req = make_request()
    req.assemble_prompt("latest_user", "system")

    assert MEMORY_BLOCK in req.messages[0].content
    assert MEMORY_BLOCK not in req.messages[-1].content


def test_relocated_blocks_are_not_persisted():
    req = make_request()
    req.assemble_prompt("latest_user")

    persisted = "".join(p.to_string() for p in req.user_prompt if p.persist)
    assert persisted.strip() == "hello"

    relocated = {p.name for p in req.user_prompt if not p.persist}
    assert relocated == {
        "dynamic_context_start", "sessions", "chat_env", "time", "dynamic_context_end",
    }


def test_no_wrapper_when_nothing_to_relocate():
    req = LLMRequest(
        system_prompt=[Prompt("ROLE", name="role", source="system")],
        user_prompt=[Prompt("hello", name="message", source="system")],
    )
    req.assemble_prompt("latest_user")

    assert "system_reminder" not in req.messages[-1].content
    assert req.messages[-1].content.strip() == "hello"
