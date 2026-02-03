import base64
import requests


def image_to_base64(image_path: str):
    """
    convert an image to base64
    :param image_path: 图片文件路径或网络URL
    :return: Base64编码的字符串
    """
    if image_path.startswith("http://") or image_path.startswith("https://"):
        resp = requests.get(image_path)
        image_data = resp.content
        base64_data = base64.b64encode(image_data)
        return base64_data.decode('utf-8')
    with open(image_path, 'rb') as image_file:
        base64_data = base64.b64encode(image_file.read())
    return base64_data.decode('utf-8')
