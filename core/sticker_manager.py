import asyncio
import json
import os
import uuid
import inspect

from typing import Optional, Union, Any, Callable
from copy import deepcopy

from core.logging_manager import get_logger
from core.utils.common_utils import desc_img
from core.utils.path_utils import get_data_path

logger = get_logger("sticker", "orange")


class StickerManager:
    def __init__(self, provider_mgr):
        self.provider_mgr = provider_mgr
        self.sticker_path = f"{get_data_path()}/config/sticker.json"
        self.sticker_folder = f"{get_data_path()}/sticker"
        self.sticker_dict = {}
        self.sticker_paths: list = []
        self.sticker_index: int = 0

        # Callbacks
        self._on_registered_callbacks: list[Callable] = []

        self._init_sticker_dict()

    def on_sticker_registered(self, callback: Callable):
        """注册回调，支持同步和 async 函数。

        Callback signature: callback(sticker_id: str, sticker_info: dict)
        sticker_info contains desc / path
        """
        self._on_registered_callbacks.append(callback)
        return callback

    async def _fire_registered(self, sid: str, info: dict):
        for cb in self._on_registered_callbacks:
            try:
                if inspect.iscoroutinefunction(cb):
                    await cb(sid, info)
                else:
                    cb(sid, info)
            except Exception as e:
                logger.error(f"Sticker registered callback error: {e}")

    def _init_sticker_dict(self):
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

            numeric_ids = []
            for key in sticker_dict:
                if isinstance(key, str) and key.isdigit():
                    try:
                        numeric_ids.append(int(key))
                    except Exception:
                        pass
            self.sticker_index = max(numeric_ids) if numeric_ids else 0

            self.sticker_paths = [sticker_dict[sticker_id].get("path") for sticker_id in sticker_dict]

            self.sticker_dict = sticker_dict
        except Exception as e:
            logger.error(f"Error loading emoji dict from {self.sticker_path}: {e}")
            self.sticker_dict = {}

    def register_sticker(self, filename: str, desc: str):
        """save sticker info to self.sticker_dict"""
        self.sticker_index += 1
        sid = str(self.sticker_index)
        self.sticker_dict[sid] = {
            "desc": desc,
            "path": filename,
            "extra": {}
        }
        self.sticker_paths.append(filename)
        self.save_sticker_dict()

        asyncio.create_task(self._fire_registered(sid, {"desc": desc, "path": filename}))

    def save_sticker_dict(self):
        try:
            os.makedirs(os.path.dirname(self.sticker_path), exist_ok=True)
            with open(self.sticker_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.sticker_dict, indent=4, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Error saving sticker dict to {self.sticker_path}: {e}")

    def update_sticker_desc(self, sticker_id: str, desc: str):
        sid = str(sticker_id)
        sticker = self.sticker_dict.get(sid)
        if not sticker:
            raise KeyError(sid)
        sticker["desc"] = desc
        self.save_sticker_dict()
        return {
            "id": sid,
            "desc": sticker.get("desc") or "",
            "path": sticker.get("path") or "",
        }

    def delete_sticker(self, sticker_id: str, delete_file: bool = False):
        sid = str(sticker_id)
        sticker = self.sticker_dict.pop(sid, None)
        if not sticker:
            raise KeyError(sid)
        path = sticker.get("path")
        if path:
            self.sticker_paths = [p for p in self.sticker_paths if p != path]
            file_path = os.path.join(self.sticker_folder, path)
            if delete_file and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    logger.error(f"Error deleting sticker file {file_path}: {e}")
        self.save_sticker_dict()

    def set_sticker_extra(self, sticker_id: str, key: Union[int, str], value: Any):
        sticker_info_dict = self.sticker_dict.get(sticker_id)
        if sticker_info_dict:
            if key is None:
                return False
            sticker_info_dict.setdefault("extra", {})[key] = value
            return True
        return False

    def get_sticker_extra(self, sticker_id: str, key: Optional[Union[int, str]] = None):
        """Get extra info of a sticker, return all extra info if key is not given"""
        sticker_info_dict = self.sticker_dict.get(sticker_id)
        if sticker_info_dict is None:
            raise KeyError(sticker_id)

        if key is None:
            return deepcopy(sticker_info_dict.get("extra", {}))

        value = sticker_info_dict.get("extra", {}).get(key)
        return deepcopy(value)

    async def add_sticker(self, file_bytes: bytes, original_filename: str, sticker_id: str | None = None, desc: str | None = None):
        if not original_filename:
            raise ValueError("File name is required")
        base_name = os.path.basename(original_filename)
        try:
            _, ext = os.path.splitext(base_name)
        except Exception:
            ext = ""
        if not ext:
            ext = ".png"
            base_name = base_name + ext
        filename = base_name
        os.makedirs(self.sticker_folder, exist_ok=True)
        file_path = os.path.join(self.sticker_folder, filename)
        with open(file_path, "wb") as f:
            f.write(file_bytes)
        final_desc = desc or ""
        if sticker_id and str(sticker_id).strip():
            sid = str(sticker_id).strip()
            if sid in self.sticker_dict:
                raise ValueError(f"Sticker id {sid} already exists")
            if sid.isdigit():
                try:
                    numeric_id = int(sid)
                    if numeric_id > self.sticker_index:
                        self.sticker_index = numeric_id
                except Exception:
                    pass
        else:
            self.sticker_index += 1
            sid = str(self.sticker_index)
        self.sticker_dict[sid] = {
            "desc": final_desc,
            "path": filename,
        }
        self.sticker_paths.append(filename)
        self.save_sticker_dict()
        # If description is not given, call VLM to get description in background, do not block upload response
        if not final_desc:
            asyncio.create_task(self._update_desc_in_background(sid, filename))
        return {
            "id": sid,
            "desc": final_desc,
            "path": filename,
        }

    async def _update_desc_in_background(self, sid: str, filename: str):
        try:
            desc = await self.get_sticker_description(filename)
            if desc and sid in self.sticker_dict:
                self.sticker_dict[sid]["desc"] = desc
                self.save_sticker_dict()
                logger.info(f"Sticker {sid} description updated by VLM: {desc}")
        except Exception as e:
            logger.error(f"Failed to get VLM description for sticker {sid}: {e}")

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

            if not is_found:
                logger.info("All stickers are already registered")

            # TODO customize interval in config file
            await asyncio.sleep(120 * 60)

    async def get_sticker_description(self, sticker_file):
        sticker_path = os.path.join(self.sticker_folder, sticker_file)

        # img_b64 = await image_to_base64(sticker_path)
        from core.chat.message_elements import Image

        vlm_model = self.provider_mgr.get_default_vlm()
        sticker_desc = await desc_img(client=vlm_model, image=Image(image=sticker_path), prompt="这是一张sticker（表情包），请描述这张表情包的内容和聊天中哪些情景使用此表情包，要求描述精确，不要太长，不要使用Markdown等标记符号，如果有文字请将其输出")

        return sticker_desc


if __name__ == '__main__':
    from pathlib import Path
    # set script dir as working dir
    working_dir = Path(__file__).parent.parent
    os.chdir(working_dir)

    # to tests, comment out the following line & comment the same statement above
    # from core.llm_manager import llm_api

    # test_mgr = StickerManager()

    # asyncio.run(test_mgr.scan_and_register_sticker())
