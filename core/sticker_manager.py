import asyncio
import json
import os
import uuid
import inspect

from typing import Optional, Union, Any, Callable
from copy import deepcopy

from core.logging_manager import get_logger
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

    def off_sticker_registered(self, callback: Callable):
        try:
            self._on_registered_callbacks.remove(callback)
        except ValueError:
            pass

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

    def register_sticker(self, filename: str, desc: str, sticker_id: Optional[str] = None):
        """save sticker info to self.sticker_dict"""
        if sticker_id:
            sid = str(sticker_id)
        else:
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
        self.register_sticker(filename, final_desc, sid)
        return {
            "id": sid,
            "desc": final_desc,
            "path": filename,
        }
