import time

from core.adapter.capabilities import IMCapability
from core.adapter.message_format_metadata import MessageFormatMetadata
from core.chat.message_utils import KiraIMSentResult, KiraIMMessage, KiraMessageEvent, MessageChain
from core.chat.session import User


class WebChatIMCapability(IMCapability):
    _SUPPORTED_ELEMENTS = ["text", "image", "record", "video", "file", "sticker", "reply"]

    def receive_message(self, message_id: str, chain: MessageChain, profile: dict):
        """Publish a regular direct-message event; plugins own its reply strategy."""
        timestamp = int(time.time())
        self.publish(KiraMessageEvent(
            supported_elements=list(self._supported_elements), timestamp=timestamp,
            adapter=self.adapter.info,
            message=KiraIMMessage(
                message_id=message_id, self_id="webchat", timestamp=timestamp,
                sender=User("admin", profile["nickname"]), chain=chain,
                is_mentioned=True,
            ),
        ))

    async def get_message_metadata(self):
        return MessageFormatMetadata(self._supported_elements)

    async def send_direct_message(self, user_id, message):
        if str(user_id) != "admin":
            return KiraIMSentResult(ok=False, err="Unknown WebChat recipient")
        profile = await self.adapter.store.get_setting("profile")
        if profile is None:
            return KiraIMSentResult(ok=False, err="WebChat setup required")
        message_id = await self.adapter.store.append_reply(message, profile["peer_nickname"])
        return KiraIMSentResult(message_id=message_id)

    async def send_group_message(self, group_id, message):
        return KiraIMSentResult(ok=False, err="WebChat supports direct messages only")
