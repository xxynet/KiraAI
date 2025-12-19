from openai import AsyncOpenAI
from io import BytesIO
import requests
import base64

from ..provider import ImageProvider, TTSProvider, STTProvider
from ..image_result import ImageResult


class SiliconflowImageProvider(ImageProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def generate_image(self, prompt) -> ImageResult:
        """
        generate image via siliconflow
        :param prompt: prompt of image generation
        :return: ImageResult with image url
        """
        url = "https://api.siliconflow.cn/v1/images/generations"
        payload = {
            "model": self.provider_config.get("model", ""),
            "prompt": prompt,
            "image_size": "1024x1024",
            "batch_size": 1,
            "num_inference_steps": 20,
            "guidance_scale": 7.5
        }
        headers = {
            "Authorization": f"Bearer {self.provider_config.get('api_key', '')}",
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=payload, headers=headers)
        image_url = response.json().get("images")[0].get("url")
        return ImageResult(image_url)


class SiliconflowTTSProvider(TTSProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def text_to_speech(self, text: str):
        client = AsyncOpenAI(
            api_key=self.provider_config.get("api_key", ""),
            base_url="https://api.siliconflow.cn/v1"
        )

        async with client.audio.speech.with_streaming_response.create(
                model=self.provider_config.get("model", ""),
                voice=self.provider_config.get("voice_name", ""),
                input=text,
                response_format="mp3"
        ) as response:
            # response.stream_to_file(speech_file_path)
            audio_bytes = b""
            async for chunk in response.iter_bytes():
                audio_bytes += chunk

        b64_str = base64.b64encode(audio_bytes).decode("utf-8")
        # audio_bs64 = f"base64://{b64_str}"
        # return str(speech_file_path)
        return b64_str


class SiliconflowSTTProvider(STTProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def speech_to_text(self, audio_base64: str) -> str:
        url = "https://api.siliconflow.cn/v1/audio/transcriptions"

        audio_data = base64.b64decode(audio_base64)
        audio_file = BytesIO(audio_data)
        audio_file.name = "audio.wav"

        files = {"file": audio_file}
        payload = {"model": self.provider_config.get("model", "")}
        headers = {"Authorization": f"Bearer {self.provider_config.get('api_key', '')}"}

        response = requests.post(url, data=payload, files=files, headers=headers)
        resp_json = response.json()
        return resp_json.get("text", "")
