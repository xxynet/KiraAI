import os
from pathlib import Path
from typing import Type

from core.tag import BaseTag
from core.chat.message_elements import (
    BaseMessageElement,
    Text,
    Image,
    At,
    Reply,
    Forward,
    Emoji,
    Sticker,
    Record,
    Notice,
    Poke,
    File,
    Video
)

from core.utils.path_utils import get_data_path
from core.utils.common_utils import image_to_base64
from core.logging_manager import get_logger

logger = get_logger("message", "cyan")
provider_logger = get_logger("provider", "purple")


class TextTag(BaseTag):
    name = "text"
    description = "<text>some text</text> # 纯文本消息"

    async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
        if value:
            return [Text(value)]
        return []


def build_emoji_tag(emoji_json: dict) -> Type[BaseTag]:
    class EmojiTag(BaseTag):
        name = "emoji"
        description = f"<emoji>emoji_id</emoji> # 发送一个emoji（中文一般叫做表情）消息，通常和文字在同一个msg标签中，可以使用的emoji如下：{emoji_json}"

        async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
            return [Emoji(value)]
    return EmojiTag


def build_sticker_tag(sticker_dict: dict) -> Type[BaseTag]:
    def load_sticker_prompt() -> str:
        """加载表情包（贴纸）提示词"""
        sticker_prompt = ""
        try:
            for sticker_id in sticker_dict:
                sticker_prompt += f"[{sticker_id}] {sticker_dict[sticker_id].get('desc')}\n"
            return sticker_prompt
        except Exception as e:
            logger.warning(f"Failed to load sticker prompt: {e}")
            return ""

    class StickerTag(BaseTag):
        name = "sticker"
        description = f"<sticker>sticker_id</sticker> # 发送一个sticker（中文一般叫做表情包）消息，通常单独在一条消息里，你需要在聊天中主动自然使用这些sticker，可以使用的sticker id和描述如下：{load_sticker_prompt()}"

        async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
            sticker_id = value
            try:
                sticker_path = sticker_dict[sticker_id].get("path")
                sticker_bs64 = await image_to_base64(f"{get_data_path()}/sticker/{sticker_path}")
                return [Sticker(sticker_id, sticker=sticker_bs64)]
            except Exception as e:
                logger.error(f"error while parsing sticker: {str(e)}")

    return StickerTag


class AtTag(BaseTag):
    name = "at"
    description = "<at>user_id</at> # 通过用户id使用@功能，通常出现在消息的开头，有时也会在消息中间（如果聊天中需要提及其他人），特殊的，传入字符串all代表@全体成员。at功能仅在群聊中使用，系统会将at消息解析为‘@用户昵称’显示"

    async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
        return [At(value)]


class ImgTag(BaseTag):
    name = "img"
    description = "<img>prompt for image generator</img> # 用于发送图片。请勿滥用，仅在用户请求看照片时使用，需要详细的绘画提示词。"

    def __init__(self, ctx):
        super().__init__(ctx=ctx)

    async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
        img_res = await self.ctx.llm_api.generate_img(value)
        if img_res:
            return [img_res]
        return []


class VideoTag(BaseTag):
    name = "video"
    description = "<video>prompt for video generator</video> # Generate a video with detailed video generation prompt"

    def __init__(self, ctx):
        super().__init__(ctx=ctx)

    async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
        duration = kwargs.get("duration", "5")

        video_client = self.ctx.provider_mgr.get_default_video()
        if not video_client:
            provider_logger.error(f"Failed to get video client, please set default video model in Configuration")
            return []

        provider_name = video_client.model.provider_name
        model_id = video_client.model.model_id
        provider_logger.info(f"Generating video using {model_id} ({provider_name})")

        video_obj = await video_client.generate_video(prompt=value)
        if video_obj:
            provider_logger.info(f"Generated video from text {value}")
            return [video_obj]
        return []


class ReplyTag(BaseTag):
    name = "reply"
    description = "<reply>message_id</reply> # 回复一条消息，如果使用这个标签，需要为一条消息的第一个元素，且不能单独出现"

    async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
        return [Reply(value)]


class RecordTag(BaseTag):
    name = "record"
    description = "<record>record_text</record> # 用于发送语音，record_text为要发送的语音文本，不能和其他msg内标签混用，用户给你发语音或者用户要求你发语音时使用（收到语音消息类似这样：[Record voice_message]）"

    def __init__(self, ctx):
        super().__init__(ctx=ctx)

    async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
        try:
            record_obj = await self.ctx.llm_api.text_to_speech(value)
            return [record_obj]
        except Exception as e:
            logger.error(f"an error occurred while generating voice message: {e}")
            return [Text(f"<record>{value}</record>")]


class PokeTag(BaseTag):
    name = "poke"
    description = "<poke>user_id</poke> # 发送戳一戳消息（一个社交平台的小功能用于引起用户注意），只能单独一条消息，不能和其他元素出现在一条消息中。可以在别人对你戳一戳（捏一捏）时使用，也可以在日常交流中自然使用"

    async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
        return [Poke(value)]


class SelfieTag(BaseTag):
    name = "selfie"
    description = "<selfie>prompt for image generator, use 'the character' to refer to the character in the reference image</selfie> # send an specific image, could be a selfie or any image with the character in it. DO NOT describe the appearance of the character, the reference image already has it."

    def __init__(self, ctx):
        super().__init__(ctx=ctx)

    async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
        try:
            ref_img_path = self.ctx.config.get('bot_config', {}).get('selfie', {}).get('path', '')
            if os.path.exists(f"{get_data_path()}/{ref_img_path}"):
                img_extension = ref_img_path.split(".")[-1]
                bs64 = await image_to_base64(f"{get_data_path()}/{ref_img_path}")
                # img_res = await self.ctx.llm_api.image_to_image(value, bs64=f"data:image/{img_extension};base64,{bs64}")
                img_res = await self.ctx.llm_api.image_to_image(value, image=Image(image=bs64, name=ref_img_path, mime=f"image/{img_extension}"))
                if img_res:
                    return [img_res]
                logger.warning("Invalid selfie image result")
            else:
                logger.warning(f"Selfie reference image not found, skipped generation")
        except Exception as e:
            logger.error(f"Failed to generate selfie: {e}")
        return []


def _get_relative_file_paths():
    file_dir = get_data_path() / "files"
    os.makedirs(file_dir, exist_ok=True)
    files = os.listdir(file_dir)
    return files


class FileTag(BaseTag):
    name = "file"
    description = f"<file type=\"image/record/video/file\">file_string</file> # send a file (do not put any other tags in the msg tag which the file tag is in), file_string could be a file url, absolute file path or relative file path. Use `type=` to specify the file type for platforms to parse, e.g. for audios, set `type` as `record` to send as voice message, `file` to send as audio file. defaults to `file`. Files specifically listed below could be sent with `data/files/` prefix: {_get_relative_file_paths()}"

    def __init__(self, ctx):
        super().__init__(ctx=ctx)

    async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
        file_type = kwargs.get("type")  # image, record, file, video
        if not file_type or file_type not in ("image", "record", "video"):
            file_type = "file"

        # Absolute path
        if os.path.exists(value):
            file_string = value
            name = Path(value).name
        elif value.startswith(("data/files/", "data/temp/")):
            abs_path = str(get_data_path() / value.removeprefix("data/"))
            file_string = abs_path
            name = Path(abs_path).name
        # File URL
        elif value.startswith(("http://", "https://")):
            file_string = value
            name = None
        else:
            return []

        if file_type == "file":
            return [File(file=file_string, name=name)]
        elif file_type == "image":
            return [Image(image=file_string, name=name)]
        elif file_type == "record":
            return [Record(record=file_string, name=name)]
        elif file_type == "video":
            return [Video(file=file_string, name=name)]
        else:
            return []


class ForwardTag(BaseTag):
    name = "forward"
    description = "<forward merge='true/false'>message_id</forward> # 用于将Forward消息再次转发，或者将多条消息合并转发。用户需要你转发消息到其他会话时使用此标签，跨会话描述需要完整给出需要转发的消息ID，message_id可以为一条Forward消息的ID，也可以是多条消息ID使用英文逗号分隔。当你需要转发Forward消息时将merge设置为false，其他情况为true或者不使用merge参数。该消息标签**必须**单独放在一个<msg>中"

    async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
        merge = kwargs.get("merge")
        if merge == "false":
            merge = False
        else:
            merge = True
        message_id = [x.strip() for x in value.split(",") if x.strip()]
        return [Forward(message_id=message_id, merge=merge)]
