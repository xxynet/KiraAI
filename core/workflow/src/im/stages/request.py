from core.workflow.base_stage import BaseStage
from core.prompt_manager import Prompt
from core.provider import LLMModelClient, LLMRequest
from core.tag import TagSet
from core.logging_manager import get_logger
from ..context import IMBatchContext

llm_logger = get_logger("llm", "purple")


class BuildRequestStage(BaseStage[IMBatchContext]):
    """Select models and scoped tools, and build the initial prompt."""

    async def run(self, ctx: IMBatchContext) -> bool:
        services, event, sid = ctx.services, ctx.event, ctx.sid
        # Set session title
        if not services.session_manager.get_session_info(sid).session_title:
            services.session_manager.update_session_info(sid, event.session.session_title)
        session_title = services.session_manager.get_session_info(sid).session_title

        # Build chat environment
        chat_env = {
            "platform": event.adapter.platform,
            "adapter": event.adapter.name,
            "chat_type": 'GroupMessage' if event.is_group_message() else 'DirectMessage',
            "self_id": event.self_id,
            "session_title": session_title,
            "session_description": event.session.session_description
        }

        # Get chat history memory
        session_memory = services.session_manager.fetch_memory(sid)

        # Generate agent prompt
        agent_prompt_list = await services.prompt_manager.get_agent_prompt(chat_env)

        # Inject skills prompt (filtered by scope)
        allowed_skills = []
        for s in services.skills_manager.skills_info:
            if not s.enabled:
                continue
            if services.skills_manager.is_skill_allowed(s.name, sid):
                allowed_skills.append(s)
        if allowed_skills:
            for i, p in enumerate(agent_prompt_list):
                if p.name == "tools":
                    agent_prompt_list.insert(i+1, services.skills_manager.build_skills_prompt(allowed_skills))
                    break

        model_group: list[LLMModelClient] = []
        if event.model_group:
            model_group = [m for m in event.model_group if isinstance(m, LLMModelClient)]
        if not model_group:
            # Get default LLM model client
            try:
                default_llm = services.provider_mgr.get_default_llm()
                if not default_llm:
                    llm_logger.error(f"Default LLM model not configured, please configure it in Configuration")
                    return False
                model_group = [default_llm]
            except Exception as _:
                llm_logger.error(f"Default LLM model not configured, please configure it in Configuration")
                return False

        # Filter tools by scope
        tool_server_map = services.mcp_manager.get_tool_server_map()

        tool_set = services.tool_manager.build_tool_set()
        # Remove tools blocked by MCP server scope
        tool_set.tools = [
            t for t in tool_set.tools
            if not (tool_server_map.get(t.name)
                    and not services.mcp_manager.is_server_allowed(tool_server_map[t.name], sid))
        ]

        request = LLMRequest(messages=session_memory[:], tool_set=tool_set)
        request.system_prompt.extend(agent_prompt_list)

        # Add received im messages
        for message in event.messages:
            request.user_prompt.append(Prompt(
                message.message_str,
                name="message",
                source="system",
                render_template=False,
            ))

        # Build tag set
        tag_set = TagSet()
        ctx.request = request
        ctx.tag_set = tag_set
        ctx.model_group = model_group
        return True
