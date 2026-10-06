from core.adapter import FeedCapability
from core.agent.message import OpenAIMessage
from core.chat import KiraCommentEvent, MessageChain
from core.chat.message_elements import Text
from core.logging_manager import get_logger
from core.plugin import BasePlugin, Priority, on
from core.provider import LLMRequest

from .prompts import build_comment_prompt


logger = get_logger("message", "cyan")
llm_logger = get_logger("llm", "purple")


class DefaultCommentPlugin(BasePlugin):
    async def initialize(self):
        pass

    async def terminate(self):
        pass

    @on.comment(priority=Priority.SYS_LOW)
    async def handle_comment(self, msg: KiraCommentEvent):
        """Provide the default reply only when no earlier plugin owns the event."""
        if msg.is_stopped:
            return
        msg.stop()

        logger.info(f"[{msg.adapter_name} | {msg.comment_id}] Processing comment")
        comment_text = "".join(element.repr for element in msg.comment_content)
        if msg.root_comment_content is not None:
            root_text = "".join(element.repr for element in msg.root_comment_content)
            comment_content = f"You: {root_text}\n{msg.commenter_nickname}: {comment_text}"
        else:
            comment_content = f"{msg.commenter_nickname}: {comment_text}"

        comment_prompt = await self._build_comment_prompt(comment_content)

        try:
            client = self.ctx.provider_mgr.get_default_llm()
        except ValueError as exc:
            llm_logger.error(f"Failed to get default LLM client: {exc}")
            return
        if not client:
            llm_logger.error(f"Default LLM model not configured, please configure it in Configuration")
            return

        llm_req = LLMRequest(messages=[OpenAIMessage(role="user", content=comment_prompt)])

        llm_resp = await client.chat(llm_req)

        response = llm_resp.text_response.strip()

        if response:
            adapter = self.ctx.adapter_mgr.get_adapter(msg.adapter_name)
            await adapter.get_capability(FeedCapability).send_comment(
                message=MessageChain([Text(response)]), target=msg.target,
                root=msg.root_comment_id, parent=msg.comment_id,
            )
        else:
            logger.warning("Blank LLM response")

    async def _build_comment_prompt(self, comment_content):
        persona = await self.ctx.persona_mgr.get_persona()

        return build_comment_prompt(
            persona=persona.content, comment_content=comment_content, lang=self.ctx.get_lang(),
        )
