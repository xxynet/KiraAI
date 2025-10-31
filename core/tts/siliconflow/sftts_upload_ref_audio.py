import requests

API_KEY = ""

url = "https://api.siliconflow.cn/v1/uploads/audio/voice"
headers = {
    "Authorization": f"Bearer {API_KEY}"
}
files = {
    "file": open("neuro.mp3", "rb") # 参考音频文件
}
data = {
    "model": "FunAudioLLM/CosyVoice2-0.5B", # 模型名称
    "customName": "neuro-sama", # 参考音频名称
    "text": "Hey guys, how's life? Has it been updated recently?" # 参考音频的文字内容
}

response = requests.post(url, headers=headers, files=files, data=data)

print(response.status_code)
print(response.json())  # 打印响应内容（如果是JSON格式）