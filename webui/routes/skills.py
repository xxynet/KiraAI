import asyncio
import json
import os
import shutil
import tempfile
import zipfile
from typing import Any, Dict, List, Optional

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from core.logging_manager import get_logger
from core.agent.skills_mgr import SkillsManager
from core.utils.path_utils import safe_extract_zip
from webui.models import SkillItem
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("webui", "blue")


class SkillsRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/skills",
                methods=["GET"],
                endpoint=self.list_skills,
                response_model=List[SkillItem],
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

    @classmethod
    def _folder_sizes(cls, paths: List[Any]) -> List[int]:
        return [cls._folder_size(path) for path in paths]

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
            skills_info = list(skills_manager.skills_info)
            sizes = await asyncio.to_thread(
                self._folder_sizes, [skill.path for skill in skills_info]
            )
            items: List[SkillItem] = []
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

    async def set_skill_enabled(self, skill_name: str, payload: Dict):
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
            import zipfile
            import tempfile

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
