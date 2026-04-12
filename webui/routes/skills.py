import json
import os
import shutil
from typing import Any, Dict, List, Optional

from fastapi import Depends, File, HTTPException, UploadFile

from core.logging_manager import get_logger
from core.agent.skills_mgr import SkillsManager
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
        ]

    async def list_skills(self):
        if not self.lifecycle or not hasattr(self.lifecycle, "skills_manager"):
            raise HTTPException(status_code=503, detail="Skills manager not available")
        else:
            skills_manager = self.lifecycle.skills_manager

        try:
            skills_info = skills_manager.skills_info
            items: List[SkillItem] = []
            for skill in skills_info:
                items.append(
                    SkillItem(
                        id=str(skill.name),
                        name=str(skill.name),
                        description=str(skill.description),
                        enabled=bool(skill.enabled),
                        path=str(skill.path),
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

                # Extract the zip
                extract_dir = os.path.join(temp_dir, "extracted")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)

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