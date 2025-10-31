from openai import OpenAI
from io import BytesIO
import requests
import base64

from core.config_loader import global_config

MAIN_PROVIDER = global_config["models"].get("main_llm").get("provider")
API_KEY = global_config["providers"].get(MAIN_PROVIDER).get("api_key")
VOICE_NAME = global_config["models"].get("tts").get("voice_name")
TTS_MODEL = global_config["models"].get("tts").get("model")
STT_MODEL = global_config["models"].get("stt").get("model")


def generate_speech(text, voice_name=VOICE_NAME):
    client = OpenAI(
        api_key=API_KEY,
        base_url="https://api.siliconflow.cn/v1"
    )

    with client.audio.speech.with_streaming_response.create(
      model=TTS_MODEL,
      voice=voice_name,
      input=text,
      response_format="mp3"
    ) as response:
        # response.stream_to_file(speech_file_path)
        audio_bytes = b"".join(response.iter_bytes())

    b64_str = base64.b64encode(audio_bytes).decode("utf-8")
    # audio_bs64 = f"base64://{b64_str}"
    # return str(speech_file_path)
    return b64_str


def speech_to_text(audio_base64):
    url = "https://api.siliconflow.cn/v1/audio/transcriptions"

    audio_data = base64.b64decode(audio_base64)
    audio_file = BytesIO(audio_data)
    audio_file.name = "audio.wav"

    files = {"file": audio_file}
    payload = {"model": STT_MODEL}
    headers = {"Authorization": f"Bearer {API_KEY}"}

    response = requests.post(url, data=payload, files=files, headers=headers)
    resp_json = response.json()
    return resp_json.get("text", "")