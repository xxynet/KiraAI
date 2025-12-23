import asyncio
import json
import os

from core.llm_manager import llm_api
from core.logging_manager import get_logger
from utils.common_utils import image_to_base64

logger = get_logger("sticker", "orange")

_sticker_path: str = "data/config/sticker.json"
_sticker_folder: str = "data/sticker"


class StickerManager:
    def __init__(self):
        self.sticker_path = _sticker_path
        self.sticker_folder = _sticker_folder
        self.sticker_dict = {}
        self.sticker_paths: list = []
        self.sticker_index: int = 0

        self.init_sticker_dict()

    def init_sticker_dict(self):
        try:
            if not os.path.exists(self.sticker_folder):
                os.makedirs(self.sticker_folder)

            if not os.path.exists(self.sticker_path):
                logger.info(f"{self.sticker_path} not found. Creating an empty sticker.json")
                os.makedirs(os.path.dirname(self.sticker_path), exist_ok=True)
                with open(self.sticker_path, "w", encoding="utf-8") as f:
                    f.write("{}")

            with open(self.sticker_path, 'r', encoding="utf-8") as f:
                sticker_json = f.read()

            sticker_dict = json.loads(sticker_json)

            if sticker_dict:
                self.sticker_index = int(next(reversed(sticker_dict)))
            else:
                self.sticker_index = 0

            self.sticker_paths = [sticker_dict[sticker_id].get("path") for sticker_id in sticker_dict]

            self.sticker_dict = sticker_dict
        except Exception as e:
            logger.error(f"Error loading emoji dict from {self.sticker_path}: {e}")
            self.sticker_dict = {}

    def register_sticker(self, filename, desc):
        """save sticker info to self.sticker_dict"""
        self.sticker_index += 1
        self.sticker_dict[str(self.sticker_index)] = {
            "desc": desc,
            "path": filename
        }

    async def scan_and_register_sticker(self):
        while True:
            logger.info("Scanning unregistered stickers")
            sticker_files = os.listdir(self.sticker_folder)
            is_found = False
            for sticker_file in sticker_files:
                if sticker_file not in self.sticker_paths:
                    is_found = True
                    logger.info(f"found sticker {sticker_file}")
                    sticker_description = await self.get_sticker_description(sticker_file)
                    logger.info(f"Registered sticker: {sticker_description}")
                    self.register_sticker(sticker_file, sticker_description)

            if is_found:
                with open(self.sticker_path, "w", encoding="utf-8") as f:
                    f.write(json.dumps(self.sticker_dict, indent=4, ensure_ascii=False))
            else:
                logger.info("All stickers are already registered")

            # TODO customize interval in config file
            await asyncio.sleep(120 * 60)

    @staticmethod
    async def get_sticker_description(sticker_file):
        sticker_path = os.path.join(_sticker_folder, sticker_file)

        img_b64 = image_to_base64(sticker_path)

        sticker_desc = await llm_api.desc_img(image=img_b64, prompt="这是一张sticker（表情包），请描述这张表情包的内容和聊天中哪些情景使用此表情包，要求描述精确，不要太长，不要使用Markdown等标记符号，如果有文字请将其输出", is_base64=True)

        return sticker_desc


if __name__ == '__main__':
    from pathlib import Path
    # set script dir as working dir
    working_dir = Path(__file__).parent.parent
    os.chdir(working_dir)

    # to tests, comment out the following line & comment the same statement above
    # from core.llm_manager import llm_api

    test_mgr = StickerManager()

    asyncio.run(test_mgr.scan_and_register_sticker())
