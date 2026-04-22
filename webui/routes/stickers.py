import json
from typing import List, Optional

from fastapi import Depends, File, Form, HTTPException, UploadFile, status

from core.logging_manager import get_logger
from core.utils.path_utils import get_data_path
from webui.models import StickerItem, StickerUpdateRequest
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("webui", "blue")


class StickersRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/stickers",
                methods=["GET"],
                endpoint=self.list_stickers,
                response_model=List[StickerItem],
                tags=["stickers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/stickers",
                methods=["POST"],
                endpoint=self.add_sticker,
                response_model=StickerItem,
                tags=["stickers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/stickers/{sticker_id}",
                methods=["GET"],
                endpoint=self.get_sticker,
                response_model=StickerItem,
                tags=["stickers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/stickers/{sticker_id}",
                methods=["PUT"],
                endpoint=self.update_sticker,
                response_model=StickerItem,
                tags=["stickers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/stickers/{sticker_id}",
                methods=["DELETE"],
                endpoint=self.delete_sticker,
                status_code=status.HTTP_204_NO_CONTENT,
                tags=["stickers"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def list_stickers(self):
        data = self.lifecycle.sticker_manager.sticker_dict

        stickers: List[StickerItem] = []
        if not isinstance(data, dict):
            return stickers
        sticker_folder = get_data_path() / "sticker"
        for sticker_id, info in data.items():
            if not isinstance(info, dict):
                continue
            path = info.get("path")
            desc = info.get("desc") or ""
            if not path:
                continue
            file_path = sticker_folder / path
            if not file_path.exists():
                continue
            stickers.append(StickerItem(id=str(sticker_id), desc=str(desc), path=str(path)))
        return stickers

    async def add_sticker(
        self,
        file: UploadFile = File(...),
        id: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
    ):
        if not file or not file.filename:
            raise HTTPException(status_code=400, detail="Sticker file is required")
        try:
            file_bytes = await file.read()
        except Exception as e:
            logger.error(f"Failed to read uploaded sticker file: {e}")
            raise HTTPException(status_code=500, detail="Failed to read sticker file")
        sticker_id = id.strip() if id else None
        desc = description.strip() if description else None
        if self.lifecycle and getattr(self.lifecycle, "sticker_manager", None):
            try:
                result = await self.lifecycle.sticker_manager.add_sticker(
                    file_bytes=file_bytes,
                    original_filename=file.filename,
                    sticker_id=sticker_id,
                    desc=desc,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                logger.error(f"Error adding sticker: {e}")
                raise HTTPException(status_code=500, detail="Failed to add sticker")
            return StickerItem(id=result["id"], desc=result["desc"], path=result["path"])

        sticker_config_path = get_data_path() / "config" / "sticker.json"
        try:
            if sticker_config_path.exists():
                with open(sticker_config_path, "r", encoding="utf-8") as f:
                    content = f.read()
                data = json.loads(content) if content.strip() else {}
            else:
                data = {}
        except Exception as e:
            logger.error(f"Failed to load stickers from {sticker_config_path}: {e}")
            raise HTTPException(status_code=500, detail="Failed to load stickers")
        if not isinstance(data, dict):
            data = {}
        sid = None
        if sticker_id:
            if sticker_id in data:
                raise HTTPException(status_code=400, detail="Sticker id already exists")
            sid = sticker_id
        else:
            numeric_ids = []
            for key in data.keys():
                if isinstance(key, str) and key.isdigit():
                    try:
                        numeric_ids.append(int(key))
                    except Exception:
                        continue
            next_id = max(numeric_ids) + 1 if numeric_ids else 1
            sid = str(next_id)
        sticker_folder = get_data_path() / "sticker"
        try:
            sticker_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create sticker folder {sticker_folder}: {e}")
            raise HTTPException(status_code=500, detail="Failed to prepare sticker folder")
        from pathlib import Path as _Path
        base_name = _Path(file.filename).name
        try:
            ext = _Path(base_name).suffix
        except Exception:
            ext = ""
        if not ext:
            ext = ".png"
            base_name = f"{base_name}{ext}"
        filename = base_name
        file_path = sticker_folder / filename
        try:
            with open(file_path, "wb") as f:
                f.write(file_bytes)
        except Exception as e:
            logger.error(f"Failed to save sticker file {file_path}: {e}")
            raise HTTPException(status_code=500, detail="Failed to save sticker file")
        final_desc = desc or ""
        data[sid] = {"desc": final_desc, "path": filename}
        try:
            sticker_config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(sticker_config_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=4, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Failed to save stickers to {sticker_config_path}: {e}")
            raise HTTPException(status_code=500, detail="Failed to save stickers")
        return StickerItem(id=sid, desc=final_desc, path=filename)

    async def get_sticker(self, sticker_id: str):
        sid = str(sticker_id)
        if self.lifecycle and getattr(self.lifecycle, "sticker_manager", None):
            sticker = self.lifecycle.sticker_manager.sticker_dict.get(sid)
            if not isinstance(sticker, dict):
                raise HTTPException(status_code=404, detail="Sticker not found")
            path = sticker.get("path") or ""
            desc = sticker.get("desc") or ""
        else:
            raise HTTPException(status_code=404, detail="Sticker manager not available")
        if not path:
            raise HTTPException(status_code=404, detail="Sticker not found")
        file_path = get_data_path() / "sticker" / path
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Sticker not found")
        return StickerItem(id=sid, desc=str(desc), path=str(path))

    async def update_sticker(self, sticker_id: str, payload: StickerUpdateRequest):
        desc = payload.desc or ""
        if self.lifecycle and getattr(self.lifecycle, "sticker_manager", None):
            try:
                result = await self.lifecycle.sticker_manager.update_sticker_desc(sticker_id, desc)
            except KeyError:
                raise HTTPException(status_code=404, detail="Sticker not found")
            except Exception as e:
                logger.error(f"Error updating sticker {sticker_id}: {e}")
                raise HTTPException(status_code=500, detail="Failed to update sticker")
            return StickerItem(id=result["id"], desc=result["desc"], path=result["path"])
        raise HTTPException(status_code=404, detail="Sticker manager not available")

    async def delete_sticker(self, sticker_id: str, delete_file: bool = False):
        if self.lifecycle and getattr(self.lifecycle, "sticker_manager", None):
            try:
                await self.lifecycle.sticker_manager.delete_sticker(sticker_id, delete_file=delete_file)
            except KeyError:
                raise HTTPException(status_code=404, detail="Sticker not found")
            except Exception as e:
                logger.error(f"Error deleting sticker {sticker_id}: {e}")
                raise HTTPException(status_code=500, detail="Failed to delete sticker")
            return None
        raise HTTPException(status_code=404, detail="Sticker manager not available")
