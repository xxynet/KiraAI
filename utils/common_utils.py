import base64


def image_to_base64(image_path):
    """
    convert an image to base64
    :param image_path: 图片文件路径
    :return: Base64编码的字符串
    """
    with open(image_path, 'rb') as image_file:
        base64_data = base64.b64encode(image_file.read())
    return base64_data.decode('utf-8')
