import asyncio
import shutil
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from uuid import uuid4

from fastapi import Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from core.plugin.manager import PLUGIN_CONFIG_DIR, PLUGIN_DATA_DIR, _compare_versions
from core.logging_manager import get_logger
from core.plugin.plugin_installer import (
    MAX_PLUGIN_ARCHIVE_BYTES,
    PluginAlreadyInstalledError,
    install_from_github,
    install_from_zip,
    install_requirements,
)
from core.plugin.store import PluginStore, StoreSource, extract_plugins
from webui.models import (
    PageMenu, PluginConfigUpdateRequest, PluginInstallGithubRequest, PluginInstallResult, PluginInstallTask, PluginItem,
    PluginUpdateCheckItem, PluginUpdateRequest,
)
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes
from webui.utils import schema_to_dict

logger = get_logger("webui", "blue")
MAX_RETAINED_INSTALL_TASKS = 20


class PluginsRoutes(Routes):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._install_tasks: Dict[str, Dict[str, Any]] = {}
        self._plugin_install_lock = asyncio.Lock()

    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/plugins",
                methods=["GET"],
                endpoint=self.list_plugins,
                response_model=List[PluginItem],
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}/icon",
                methods=["GET"],
                endpoint=self.get_plugin_icon,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}/menu-icon/{page_route:path}",
                methods=["GET"],
                endpoint=self.get_plugin_menu_icon,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}/config",
                methods=["GET"],
                endpoint=self.get_plugin_config,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}/config",
                methods=["PUT"],
                endpoint=self.update_plugin_config,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}/enabled",
                methods=["POST"],
                endpoint=self.set_plugin_enabled,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}/reload",
                methods=["POST"],
                endpoint=self.reload_plugin,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}/readme",
                methods=["GET"],
                endpoint=self.get_plugin_readme,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}",
                methods=["DELETE"],
                endpoint=self.delete_plugin,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/install/github",
                methods=["POST"],
                endpoint=self.install_from_github,
                response_model=PluginInstallResult,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/install/upload",
                methods=["POST"],
                endpoint=self.install_from_upload,
                response_model=PluginInstallResult,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/install/github/tasks",
                methods=["POST"],
                endpoint=self.start_github_install_task,
                response_model=PluginInstallTask,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/install/tasks/active",
                methods=["GET"],
                endpoint=self.get_active_install_task,
                response_model=Optional[PluginInstallTask],
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/install/tasks/{task_id}",
                methods=["GET"],
                endpoint=self.get_install_task,
                response_model=PluginInstallTask,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/install/tasks/{task_id}/cancel",
                methods=["POST"],
                endpoint=self.cancel_install_task,
                response_model=PluginInstallTask,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/updates/check",
                methods=["POST"],
                endpoint=self.check_plugin_updates,
                response_model=List[PluginUpdateCheckItem],
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}/update",
                methods=["POST"],
                endpoint=self.update_plugin,
                response_model=PluginInstallResult,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def list_plugins(self):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            return []
        try:
            plugin_manager = self.lifecycle.plugin_manager
            all_components = plugin_manager.get_plugin_components()
            items: List[PluginItem] = []
            for info in plugin_manager.list_plugins():
                if info.hidden:
                    continue
                pid = info.plugin_id
                # Collect menu entries from registered pages
                menus: List[PageMenu] = []
                comp = all_components.get(pid)
                if comp:
                    for page in comp.pages:
                        menu_cfg = page.get("menu")
                        if not menu_cfg:
                            continue
                        # A menu icon may reference an SVG file inside the
                        # plugin root; expose it through the menu-icon endpoint.
                        icon_value = menu_cfg.icon
                        if plugin_manager.get_page_menu_icon_path(pid, page["route"]):
                            icon_value = (
                                f"/api/plugins/{quote(pid, safe='')}"
                                f"/menu-icon/{page['route'].lstrip('/')}"
                            )
                        menus.append(PageMenu(
                            route=f"/page/plugin/{pid}/{page['route'].lstrip('/')}",
                            label=menu_cfg.label,
                            icon=icon_value,
                            order=menu_cfg.order,
                        ))
                    menus.sort(key=lambda m: m.order)
                items.append(
                    PluginItem(
                        id=pid,
                        name=info.display_name,
                        version=info.version,
                        author=info.author,
                        description=info.description,
                        repo=info.repo,
                        enabled=plugin_manager.is_plugin_enabled(pid),
                        builtin=info.builtin,
                        uninstallable=info.uninstallable,
                        locales=info.locales,
                        tags=info.tags,
                        core_version=info.core_version,
                        error=info.error,
                        status=info.status,
                        menus=menus,
                        icon=(
                            f"/api/plugins/{quote(pid, safe='')}/icon"
                            if info.icon else None
                        ),
                        icon_dark=(
                            f"/api/plugins/{quote(pid, safe='')}/icon?dark=true"
                            if info.icon_dark else None
                        ),
                    )
                )
            return items
        except Exception as e:
            logger.error(f"Failed to list plugins: {e}")
            raise HTTPException(status_code=500, detail="Failed to list plugins")

    async def get_plugin_icon(self, plugin_id: str, dark: bool = False):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=404, detail="Plugin manager not available")
        plugin_info = self.lifecycle.plugin_manager.get_plugin_info(plugin_id)
        icon_path = None
        if plugin_info:
            icon_path = plugin_info.icon_dark if dark else plugin_info.icon
        if not icon_path:
            raise HTTPException(status_code=404, detail="Plugin icon not found")
        return FileResponse(icon_path, headers={"Cache-Control": "no-cache"})

    async def get_plugin_menu_icon(self, plugin_id: str, page_route: str):
        """Serve the sidebar menu icon file of a plugin page.

        Only SVG files can resolve as menu icons.  The file path is looked up
        from the page's registered menu config, so the URL itself never
        carries a filesystem path.
        """
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=404, detail="Plugin manager not available")
        plugin_manager = self.lifecycle.plugin_manager
        icon_path = plugin_manager.get_page_menu_icon_path(plugin_id, page_route)
        if not icon_path:
            raise HTTPException(status_code=404, detail="Plugin menu icon not found")
        # Pin the media type: guessing from the file suffix can pick up a
        # wrong .svg mapping from the Windows registry.
        return FileResponse(icon_path, media_type="image/svg+xml",
                            headers={"Cache-Control": "no-cache"})

    async def get_plugin_config(self, plugin_id: str):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")
        try:
            plugin_manager = self.lifecycle.plugin_manager
            if not plugin_manager.has_plugin(plugin_id):
                raise HTTPException(status_code=404, detail="Plugin not found")
            schema_fields = plugin_manager.get_plugin_schema(plugin_id) or []
            config = plugin_manager.get_plugin_config(plugin_id)
            return {"schema": schema_to_dict(schema_fields), "config": config}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get config for plugin {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to load plugin config")

    async def update_plugin_config(
        self,
        plugin_id: str,
        payload: PluginConfigUpdateRequest,
    ):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")
        try:
            plugin_manager = self.lifecycle.plugin_manager
            if not plugin_manager.has_plugin(plugin_id):
                raise HTTPException(status_code=404, detail="Plugin not found")
            updated_config = await plugin_manager.update_plugin_config(plugin_id, payload.config or {})
            schema_fields = plugin_manager.get_plugin_schema(plugin_id) or []
            return {"schema": schema_to_dict(schema_fields), "config": updated_config}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update config for plugin {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to save plugin config")

    async def get_plugin_readme(self, plugin_id: str):
        """Return the optional README from an installed plugin directory."""
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")

        plugin_manager = self.lifecycle.plugin_manager
        if not plugin_manager.has_plugin(plugin_id):
            raise HTTPException(status_code=404, detail="Plugin not found")

        plugin_dir = plugin_manager.get_plugin_module_path(plugin_id)
        if not plugin_dir:
            return {"readme": None}

        def read_readme() -> Optional[str]:
            for name in ("README.md", "README.MD", "README"):
                readme_path = plugin_dir / name
                if readme_path.is_file():
                    return readme_path.read_text(encoding="utf-8", errors="replace")[:1_000_000]
            return None

        try:
            return {"readme": await asyncio.to_thread(read_readme)}
        except OSError as e:
            logger.warning(f"Failed to read README for plugin {plugin_id}: {e}")
            return {"readme": None}

    async def set_plugin_enabled(self, plugin_id: str, payload: Dict):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")
        try:
            enabled = bool(payload.get("enabled"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid payload")
        try:
            plugin_manager = self.lifecycle.plugin_manager
            if not plugin_manager.has_plugin(plugin_id):
                raise HTTPException(status_code=404, detail="Plugin not found")
            if enabled and plugin_id in plugin_manager.get_plugin_load_errors():
                raise HTTPException(status_code=400, detail="Cannot enable a plugin that failed to load")
            await plugin_manager.set_plugin_enabled(plugin_id, enabled)
            return {"plugin_id": plugin_id, "enabled": enabled}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to set plugin enabled state for {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to update plugin state")

    async def reload_plugin(self, plugin_id: str):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")
        try:
            plugin_manager = self.lifecycle.plugin_manager
            if not plugin_manager.has_plugin(plugin_id):
                raise HTTPException(status_code=404, detail="Plugin not found")
            if plugin_manager.is_builtin_plugin(plugin_id):
                raise HTTPException(status_code=400, detail="Built-in plugins cannot be reloaded")
            await plugin_manager.reload(plugin_id)
            # Check if the plugin reloaded successfully
            if plugin_id in plugin_manager.get_registered_plugins():
                return {"plugin_id": plugin_id, "reloaded": True}
            # Plugin failed to reload — get the error
            errors = plugin_manager.get_plugin_load_errors()
            error_msg = errors.get(plugin_id, {}).get("error", "Unknown error")
            return {"plugin_id": plugin_id, "reloaded": False, "error": error_msg}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to reload plugin {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to reload plugin: {e}")

    async def delete_plugin(
        self,
        plugin_id: str,
        delete_config: bool = Query(False),
        delete_data: bool = Query(False),
    ):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")

        plugin_manager = self.lifecycle.plugin_manager

        if not plugin_manager.has_plugin(plugin_id):
            raise HTTPException(status_code=404, detail="Plugin not found")

        if not plugin_manager.is_plugin_uninstallable(plugin_id):
            raise HTTPException(status_code=400, detail="This built-in plugin cannot be deleted")

        plugin_dir = plugin_manager.get_plugin_module_path(plugin_id)
        if not plugin_dir:
            # Failed plugins may not have a registered path; try the plugins directory
            plugin_dir = plugin_manager.plugin_dir / plugin_id
            if not plugin_dir.exists():
                raise HTTPException(status_code=500, detail="Could not resolve plugin path")

        try:
            await plugin_manager.uninstall_plugin(plugin_id)
        except Exception as e:
            logger.error(f"Failed to uninstall plugin {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to uninstall plugin: {e}")

        try:
            shutil.rmtree(plugin_dir)
        except Exception as e:
            logger.error(f"Failed to delete plugin directory {plugin_dir}: {e}")
            raise HTTPException(status_code=500, detail=f"Plugin unregistered but directory deletion failed: {e}")

        if delete_config:
            config_file = PLUGIN_CONFIG_DIR / f"{plugin_id}.json"
            try:
                if config_file.exists():
                    config_file.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete plugin config {config_file}: {e}")

        if delete_data:
            data_dir = PLUGIN_DATA_DIR / plugin_id
            try:
                if data_dir.exists():
                    shutil.rmtree(data_dir)
            except Exception as e:
                logger.warning(f"Failed to delete plugin data {data_dir}: {e}")

        return {"plugin_id": plugin_id, "deleted": True}

    async def install_from_github(self, payload: PluginInstallGithubRequest) -> PluginInstallResult:
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")

        plugin_manager = self.lifecycle.plugin_manager
        async with self._plugin_install_guard():
            return await self._install_from_github_locked(payload, plugin_manager)

    async def _install_from_github_locked(
        self, payload: PluginInstallGithubRequest, plugin_manager
    ) -> PluginInstallResult:
        try:
            plugin_dir = await install_from_github(
                payload.repo_url,
                plugin_manager.plugin_dir,
                proxy=payload.proxy,
                gh_proxy=payload.gh_proxy,
                commit_sha=payload.commit_sha,
                is_plugin_installed=plugin_manager.has_plugin,
            )
        except PluginAlreadyInstalledError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except ConnectionError as e:
            raise HTTPException(status_code=422, detail=str(e))

        warnings = await install_requirements(plugin_dir, pypi_mirror=self._get_pypi_mirror())

        plugin_id = await plugin_manager.load_plugin_from_dir(plugin_dir)
        if not plugin_id:
            raise HTTPException(status_code=500, detail="Plugin files were installed but failed to load")

        return self._build_install_result(plugin_manager, plugin_id, warnings)

    async def start_github_install_task(self, payload: PluginInstallGithubRequest) -> PluginInstallTask:
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")
        self._ensure_plugin_install_available()

        task_id = uuid4().hex
        task_data: Dict[str, Any] = {
            "task_id": task_id,
            "repo_url": payload.repo_url,
            "commit_sha": payload.commit_sha,
            "status": "installing",
            "stage": "downloading",
            "plugin_id": None,
            "error": None,
            "warnings": [],
            "task": None,
        }
        self._install_tasks[task_id] = task_data
        task_data["task"] = asyncio.create_task(self._run_github_install_task(task_data, payload))
        return self._serialize_install_task(task_data)

    async def get_active_install_task(self) -> Optional[PluginInstallTask]:
        active = self._active_install_task()
        return self._serialize_install_task(active) if active else None

    async def get_install_task(self, task_id: str) -> PluginInstallTask:
        task_data = self._install_tasks.get(task_id)
        if not task_data:
            raise HTTPException(status_code=404, detail="Plugin installation task not found")
        return self._serialize_install_task(task_data)

    async def cancel_install_task(self, task_id: str) -> PluginInstallTask:
        task_data = self._install_tasks.get(task_id)
        if not task_data:
            raise HTTPException(status_code=404, detail="Plugin installation task not found")
        task = task_data.get("task")
        if task_data["status"] != "installing" or not task or task.done():
            return self._serialize_install_task(task_data)
        if task_data["stage"] == "loading":
            raise HTTPException(status_code=409, detail="Plugin installation can no longer be cancelled")
        task.cancel()
        return self._serialize_install_task(task_data)

    def _active_install_task(self) -> Optional[Dict[str, Any]]:
        return next(
            (task for task in self._install_tasks.values() if task["status"] == "installing"),
            None,
        )

    def _ensure_plugin_install_available(self) -> None:
        if self._plugin_install_lock.locked() or self._active_install_task():
            raise HTTPException(status_code=409, detail="Another plugin installation is already in progress")

    @asynccontextmanager
    async def _plugin_install_guard(self):
        self._ensure_plugin_install_available()
        async with self._plugin_install_lock:
            yield

    def _finish_install_task(self, task_data: Dict[str, Any], **values: Any) -> None:
        task_data.update(values)
        task_data["completed_at"] = time.monotonic()
        terminal_tasks = sorted(
            (task for task in self._install_tasks.values() if task["status"] != "installing"),
            key=lambda task: task.get("completed_at", 0),
        )
        for task in terminal_tasks[:-MAX_RETAINED_INSTALL_TASKS]:
            self._install_tasks.pop(task["task_id"], None)

    @staticmethod
    def _serialize_install_task(task_data: Dict[str, Any]) -> PluginInstallTask:
        return PluginInstallTask(**{
            key: value for key, value in task_data.items() if key not in {"task", "completed_at"}
        })

    async def _run_github_install_task(
        self, task_data: Dict[str, Any], payload: PluginInstallGithubRequest
    ) -> None:
        plugin_manager = self.lifecycle.plugin_manager
        async with self._plugin_install_lock:
            plugin_dir = None
            plugin_id = None
            try:
                plugin_dir = await install_from_github(
                    payload.repo_url,
                    plugin_manager.plugin_dir,
                    proxy=payload.proxy,
                    gh_proxy=payload.gh_proxy,
                    commit_sha=payload.commit_sha,
                    is_plugin_installed=plugin_manager.has_plugin,
                )
                task_data["stage"] = "installing_dependencies"
                warnings = await install_requirements(plugin_dir, pypi_mirror=self._get_pypi_mirror())
                task_data["stage"] = "loading"
                plugin_id = await plugin_manager.load_plugin_from_dir(plugin_dir)
                if not plugin_id:
                    raise RuntimeError("Plugin files were installed but failed to load")
                self._finish_install_task(
                    task_data,
                    status="completed",
                    stage="completed",
                    plugin_id=plugin_id,
                    warnings=warnings,
                )
            except asyncio.CancelledError:
                if plugin_dir and plugin_dir.exists():
                    if plugin_id:
                        await plugin_manager.uninstall_plugin(plugin_id)
                    await asyncio.to_thread(shutil.rmtree, plugin_dir, ignore_errors=True)
                self._finish_install_task(task_data, status="cancelled", stage="cancelled")
                raise
            except PluginAlreadyInstalledError as e:
                self._finish_install_task(task_data, status="failed", stage="failed", error=str(e))
            except (ValueError, ConnectionError, IOError) as e:
                self._finish_install_task(task_data, status="failed", stage="failed", error=str(e))
            except Exception as e:
                logger.exception("Background plugin installation failed")
                self._finish_install_task(task_data, status="failed", stage="failed", error=str(e))

    async def install_from_upload(self, file: UploadFile = File(...)) -> PluginInstallResult:
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")

        if not file.filename or not file.filename.endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip files are accepted")

        plugin_manager = self.lifecycle.plugin_manager

        zip_bytes = await file.read(MAX_PLUGIN_ARCHIVE_BYTES + 1)
        if len(zip_bytes) > MAX_PLUGIN_ARCHIVE_BYTES:
            raise HTTPException(status_code=413, detail="Plugin archive exceeds the 50 MiB size limit")
        async with self._plugin_install_guard():
            return await self._install_from_upload_locked(zip_bytes, plugin_manager)

    async def _install_from_upload_locked(self, zip_bytes: bytes, plugin_manager) -> PluginInstallResult:
        try:
            plugin_dir = await install_from_zip(
                zip_bytes,
                plugin_manager.plugin_dir,
                is_plugin_installed=plugin_manager.has_plugin,
            )
        except PluginAlreadyInstalledError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except (ValueError, IOError) as e:
            raise HTTPException(status_code=422, detail=str(e))

        warnings = await install_requirements(plugin_dir, pypi_mirror=self._get_pypi_mirror())

        plugin_id = await plugin_manager.load_plugin_from_dir(plugin_dir)
        if not plugin_id:
            raise HTTPException(status_code=500, detail="Plugin files were installed but failed to load")

        return self._build_install_result(plugin_manager, plugin_id, warnings)

    def _get_pypi_mirror(self) -> Optional[str]:
        config = getattr(self.lifecycle, "kira_config", None)
        if not config:
            return None
        return (config.get("network") or {}).get("pypi_mirror") or None

    @staticmethod
    def _build_install_result(plugin_manager, plugin_id: str, warnings: List[str]) -> PluginInstallResult:
        info = plugin_manager.get_plugin_info(plugin_id)
        return PluginInstallResult(
            id=plugin_id,
            name=info.display_name if info else plugin_id,
            version=info.version if info else "",
            author=info.author if info else "",
            description=info.description if info else "",
            repo=info.repo if info else None,
            enabled=plugin_manager.is_plugin_enabled(plugin_id),
            tags=info.tags if info else [],
            core_version=info.core_version if info else None,
            error=info.error if info else None,
            status=info.status if info else "pending",
            icon=(f"/api/plugins/{quote(plugin_id, safe='')}/icon" if info and info.icon else None),
            icon_dark=(
                f"/api/plugins/{quote(plugin_id, safe='')}/icon?dark=true"
                if info and info.icon_dark else None
            ),
            warnings=warnings,
        )

    async def check_plugin_updates(self) -> List[PluginUpdateCheckItem]:
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            return []

        plugin_manager = self.lifecycle.plugin_manager
        db_service = getattr(self.lifecycle, "db_service", None)

        # Get store version map from the current store source (with 10-min cache)
        store_versions: Dict[str, tuple[str, Optional[str]]] = {}
        store_fetch_error: Optional[str] = None
        if db_service:
            try:
                sources = await db_service.list_plugin_store_sources()
                current = next((s for s in sources if s.get("is_current")), None)
                if current and current.get("url"):
                    fetched = await PluginStore(StoreSource.from_record(current)).fetch(
                        persist_cache=True,
                        strict_cache=True,
                    )
                    if fetched.cache_file is not None:
                        await db_service.update_plugin_store_source(
                            current["id"], cache_file=fetched.cache_file, updated_at=fetched.updated_at,
                        )

                    for item in extract_plugins(fetched.data):
                        if item.version and item.id:
                            store_versions[item.id] = (item.version, item.commit_sha)
            except Exception as e:
                store_fetch_error = f"Failed to fetch store data: {e}"
                logger.warning(store_fetch_error)

        results: List[PluginUpdateCheckItem] = []
        for info in plugin_manager.list_plugins():
            if info.builtin or info.hidden or info.status == "error":
                continue

            pid = info.plugin_id
            installed_ver = info.version
            latest_ver: Optional[str] = None
            commit_sha: Optional[str] = None
            err: Optional[str] = None

            if pid in store_versions:
                store_ver, store_commit_sha = store_versions[pid]
                try:
                    if _compare_versions(installed_ver, store_ver):
                        latest_ver = store_ver
                        commit_sha = store_commit_sha
                except Exception as e:
                    err = str(e)
            elif store_fetch_error:
                err = store_fetch_error

            results.append(PluginUpdateCheckItem(
                plugin_id=pid,
                current_version=installed_ver,
                latest_version=latest_ver,
                commit_sha=commit_sha,
                has_update=latest_ver is not None,
                error=err,
            ))

        return results

    async def update_plugin(self, plugin_id: str, payload: PluginUpdateRequest) -> PluginInstallResult:
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")

        plugin_manager = self.lifecycle.plugin_manager
        async with self._plugin_install_guard():
            return await self._update_plugin_locked(plugin_id, payload, plugin_manager)

    async def _update_plugin_locked(
        self, plugin_id: str, payload: PluginUpdateRequest, plugin_manager
    ) -> PluginInstallResult:
        info = plugin_manager.get_plugin_info(plugin_id)
        if not info:
            raise HTTPException(status_code=404, detail="Plugin not found")
        if info.builtin:
            raise HTTPException(status_code=400, detail="Built-in plugins cannot be updated")
        if not info.repo:
            raise HTTPException(status_code=400, detail="Plugin has no repo URL configured")

        plugin_dir = plugin_manager.get_plugin_module_path(plugin_id)
        if not plugin_dir:
            raise HTTPException(status_code=500, detail="Could not resolve installed plugin directory")

        try:
            plugin_dir = await install_from_github(
                info.repo,
                plugin_manager.plugin_dir,
                gh_proxy=payload.gh_proxy,
                commit_sha=payload.commit_sha,
                target_dir=plugin_dir,
                expected_plugin_id=plugin_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except ConnectionError as e:
            raise HTTPException(status_code=422, detail=str(e))

        warnings = await install_requirements(plugin_dir, pypi_mirror=self._get_pypi_mirror())

        await plugin_manager.prepare_plugin_reload(plugin_id)

        new_plugin_id = await plugin_manager.load_plugin_from_dir(plugin_dir)
        if not new_plugin_id:
            raise HTTPException(status_code=500, detail="Plugin files were installed but failed to load after update")
        if new_plugin_id != plugin_id:
            raise HTTPException(
                status_code=500,
                detail=f"Plugin identity changed after update: requested '{plugin_id}' but loaded '{new_plugin_id}'",
            )

        return self._build_install_result(plugin_manager, new_plugin_id, warnings)
