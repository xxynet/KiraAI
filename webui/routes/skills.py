import asyncio
import mimetypes
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from core.agent.skills_mgr import SkillsManager, SkillValidationError
from core.logging_manager import get_logger
from core.utils.path_utils import is_within_directory, safe_extract_zip
from webui.models import SkillItem, SkillFileItem, SkillFileUpdateRequest
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("webui", "blue")
MAX_EDITABLE_FILE_BYTES = 2 * 1024 * 1024
IMAGE_MIME_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif",
    "image/bmp", "image/x-icon", "image/vnd.microsoft.icon",
})


class SkillsRoutes(Routes):
    def __init__(self, app, lifecycle=None):
        super().__init__(app, lifecycle)
        self._content_lock = asyncio.Lock()

    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/skills",
                methods=["GET"],
                endpoint=self.list_skills,
                response_model=list[SkillItem],
                tags=["skills"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/skills/{skill_name}/enabled",
                methods=["POST"],
                endpoint=self.set_skill_enabled,
                tags=["skills"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/skills/refresh",
                methods=["POST"],
                endpoint=self.refresh_skills,
                tags=["skills"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/skills/upload",
                methods=["POST"],
                endpoint=self.upload_skill,
                tags=["skills"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/skills/{skill_name}/export",
                methods=["GET"],
                endpoint=self.export_skill,
                tags=["skills"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/skills/{skill_name}/files",
                methods=["GET"],
                endpoint=self.list_skill_files,
                response_model=list[SkillFileItem],
                tags=["skills"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/skills/{skill_name}/file",
                methods=["GET"],
                endpoint=self.get_skill_file,
                tags=["skills"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/skills/{skill_name}/file",
                methods=["PUT"],
                endpoint=self.update_skill_file,
                tags=["skills"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/skills/{skill_name}/file/download",
                methods=["GET"],
                endpoint=self.download_skill_file,
                tags=["skills"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/skills/{skill_name}",
                methods=["DELETE"],
                endpoint=self.delete_skill,
                tags=["skills"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    def _get_skill(self, skill_name: str):
        if not self.lifecycle or not hasattr(self.lifecycle, "skills_manager"):
            raise HTTPException(status_code=503, detail="Skills manager not available")
        for skill in self.lifecycle.skills_manager.skills_info:
            if skill.name == skill_name:
                return skill
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    @staticmethod
    def _folder_size(path) -> int:
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

    def _skill_path(self, skill) -> Path:
        skill_path = skill.path.resolve()
        skills_dir = self.lifecycle.skills_manager.skills_dir.resolve()
        if skill_path.parent != skills_dir:
            raise HTTPException(status_code=400, detail="Invalid skill path")
        if not skill_path.is_dir():
            raise HTTPException(status_code=404, detail="Skill directory not found")
        return skill_path

    def _file_path(self, skill, path: str) -> Path:
        if (
            not path or "\x00" in path or "\\" in path or ":" in path
            or PurePosixPath(path).is_absolute() or PureWindowsPath(path).drive
            or ".." in PurePosixPath(path).parts
        ):
            raise HTTPException(status_code=400, detail="Invalid skill file path")
        skill_path = self._skill_path(skill)
        file_path = (skill_path / path).resolve()
        if not is_within_directory(skill_path, file_path):
            raise HTTPException(status_code=400, detail="Invalid skill file path")
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail=f"Skill file not found: {path}")
        return file_path

    @staticmethod
    def _read_text_file(file_path: Path) -> str:
        with file_path.open("rb") as file:
            data = file.read(MAX_EDITABLE_FILE_BYTES + 1)
        if len(data) > MAX_EDITABLE_FILE_BYTES:
            raise HTTPException(status_code=413, detail="Text editing is limited to files up to 2 MiB")
        if b"\x00" in data:
            raise HTTPException(status_code=415, detail="Binary files cannot be edited as text")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise HTTPException(status_code=415, detail="Only UTF-8 text files can be edited") from e

    async def list_skill_files(self, skill_name: str):
        try:
            skill = self._get_skill(skill_name)

            def scan_files():
                skill_path = self._skill_path(skill)
                items = []

                def on_error(error):
                    raise error

                for root, directories, files in os.walk(skill_path, onerror=on_error):
                    root_path = Path(root)
                    directories[:] = sorted(
                        name for name in directories
                        if (root_path / name).resolve() == (root_path / name).absolute()
                    )
                    for name in files:
                        file_path = root_path / name
                        if file_path.is_file() and is_within_directory(skill_path, file_path):
                            items.append(SkillFileItem(
                                path=file_path.relative_to(skill_path).as_posix(),
                                size_bytes=file_path.stat().st_size,
                            ))
                return sorted(items, key=lambda item: (item.path != "SKILL.md", item.path.casefold()))

            return await asyncio.to_thread(scan_files)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to list files for skill {skill_name}: {e}")
            raise HTTPException(status_code=500, detail="Failed to list skill files")

    async def get_skill_file(self, skill_name: str, path: str):
        try:
            skill = self._get_skill(skill_name)

            def read_file():
                file_path = self._file_path(skill, path)
                result = {"path": path, "size_bytes": file_path.stat().st_size, "content": None}
                if result["size_bytes"] > MAX_EDITABLE_FILE_BYTES:
                    return {**result, "kind": "binary", "reason": "too_large"}
                if mimetypes.guess_type(file_path.name)[0] in IMAGE_MIME_TYPES:
                    return {**result, "kind": "image", "reason": None}
                try:
                    content = self._read_text_file(file_path)
                except HTTPException as e:
                    if e.status_code not in (413, 415):
                        raise
                    return {**result, "kind": "binary", "reason": "too_large" if e.status_code == 413 else "non_text"}
                return {**result, "kind": "text", "content": content, "reason": None}

            return await asyncio.to_thread(read_file)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to read skill file {skill_name}/{path}: {e}")
            raise HTTPException(status_code=500, detail="Failed to read skill file")

    async def download_skill_file(self, skill_name: str, path: str):
        try:
            skill = self._get_skill(skill_name)
            file_path = await asyncio.to_thread(self._file_path, skill, path)
            return FileResponse(
                file_path, filename=file_path.name, media_type="application/octet-stream",
                headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to download skill file {skill_name}/{path}: {e}")
            raise HTTPException(status_code=500, detail="Failed to download skill file")

    async def update_skill_file(self, skill_name: str, payload: SkillFileUpdateRequest, path: str):
        try:
            async with self._content_lock:
                skill = self._get_skill(skill_name)

                def save_content():
                    content_path = self._file_path(skill, path)
                    try:
                        content_bytes = payload.content.encode("utf-8")
                    except UnicodeEncodeError as e:
                        raise HTTPException(status_code=400, detail={
                            "code": "invalid_encoding", "message": "Content must be valid UTF-8",
                        }) from e
                    if len(content_bytes) > MAX_EDITABLE_FILE_BYTES:
                        raise HTTPException(status_code=413, detail="Text editing is limited to files up to 2 MiB")
                    if b"\x00" in content_bytes:
                        raise HTTPException(status_code=415, detail="Binary files cannot be edited as text")
                    if self._read_text_file(content_path) != payload.original_content:
                        raise HTTPException(
                            status_code=409,
                            detail="The file has changed. Reopen it before editing again.",
                        )
                    info = None
                    if content_path == (self._skill_path(skill) / "SKILL.md").resolve():
                        try:
                            info = SkillsManager.parse_skill_content(payload.content, skill.path)
                        except SkillValidationError as e:
                            detail = {"code": e.code, "message": str(e)}
                            if e.code == "invalid_yaml" and e.__cause__ is not None:
                                detail["diagnostic"] = str(e.__cause__)
                            raise HTTPException(status_code=400, detail=detail) from e
                        if info.name != skill.name:
                            raise HTTPException(status_code=400, detail={
                                "code": "name_immutable", "message": "Skill name cannot be changed",
                            })
                    temporary_path = None
                    try:
                        with tempfile.NamedTemporaryFile(
                            mode="w", encoding="utf-8", newline="", dir=content_path.parent,
                            prefix=".skill-", suffix=".tmp", delete=False,
                        ) as temporary_file:
                            temporary_path = temporary_file.name
                            temporary_file.write(payload.content)
                        os.chmod(temporary_path, stat.S_IMODE(content_path.stat().st_mode))
                        os.replace(temporary_path, content_path)
                    finally:
                        if temporary_path and os.path.exists(temporary_path):
                            os.unlink(temporary_path)
                    return info

                info = await asyncio.to_thread(save_content)
                if info:
                    for current_skill in self.lifecycle.skills_manager.skills_info:
                        if current_skill.name == skill.name and current_skill.path == skill.path:
                            current_skill.description = info.description
                return {
                    "skill_name": skill.name, "path": path, "saved": True,
                    "description": info.description if info else skill.description,
                    "size_bytes": len(payload.content.encode("utf-8")),
                }
        except HTTPException as e:
            codes = {
                400: "invalid_path", 404: "not_found", 409: "file_changed",
                413: "too_large", 415: "not_text", 503: "unavailable",
            }
            if isinstance(e.detail, str) and e.status_code in codes:
                e.detail = {"code": codes[e.status_code], "message": e.detail}
            raise
        except Exception as e:
            logger.error(f"Failed to save skill file {skill_name}/{path}: {e}")
            raise HTTPException(status_code=500, detail={
                "code": "write_failed", "message": "Failed to save skill file", "diagnostic": str(e),
            })

    @staticmethod
    def _create_skill_archive(skill_path, archive_path) -> None:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file_path in skill_path.rglob("*"):
                if file_path.is_file():
                    zip_file.write(file_path, file_path.relative_to(skill_path.parent))

    async def list_skills(self):
        if not self.lifecycle or not hasattr(self.lifecycle, "skills_manager"):
            raise HTTPException(status_code=503, detail="Skills manager not available")
        else:
            skills_manager = self.lifecycle.skills_manager

        try:
            skills_info = skills_manager.skills_info
            sizes = await asyncio.gather(
                *(asyncio.to_thread(self._folder_size, skill.path) for skill in skills_info)
            )
            items: list[SkillItem] = []
            for skill, size_bytes in zip(skills_info, sizes):
                items.append(
                    SkillItem(
                        id=str(skill.name),
                        name=str(skill.name),
                        description=str(skill.description),
                        enabled=bool(skill.enabled),
                        path=str(skill.path),
                        size_bytes=size_bytes,
                    )
                )
            return items
        except Exception as e:
            logger.error(f"Failed to list skills: {e}")
            raise HTTPException(status_code=500, detail="Failed to list skills")

    async def set_skill_enabled(self, skill_name: str, payload: dict):
        if not self.lifecycle or not hasattr(self.lifecycle, "skills_manager"):
            raise HTTPException(status_code=503, detail="Skills manager not available")
        try:
            enabled = bool(payload.get("enabled"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid payload")
        try:
            skills_manager = self.lifecycle.skills_manager
            success = skills_manager.set_skill_enabled(skill_name, enabled)
            if not success:
                raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
            return {"skill_name": skill_name, "enabled": enabled}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to set skill enabled state for {skill_name}: {e}")
            raise HTTPException(status_code=500, detail="Failed to update skill state")

    async def export_skill(self, skill_name: str):
        archive_path = None
        try:
            skill = self._get_skill(skill_name)
            archive_fd, archive_path = tempfile.mkstemp(prefix="kira-skill-", suffix=".zip")
            os.close(archive_fd)
            await asyncio.to_thread(self._create_skill_archive, skill.path, archive_path)

            def cleanup_archive() -> None:
                if archive_path:
                    try:
                        os.unlink(archive_path)
                    except FileNotFoundError:
                        pass

            def iter_archive():
                try:
                    with open(archive_path, "rb") as archive_file:
                        while chunk := archive_file.read(1024 * 1024):
                            yield chunk
                finally:
                    cleanup_archive()

            return StreamingResponse(
                iter_archive(),
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{skill.path.name}.zip"'},
                background=BackgroundTask(cleanup_archive),
            )
        except HTTPException:
            raise
        except Exception as e:
            if archive_path:
                try:
                    os.unlink(archive_path)
                except FileNotFoundError:
                    pass
            logger.error(f"Failed to export skill {skill_name}: {e}")
            raise HTTPException(status_code=500, detail="Failed to export skill")

    async def delete_skill(self, skill_name: str):
        try:
            skill = self._get_skill(skill_name)
            skill_path = skill.path.resolve()
            skills_dir = self.lifecycle.skills_manager.skills_dir.resolve()
            if skill_path.parent != skills_dir or not skill_path.is_dir():
                raise HTTPException(status_code=400, detail="Invalid skill path")
            shutil.rmtree(skill_path)
            manager = self.lifecycle.skills_manager
            manager.skills_config_dict.pop(skill.name, None)
            scope = manager._raw_config.get("_scope", {})
            scope.pop(skill.name, None)
            manager._save_config()
            manager.skills_info = manager.scan_skill_dir()
            return {"skill_name": skill_name, "deleted": True}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to delete skill {skill_name}: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete skill")

    async def refresh_skills(self):
        if not self.lifecycle or not hasattr(self.lifecycle, "skills_manager"):
            raise HTTPException(status_code=503, detail="Skills manager not available")
        try:
            skills_manager = self.lifecycle.skills_manager
            skills_manager.skills_info = skills_manager.scan_skill_dir()
            return {"refreshed": True}
        except Exception as e:
            logger.error(f"Failed to refresh skills: {e}")
            raise HTTPException(status_code=500, detail="Failed to refresh skills")

    async def upload_skill(self, file: UploadFile = File(...)):
        if not self.lifecycle or not hasattr(self.lifecycle, "skills_manager"):
            raise HTTPException(status_code=503, detail="Skills manager not available")

        if not file.filename or not file.filename.endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip files are accepted")

        skills_manager = self.lifecycle.skills_manager
        skills_dir = skills_manager.skills_dir

        try:
            import tempfile
            import zipfile

            # Create a temporary directory to extract the zip
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = os.path.join(temp_dir, file.filename)
                with open(zip_path, "wb") as f:
                    shutil.copyfileobj(file.file, f)

                # Extract the zip. safe_extract_zip rejects members whose paths
                # escape extract_dir (Zip-Slip), unlike a bare extractall().
                extract_dir = os.path.join(temp_dir, "extracted")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    safe_extract_zip(zip_ref, extract_dir)

                # Find the skill directory (should contain SKILL.md)
                skill_dirs = []
                for root, dirs, files in os.walk(extract_dir):
                    if "SKILL.md" in files:
                        skill_dirs.append(root)
                        break

                if not skill_dirs:
                    raise HTTPException(status_code=400, detail="No valid skill found in the uploaded archive")

                skill_source_dir = skill_dirs[0]
                skill_name = os.path.basename(skill_source_dir)

                # Check if skill already exists
                dest_dir = skills_dir / skill_name
                if dest_dir.exists():
                    raise HTTPException(status_code=400, detail=f"Skill '{skill_name}' already exists")

                # Copy the skill directory
                shutil.copytree(skill_source_dir, dest_dir)

                # Refresh skills
                skills_manager.skills_info = skills_manager.scan_skill_dir()

                return {"skill_name": skill_name, "uploaded": True}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to upload skill: {e}")
            raise HTTPException(status_code=500, detail="Failed to upload skill")
