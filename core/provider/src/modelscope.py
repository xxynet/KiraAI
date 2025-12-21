import requests
import base64
import time
import json

from ..provider import ImageProvider, TTSProvider, STTProvider
from ..image_result import ImageResult


class ModelScopeImageProvider(ImageProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)
        self.timeout = int(self.provider_config.get("timeout", "10"))

    async def text_to_image(self, prompt) -> ImageResult:
        """
        generate image via modelscope
        :param prompt: prompt of image generation
        :return: ImageResult with base64 encoded image
        """

        base_url = 'https://api-inference.modelscope.cn/'
        api_key = self.provider_config.get("api_key", "")  # ModelScope Token

        common_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            f"{base_url}v1/images/generations",
            headers={**common_headers, "X-ModelScope-Async-Mode": "true"},
            data=json.dumps({
                "model": self.provider_config.get("model", ""),  # ModelScope Model-Id, required
                # "loras": "<lora-repo-id>", # optional lora(s)
                # """
                # LoRA(s) Configuration:
                # - for Single LoRA:
                # "loras": "<lora-repo-id>"
                # - for Multiple LoRAs:
                # "loras": {"<lora-repo-id1>": 0.6, "<lora-repo-id2>": 0.4}
                # - Upto 6 LoRAs, all weight-coeffients must sum to 1.0
                # """
                "prompt": prompt
            }, ensure_ascii=False).encode('utf-8')
        )

        response.raise_for_status()
        task_id = response.json()["task_id"]

        start_time = int(time.time())

        while int(time.time()) - start_time < self.timeout:
            result = requests.get(
                f"{base_url}v1/tasks/{task_id}",
                headers={**common_headers, "X-ModelScope-Task-Type": "image_generation"},
            )
            result.raise_for_status()
            data = result.json()

            if data["task_status"] == "SUCCEED":
                image_content = requests.get(data["output_images"][0]).content
                image_base64 = base64.b64encode(image_content).decode('utf-8')
                return ImageResult(base64=image_base64)
            elif data["task_status"] == "FAILED":
                print("Image Generation Failed.")
                break

            time.sleep(2)

        # TODO change this statement to logging
        print("timeout while generating image using model scope")
