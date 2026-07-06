import os
import asyncio

from typing import Optional, Type

from core.logging_manager import get_logger
from core.plugin import BasePlugin, logger, on, Priority
from core.tag import BaseTag, TagSet
from core.chat import KiraMessageBatchEvent
from core.utils.common_utils import image_to_base64
from core.utils.path_utils import get_data_path
from core.chat.message_elements import BaseMessageElement, Sticker

message_logger = get_logger("message", "cyan")

STICKER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def build_sticker_tag(sticker_dict: dict) -> Type[BaseTag]:
    def load_sticker_prompt() -> str:
        """加载表情包（贴纸）提示词"""
        sticker_prompt = ""
        try:
            for sticker_id in sticker_dict:
                sticker_prompt += f"[{sticker_id}] {sticker_dict[sticker_id].get('desc')}\n"
            return sticker_prompt
        except Exception as e:
            message_logger.warning(f"Failed to load sticker prompt: {e}")
            return ""

    class StickerTag(BaseTag):
        name = "sticker"
        description = f"<sticker>sticker_id</sticker> # 发送一个sticker（中文一般叫做表情包）消息，通常单独在一条消息里，你需要在聊天中主动自然使用这些sticker，可以使用的sticker id和描述如下：{load_sticker_prompt()}"

        async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
            sticker_id = value
            try:
                sticker_path = sticker_dict[sticker_id].get("path")
                sticker_desc = sticker_dict[sticker_id].get("desc")
                sticker_bs64 = await image_to_base64(f"{get_data_path()}/sticker/{sticker_path}")
                sticker_obj = Sticker(sticker_id, sticker=sticker_bs64, caption=sticker_desc)
                return [sticker_obj]
            except Exception as e:
                message_logger.error(f"error while parsing sticker: {str(e)}")
                return []

    return StickerTag


class DefaultStickerPlugin(BasePlugin):
    """
    DefaultStickerPlugin
    """
    
    DEFAULT_RECOGNITION_PROMPT = "这是一张sticker（表情包），请描述这张表情包的内容和聊天中哪些情景使用此表情包，要求描述精确，不要太长，不要使用Markdown等标记符号，如果有文字请将其输出"

    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.scan_interval = 120
        self.recognition_model = None
        self.recognition_prompt = self.DEFAULT_RECOGNITION_PROMPT
        self.vlm_concurrency = 3
        self._vlm_sem: Optional[asyncio.Semaphore] = None
        self.sticker_mgr = self.ctx.sticker_manager
        self._scan_task: Optional[asyncio.Task] = None
    
    async def initialize(self):
        self.scan_interval = self.plugin_cfg.get("scan_interval", 120)
        self.recognition_model = self.plugin_cfg.get("recognition_model", None)
        self.recognition_prompt = self.plugin_cfg.get("recognition_prompt", "").strip() or self.DEFAULT_RECOGNITION_PROMPT
        self.vlm_concurrency = max(self.plugin_cfg.get("vlm_concurrency", 3), 1)
        self._vlm_sem = asyncio.Semaphore(self.vlm_concurrency)
        self.sticker_mgr.on_sticker_registered(self.on_sticker_registered)

        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info(f"Default Sticker initialized (vlm_concurrency={self.vlm_concurrency})")
    
    async def terminate(self):
        self.sticker_mgr.off_sticker_registered(self.on_sticker_registered)

        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None

    async def on_sticker_registered(self, sticker_id: str, sticker_info: dict):
        path = sticker_info.get("path")
        desc = sticker_info.get("desc")

        if desc:
            return
        async with self._vlm_sem:
            try:
                sticker_desc = await self.get_sticker_description(path)
                await self.sticker_mgr.update_sticker_desc(sticker_id, sticker_desc)
                logger.info(f"Sticker {sticker_id} description updated by VLM: {sticker_desc}")
            except Exception as e:
                logger.error(f"Failed to get description for sticker {sticker_id} by VLM: {e}")

    async def get_sticker_description(self, sticker_file):
        sticker_path = os.path.join(self.sticker_mgr.sticker_folder, sticker_file)

        from core.chat.message_elements import Image
        from core.utils.common_utils import desc_img

        if self.recognition_model:
            vlm_model = self.ctx.get_llm_client(model_uuid=self.recognition_model)
        else:
            try:
                vlm_model = self.ctx.provider_mgr.get_default_vlm()
            except Exception as e:
                logger.error(f"Failed to get default VLM model for sticker recognition: {e}")
                return ""
        sticker_desc = await desc_img(client=vlm_model, image=Image(image=sticker_path), prompt=self.recognition_prompt)

        return sticker_desc

    async def _scan_once(self):
        logger.info("Scanning unregistered stickers")
        sticker_files = [
            f for f in os.listdir(self.sticker_mgr.sticker_folder)
            if f.lower().endswith(STICKER_EXTENSIONS)
        ]
        pending = [
            f for f in sticker_files
            if f not in self.sticker_mgr.sticker_paths
        ]

        if pending:
            logger.info(f"Found {len(pending)} unregistered stickers, describing (vlm_concurrency={self.vlm_concurrency})...")

            async def _describe_one(file: str) -> tuple[str, str]:
                async with self._vlm_sem:
                    desc = await self.get_sticker_description(file)
                    return file, desc

            results = await asyncio.gather(
                *[_describe_one(f) for f in pending],
                return_exceptions=True,
            )

            for item in results:
                if isinstance(item, Exception):
                    logger.error(f"VLM description failed during scan: {item}")
                    continue
                file, desc = item
                if desc:
                    await self.sticker_mgr.register_sticker(file, desc)
                    logger.info(f"Registered sticker: {desc[:60]}")
        else:
            logger.info("All stickers are already registered")

    async def _scan_loop(self):
        try:
            while True:
                try:
                    await self._scan_once()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Scan iteration failed, will retry next interval: {e}")

                delay_minutes = self.scan_interval
                if delay_minutes < 10:
                    delay_minutes = 10

                await asyncio.sleep(delay_minutes * 60)
        except asyncio.CancelledError:
            logger.info("Scan loop cancelled")

    @on.llm_request(priority=Priority.SYS_HIGH - 1)
    async def inject_sticker_tag(self, event: KiraMessageBatchEvent, _, tag_set: TagSet):
        """Inject sticker tag"""
        message_types = event.message_types
        if "sticker" in message_types:
            sticker_dict = self.ctx.sticker_manager.sticker_dict
            tag_set.register(build_sticker_tag(sticker_dict=sticker_dict))
