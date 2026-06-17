import base64
import aiohttp

from core.provider import ModelInfo, TTSModelClient
from core.chat.message_elements import Record
from core.logging_manager import get_logger


logger = get_logger("provider", "purple")


class GptSovitsTTSClient(TTSModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_speech(self, text: str, **kwargs) -> Record:
        mp = self.model.provider_config

        tts_url = mp.get("base_url", "http://127.0.0.1:9880/tts")

        # 从 model_config 读取所有配置参数
        mc = self.model.model_config

        # 可选参数：超时
        section_advanced = mc.get("section_advanced")
        timeout = 60
        if isinstance(section_advanced, dict):
            timeout = section_advanced.get("timeout", 60)

        # 构建请求参数，GPT-SoVITS API 标准字段名
        payload = {
            "text": text,
            "text_lang": mc.get("text_language", "auto"),
            "media_type": "wav",
            "streaming_mode": True
        }

        # 参数：参考音频（用于音色克隆）
        ref_audio = mp.get("ref_audio_path", "") if not mc.get("ref_audio_path", "") else mc.get("ref_audio_path", "")
        if ref_audio:
            payload["ref_audio_path"] = ref_audio

        ref_text = mp.get("ref_text", "") if not mc.get("ref_text", "") else mc.get("ref_text", "")
        if ref_text:
            payload["prompt_text"] = ref_text

        ref_language = mc.get("ref_language", "")
        if ref_language and ref_language != "auto":
            payload["prompt_lang"] = ref_language

        # 可选参数：合成控制
        speed = mc.get("speed")
        if speed is not None:
            payload["speed_factor"] = float(speed)

        top_k = mc.get("top_k")
        if top_k is not None:
            payload["top_k"] = int(top_k)

        top_p = mc.get("top_p")
        if top_p is not None:
            payload["top_p"] = float(top_p)

        temperature = mc.get("temperature")
        if temperature is not None:
            payload["temperature"] = float(temperature)

        # 每次请求创建独立的 session，用完后自动关闭，避免连接泄漏
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit_per_host=4),
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.post(
                tts_url,
                headers={'Content-Type': 'application/json'},
                json=payload
            ) as response:

                if response.status == 200:
                    audio_bytes = b""
                    async for chunk in response.content.iter_any():
                        audio_bytes += chunk
                else:
                    logger.error(f"GPT-Sovits TTS Request failed: {response.status}")
                    try:
                        error_info = await response.json()
                        logger.error(f"GPT-Sovits Error: {error_info}")
                    except:
                        pass
                    return None

        b64_str = base64.b64encode(audio_bytes).decode("utf-8")
        return Record(record=b64_str)