from core.chat.message_utils import KiraIMMessage, MessageChain
from core.chat.message_elements import Image, Sticker, Reply, Forward
from core.logging_manager import get_logger
from core.utils.media_refs import store_session_media

logger = get_logger("message", "cyan")


class MessageMediaService:
    """Traverse incoming media and persist native multimodal content."""

    @staticmethod
    def iter_images(message_chain: MessageChain):
        """Yield every image-like element contained in a message chain."""
        for element in message_chain:
            if isinstance(element, (Image, Sticker)):
                yield element
            elif isinstance(element, Reply) and element.chain:
                yield from MessageMediaService.iter_images(element.chain)
            elif isinstance(element, Forward):
                for chain in element.chains:
                    yield from MessageMediaService.iter_images(chain)

    async def build_native_content(self, message: KiraIMMessage, session_id: str) -> list[dict]:
        """Persist incoming images and create the provider-independent content parts."""
        content: list[dict] = [{"type": "text", "text": message.message_str or ""}]
        for image in self.iter_images(message.chain):
            try:
                content.append(await store_session_media(image, session_id, message.message_id))
            except Exception as exc:
                logger.warning(f"Failed to persist image for native multimodal input: {exc}")
        return content
