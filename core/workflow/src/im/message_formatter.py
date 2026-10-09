from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from core.chat.message_utils import MessageChain
from core.chat.message_elements import (
    Text, Image, At, Reply, Forward, Emoji, Sticker, Record, Notice, Json, File, Video,
)
from core.logging_manager import get_logger
from core.utils.common_utils import desc_img, speech_to_text
from core.utils.path_utils import get_data_path

if TYPE_CHECKING:
    from core.image_desc_cache import ImageDescCache
    from core.chat.session_manager import SessionManager
    from core.config import KiraConfig
    from core.provider import ProviderManager

logger = get_logger("message", "cyan")


class MessageFormatter:
    """Convert message chains to model input using explicitly supplied services."""

    def __init__(
        self,
        config: KiraConfig,
        provider_mgr: ProviderManager | None = None,
        session_manager: SessionManager | None = None,
        image_desc_cache: ImageDescCache | None = None,
    ):
        self.kira_config = config
        self.provider_mgr = provider_mgr
        self.session_manager = session_manager
        self.image_desc_cache = image_desc_cache

    async def format_to_text(self, message_chain: MessageChain, session_id: Optional[str] = None, capabilities: Optional[dict] = None):
        """将平台使用标准消息格式封装的消息转换为LLM可以接收的字符串"""
        message_str = ""
        if capabilities is None:
            global_capabilities = self.kira_config.get_config("bot_config.capabilities", {})
            if not isinstance(global_capabilities, dict):
                global_capabilities = {}
            capabilities = self.session_manager.get_effective_capabilities(
                session_id, global_capabilities
            ) if session_id and self.session_manager is not None else global_capabilities
        if not isinstance(capabilities, dict):
            capabilities = {}
        image_recognition = capabilities.get("image_recognition", {})
        if not isinstance(image_recognition, dict) or not image_recognition:
            image_recognition = {
                "mode": self.kira_config.get_config("bot_config.capabilities.image_recognition.mode", "vlm_description")
            }
        for ele in message_chain:
            if isinstance(ele, Text):
                message_str += ele.text
            elif isinstance(ele, Emoji):
                if ele.emoji_desc:
                    message_str += f"[Emoji {ele.emoji_desc} (ID: {ele.emoji_id})]"
                else:
                    message_str += f"[Emoji {ele.emoji_id}]"
            elif isinstance(ele, At):
                if ele.nickname:
                    message_str += f"[At {ele.pid}(nickname: {ele.nickname})]"
                else:
                    message_str += f"[At {ele.pid}]"
            elif isinstance(ele, Image):
                image_mode = image_recognition.get("mode", "vlm_description")
                if image_mode == "native":
                    ele.caption = "attached image"
                    message_str += "[Image attached]"
                    continue
                if ele.caption is None:
                    try:
                        md5 = await ele.hash_image()
                        cached_desc = await self.image_desc_cache.get(md5)
                    except (ValueError, Exception) as e:
                        logger.warning(f"Failed to hash image: {e}")
                        md5 = None
                        cached_desc = None
                    if cached_desc:
                        img_desc = cached_desc
                    else:
                        try:
                            vlm_model = self.provider_mgr.get_default_vlm()

                            # Check if image recognition is enabled
                            caps = image_recognition
                            if caps.get("enabled", True):
                                img_prompt = caps.get("desc_prompt", "").strip() or None
                                img_desc = await desc_img(
                                    client=vlm_model,
                                    image=ele,
                                    prompt=img_prompt,
                                    lang=self.kira_config.get_config("locale.lang") or "en",
                                )
                            else:
                                img_desc = ""
                        except Exception as e:
                            logger.error(f"Failed to get default VLM model for image description: {e}")
                            img_desc = ""

                        if md5 and img_desc:
                            try:
                                await self.image_desc_cache.set(md5, img_desc)
                            except Exception as e:
                                logger.warning(f"Failed to cache image desc: {e}")
                    ele.caption = img_desc
                else:
                    try:
                        md5 = await ele.hash_image()
                        cached = await self.image_desc_cache.get(md5)
                        if not cached:
                            await self.image_desc_cache.set(md5, ele.caption)
                    except Exception as e:
                        logger.warning(f"Failed to cache image desc: {e}")
                try:
                    path = Path(await ele.to_path())
                    data_dir = get_data_path()
                    try:
                        rel = path.relative_to(data_dir)
                        path_result = f"data/{rel}"
                    except ValueError:
                        path_result = str(path)
                    message_str += f"[Image {str(ele.caption)}, file_path: {path_result}]"
                except Exception as e:
                    logger.warning(f"Failed to save image: {e}")
                    message_str += f"[Image {str(ele.caption)}]"
            elif isinstance(ele, Sticker):
                image_mode = image_recognition.get("mode", "vlm_description")
                if image_mode == "native":
                    ele.caption = "attached sticker"
                    message_str += "[Sticker attached]"
                    continue
                if ele.caption is None:
                    try:
                        md5 = await ele.hash_image()
                        cached_desc = await self.image_desc_cache.get(md5)
                    except (ValueError, Exception) as e:
                        logger.warning(f"Failed to hash sticker: {e}")
                        md5 = None
                        cached_desc = None
                    if cached_desc:
                        sticker_desc = cached_desc
                    else:
                        try:
                            vlm_model = self.provider_mgr.get_default_vlm()

                            # Check if image recognition is enabled
                            caps = image_recognition
                            if caps.get("enabled", True):
                                sticker_prompt = caps.get("desc_prompt", "").strip() or None
                                sticker_desc = await desc_img(
                                    client=vlm_model,
                                    image=ele,
                                    prompt=sticker_prompt,
                                    lang=self.kira_config.get_config("locale.lang") or "en",
                                )
                            else:
                                sticker_desc = ""
                        except Exception as e:
                            logger.error(f"Failed to get default VLM model for sticker description: {e}")
                            sticker_desc = ""

                        if md5 and sticker_desc:
                            try:
                                await self.image_desc_cache.set(md5, sticker_desc)
                            except Exception as e:
                                logger.warning(f"Failed to cache sticker desc: {e}")
                    ele.caption = sticker_desc
                else:
                    try:
                        md5 = await ele.hash_image()
                        cached = await self.image_desc_cache.get(md5)
                        if not cached:
                            await self.image_desc_cache.set(md5, ele.caption)
                    except Exception as e:
                        logger.warning(f"Failed to cache sticker desc: {e}")
                message_str += f"[Sticker {str(ele.caption)}]"
            elif isinstance(ele, Reply):
                if ele.chain:
                    ele.chain.message_list = [x for x in ele.chain if not isinstance(x, Reply)]
                    reply_content = await self.format_to_text(ele.chain, session_id, capabilities)
                    message_str += f"[Reply ID: {ele.message_id} content: {reply_content}]"
                elif ele.message_content:
                    message_str += f"[Reply ID: {ele.message_id} content: {ele.message_content}]"
                else:
                    message_str += f"[Reply ID: {ele.message_id}]"
            elif isinstance(ele, Forward):
                caps = capabilities.get("forward_parsing", {})
                if not caps.get("enabled", True):
                    message_str += "[Forward message]"
                elif ele.chains:
                    forward_contents = ""
                    for i, chain in enumerate(ele.chains):
                        ele.chains[i].message_list = [x for x in chain if not isinstance(x, Forward)]
                        forward_content = await self.format_to_text(ele.chains[i], session_id, capabilities)
                        forward_contents += f"\n{forward_content}\n"
                    message_str += f"[Forward {forward_contents.strip()}]"
            elif isinstance(ele, Record):
                try:
                    caps = capabilities.get("stt", {})
                    if caps.get("enabled", True):
                        stt_client = self.provider_mgr.get_default_stt()
                        if not stt_client:
                            logger.error("Failed to get STT client, please set default STT model in Configuration")
                            record_text = "[Speech recognition unavailable]"
                        else:
                            record_text = await speech_to_text(client=stt_client, record=ele)
                    else:
                        record_text = "[Speech recognition disabled]"
                except Exception as e:
                    logger.error(f"Failed to get STT model for speech recognition: {e}")
                    record_text = "[Speech recognition unavailable]"
                ele.transcript = record_text
                message_str += f"[Record {record_text}]"
            elif isinstance(ele, Notice):
                message_str += f"{ele.text}"
            elif isinstance(ele, Json):
                try:
                    card_str = json.dumps(ele.data, ensure_ascii=False)
                except (TypeError, ValueError):
                    card_str = json.dumps(str(ele.data), ensure_ascii=False)
                message_str += f"[Json card {card_str}]"
            elif isinstance(ele, File):
                try:
                    file_size = int(ele.size)
                except Exception as _:
                    file_size = None

                # TODO Make it customizable
                if not file_size or file_size > 10 * 1024 * 1024:
                    message_str += f"[File name: {ele.name} (File size over 10MB, not cached)]"
                    continue

                try:
                    path = Path(await ele.to_path())
                    data_dir = get_data_path()

                    try:
                        rel = path.relative_to(data_dir)
                        path_result = f"data/{rel}"
                    except ValueError:
                        path_result = str(path)

                    message_str += f"[File name: {ele.name}, file_path: {path_result}]"
                except Exception as e:
                    logger.error(f"Failed to save temp file: {e}")
            elif isinstance(ele, Video):
                try:
                    video_file_size = int(ele.size)
                except Exception as _:
                    video_file_size = None

                # TODO Make it customizable
                if not video_file_size or video_file_size > 10 * 1024 * 1024:
                    message_str += f"[Video name: {ele.name} (Video size over 10MB, not cached)]"
                    continue

                try:
                    path = Path(await ele.to_path())
                    data_dir = get_data_path()

                    try:
                        rel = path.relative_to(data_dir)
                        path_result = f"data/{rel}"
                    except ValueError:
                        path_result = str(path)

                    message_str += f"[Video name: {ele.name}, file_path: {path_result}]"
                except Exception as e:
                    logger.error(f"Failed to save temp video file: {e}")
            else:
                pass
        return message_str
