import os
import re
import json
import shutil
import asyncio
import posixpath
import subprocess
import signal
from dataclasses import dataclass, field
from time import monotonic
from uuid import uuid4

from pathlib import Path

from core.plugin import BasePlugin, logger, on, Priority, register
from core.chat import KiraMessageBatchEvent, MessageChain
from core.chat.message_elements import Image, Text
from core.provider import LLMRequest
from core.agent.tool import ToolResult

from core.utils.common_utils import desc_img
from core.utils.image_compression import compress_image_file
from core.utils.media_refs import store_session_media
from core.utils.path_utils import get_config_path, get_data_path, get_root_path

PLUGIN_ID = "agent"
# Plugin id used before this plugin was renamed from "file" to "agent"
LEGACY_PLUGIN_ID = "file"

# Session permission modes, mirroring the chat adapters
ALLOW_LIST = "allow_list"
DENY_LIST = "deny_list"

# Flat pre-section config keys mapped to their (section, key) location. Only keys
# the plugin ever read are listed; "extra_paths" held a nested object instead, so
# it is reshaped separately.
LEGACY_KEY_LOCATIONS = {
    "enabled_tools": ("tools", "enabled_tools"),
    "allowed_sessions": ("file_access", "session_list"),
    "allowed_exec_sessions": ("exec_access", "session_list"),
    "exec_deny_list": ("exec_access", "command_deny_list"),
    "exec_timeout": ("exec_access", "timeout"),
    "background_exec_timeout": ("exec_access", "background_timeout"),
    "background_exec_wait_seconds": ("exec_access", "background_wait_seconds"),
}
LEGACY_EXTRA_PATH_KEYS = ("extra_read_paths", "extra_write_paths")

restricted_paths = ['~/.ssh/', '~/.gnupg/', '~/.aws/', '~/.config/gh/', '.pem',
                    '.p12', 'key', 'secret', 'password', 'token', 'credential']

blocked_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg',
                      '.mp3', '.mp4', '.wav', '.ogg', '.flac', '.aac', '.silk', '.slk',
                      '.slac', '.amr', '.avi', '.mkv', '.mov', '.flv', '.wmv',
                      '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.exe', '.bin',
                      '.dll', '.so', '.dylib', '.pdf', '.doc', '.docx', '.xls', '.xlsx',
                      '.ppt', '.pptx', '.iso', '.img', '.dmg'}

# Raster image formats read_file can serve to the LLM (compression and VLM
# both handle these). SVG stays blocked: it is text-based and neither the
# image compressor nor vision models treat it as a raster image.
readable_image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}

ALL_TOOL_NAMES = [
    "read_file", "write_file", "edit_file", "list_files", "grep", "search_files",
    "exec", "manage_background_exec",
]
PROCESS_TERMINATION_GRACE_SECONDS = 5


@dataclass
class BackgroundExecTask:
    task_id: str
    session: str
    work_dir: Path
    timeout: int
    started_at: float = field(default_factory=monotonic)
    output_chunks: list[str] = field(default_factory=list)
    process: asyncio.subprocess.Process | None = None
    execution_task: asyncio.Task[str] | None = None
    status: str = "starting"
    stop_requested: bool = False
    notify_on_completion: bool = False


class AgentPlugin(BasePlugin):
    """
    AgentPlugin

    Gives the AI agent-style access to the local environment: file operations
    and shell command execution, both guarded by session and path permissions.
    """
    
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.file_permission_mode = ALLOW_LIST
        self.file_sessions = list()
        self.exec_permission_mode = ALLOW_LIST
        self.exec_sessions = list()
        self.exec_command_deny_list = list()
        self.allowed_read_paths = tuple()
        self.allowed_write_paths = tuple()

        self._exec_timeout = 30
        self._background_exec_timeout = 300
        self._background_exec_wait_seconds = 2
        self._background_exec_tasks: dict[str, BackgroundExecTask] = {}
        self._background_notice_tasks: set[asyncio.Task] = set()

    async def initialize(self):
        self._migrate_legacy_config()

        file_access = self._config_section("file_access")
        exec_access = self._config_section("exec_access")

        self.file_permission_mode = self._permission_mode(file_access, "file_access")
        self.file_sessions = self._session_list(file_access)
        self.exec_permission_mode = self._permission_mode(exec_access, "exec_access")
        self.exec_sessions = self._session_list(exec_access)
        self.exec_command_deny_list = list(exec_access.get("command_deny_list") or [])

        self._exec_timeout = self._get_positive_int_config("exec_access.timeout", 30)
        self._background_exec_timeout = self._get_positive_int_config(
            "exec_access.background_timeout", 300
        )
        self._background_exec_wait_seconds = self._get_positive_int_config(
            "exec_access.background_wait_seconds", 2
        )
        base_read = ["data/files", "data/temp", "data/skills"]
        base_write = ["data/files", "data/temp"]
        extra_read = file_access.get("extra_read_paths") or []
        extra_write = file_access.get("extra_write_paths") or []
        self.allowed_read_paths = tuple(base_read + list(extra_read))
        self.allowed_write_paths = tuple(base_write + list(extra_write))

    def _config_section(self, key: str) -> dict:
        """Return a config section, empty when it is missing or malformed."""
        section = self.plugin_cfg.get(key)
        if section is None:
            return {}
        if not isinstance(section, dict):
            logger.warning(f"Invalid {key} section in plugin config; using defaults")
            return {}
        return section

    def _config_section_for_write(self, key: str) -> dict:
        """Return a config section to write into, creating it when needed."""
        section = self.plugin_cfg.get(key)
        if not isinstance(section, dict):
            section = {}
            self.plugin_cfg[key] = section
        return section

    def _permission_mode(self, section: dict, label: str) -> str:
        """Read the session permission mode of a config section.

        Only an explicit ``deny_list`` switches a section to deny semantics;
        anything else falls back to ``allow_list`` so that an unreadable value
        can never open a capability up.
        """
        value = str(section.get("permission_mode", ALLOW_LIST)).strip().lower()
        if value == DENY_LIST:
            return DENY_LIST
        if value != ALLOW_LIST:
            logger.warning(
                f"Invalid {label}.permission_mode in plugin config; using {ALLOW_LIST}"
            )
        return ALLOW_LIST

    @staticmethod
    def _session_list(section: dict) -> list[str]:
        """Read a session list from a config section, dropping malformed entries.

        Session ids are compared as strings, so numeric ids coming from the WebUI
        are normalized here.
        """
        value = section.get("session_list")
        if not isinstance(value, list):
            return []
        sessions = []
        for entry in value:
            if isinstance(entry, bool) or not isinstance(entry, (str, int)):
                continue
            text = str(entry).strip()
            if text:
                sessions.append(text)
        return sessions

    @staticmethod
    def _session_allowed(session_id: str, mode: str, sessions: list) -> bool:
        """Apply the allow_list / deny_list semantics of a session permission.

        Mirrors the chat adapters: ``allow_list`` grants only the listed
        sessions, ``deny_list`` grants every session except the listed ones.
        """
        listed = str(session_id) in sessions
        return listed if mode == ALLOW_LIST else not listed

    def _is_file_session_allowed(self, session_id: str) -> bool:
        return self._session_allowed(
            session_id, self.file_permission_mode, self.file_sessions
        )

    def _is_exec_session_allowed(self, session_id: str) -> bool:
        return self._session_allowed(
            session_id, self.exec_permission_mode, self.exec_sessions
        )

    def _migrate_legacy_config(self) -> bool:
        """Inherit and reshape plugin config that was written in an older layout.

        Two older layouts can be on disk. ``file.json`` was written while this
        plugin was still called ``file``, and it holds flat keys. An intermediate
        build of the rename could also have written those flat keys into
        ``agent.json``. Both are folded into the current sectioned layout: the
        legacy file's values win over the freshly generated schema defaults, the
        legacy file is deleted once, and only once, the migrated config is safely
        on disk, which keeps later WebUI edits authoritative.
        """
        changed = False
        legacy_path = get_config_path() / "plugins" / f"{LEGACY_PLUGIN_ID}.json"
        legacy_cfg = self._read_legacy_config(legacy_path)
        if legacy_cfg is not None:
            self.plugin_cfg.update(legacy_cfg)
            changed = True

        if self._reshape_flat_config():
            changed = True

        if not changed:
            return False

        if not self._persist_config():
            # Keep the legacy file so the settings are never lost on a failed write
            if legacy_cfg is not None:
                logger.error(
                    f"Kept {legacy_path.name}: migrated settings could not be persisted "
                    f"to the {PLUGIN_ID} plugin config"
                )
            else:
                logger.error(f"Failed to write the reshaped {PLUGIN_ID} plugin config")
            return False

        if legacy_cfg is not None:
            try:
                legacy_path.unlink()
            except OSError as e:
                logger.warning(f"Failed to remove migrated legacy config {legacy_path}: {e}")
            logger.info(
                f"Migrated {len(legacy_cfg)} setting(s) from {legacy_path.name} "
                f"into the {PLUGIN_ID} plugin config"
            )
        return True

    @staticmethod
    def _read_legacy_config(legacy_path: Path) -> dict | None:
        """Read a legacy config file, or return None when there is nothing usable."""
        if not legacy_path.exists():
            return None

        try:
            with legacy_path.open("r", encoding="utf-8") as f:
                legacy_cfg = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read legacy plugin config {legacy_path}: {e}")
            return None

        if not isinstance(legacy_cfg, dict):
            logger.warning(f"Ignoring legacy plugin config {legacy_path}: not a JSON object")
            return None

        return legacy_cfg

    def _reshape_flat_config(self) -> bool:
        """Move flat pre-section keys into their config section, in place.

        Returns True when something moved. The flat keys are dropped from the top
        level and the result is persisted right away, so the reshape happens once
        and a stale flat key can never shadow a later WebUI edit.
        """
        moved = False
        for legacy_key, (section_key, field_key) in LEGACY_KEY_LOCATIONS.items():
            if legacy_key not in self.plugin_cfg:
                continue
            value = self.plugin_cfg.pop(legacy_key)
            self._config_section_for_write(section_key)[field_key] = value
            moved = True

        extra_paths = self.plugin_cfg.get("extra_paths")
        if isinstance(extra_paths, dict):
            target = self._config_section_for_write("file_access")
            for key in LEGACY_EXTRA_PATH_KEYS:
                if key in extra_paths:
                    target[key] = extra_paths[key]
            del self.plugin_cfg["extra_paths"]
            moved = True
        elif extra_paths is not None:
            logger.warning("Ignoring extra_paths in plugin config: not a JSON object")

        return moved

    def _persist_config(self) -> bool:
        """Write the in-memory plugin config back to the plugin config file.

        ``self.plugin_cfg`` is the same dict the plugin registry keeps in memory,
        so the WebUI reads the migrated state without a reload.
        """
        config_path = get_config_path() / "plugins" / f"{PLUGIN_ID}.json"
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(self.plugin_cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to persist migrated {PLUGIN_ID} plugin config: {e}")
            return False
        return True

    def _get_positive_int_config(self, key: str, default: int) -> int:
        """Read a positive int from the plugin config.

        ``key`` is dotted (``"exec_access.timeout"``) because int settings live
        inside a config section.
        """
        section_key, _, field_key = key.partition(".")
        value = self._config_section(section_key).get(field_key)
        if isinstance(value, bool):
            value = None
        else:
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = None

        if value is not None and value > 0:
            return value

        logger.warning(f"Invalid {key} value; using default of {default} seconds")
        return default

    @on.llm_request(priority=Priority.LOW)
    async def filter_tools(self, event: KiraMessageBatchEvent, req: LLMRequest, *_):
        tools_cfg = self.plugin_cfg.get("tools")
        enabled = tools_cfg.get("enabled_tools") if isinstance(tools_cfg, dict) else None
        if enabled is None:
            enabled = ALL_TOOL_NAMES
        enabled = set(enabled)
        if "exec" in enabled:
            enabled.add("manage_background_exec")
        else:
            enabled.discard("manage_background_exec")
        disabled = set(ALL_TOOL_NAMES) - enabled
        if disabled:
            req.tool_set.remove(*disabled)

    async def terminate(self):
        background_tasks = list(self._background_exec_tasks.values())
        self._background_exec_tasks.clear()
        for background_task in background_tasks:
            background_task.stop_requested = True
            background_task.notify_on_completion = False
            await self._terminate_background_process(background_task.process)
            if background_task.execution_task is not None:
                background_task.execution_task.cancel()

        notice_tasks = list(self._background_notice_tasks)
        for notice_task in notice_tasks:
            notice_task.cancel()

        await asyncio.gather(
            *(task.execution_task for task in background_tasks if task.execution_task is not None),
            *notice_tasks,
            return_exceptions=True,
        )
        self._background_notice_tasks.clear()

    @staticmethod
    def _run_shell_command(
        shell_command: str,
        exec_timeout: int,
        env: dict[str, str],
        exec_work_dir: Path,
    ) -> str:
        try:
            result = subprocess.run(
                shell_command, shell=True, capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=exec_timeout, env=env, cwd=exec_work_dir,
                encoding='utf-8', errors='replace'
            )
            output = (result.stdout or '') + (result.stderr or '')
            if result.returncode == 0:
                return f'Shell command output:\n{output}'
            return f'Shell command failed (exit {result.returncode}):\n{output}'
        except subprocess.TimeoutExpired:
            return f'Shell command timed out after {exec_timeout} seconds: {shell_command}'
        except Exception as e:
            return f'Unexpected error while executing shell command: {e}'

    @staticmethod
    async def _read_background_output(
        stream: asyncio.StreamReader | None,
        background_task: BackgroundExecTask,
    ):
        if stream is None:
            return
        while chunk := await stream.read(4096):
            background_task.output_chunks.append(chunk.decode("utf-8", errors="replace"))

    @staticmethod
    async def _terminate_background_process(process: asyncio.subprocess.Process | None):
        if process is None or process.returncode is not None:
            return

        try:
            if os.name == "nt":
                killer = await asyncio.create_subprocess_exec(
                    "taskkill", "/PID", str(process.pid), "/T", "/F",
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(killer.wait(), timeout=PROCESS_TERMINATION_GRACE_SECONDS)
                if killer.returncode != 0 and process.returncode is None:
                    logger.warning(
                        f"taskkill failed for background process {process.pid} "
                        f"with exit code {killer.returncode}; killing the shell process"
                    )
                    process.kill()
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError, asyncio.TimeoutError):
            if process.returncode is None:
                process.kill()

        try:
            await asyncio.wait_for(process.wait(), timeout=PROCESS_TERMINATION_GRACE_SECONDS)
        except asyncio.TimeoutError:
            if os.name == "nt":
                logger.warning(
                    f"Background process {process.pid} did not exit after taskkill; killing the shell process"
                )
                if process.returncode is None:
                    process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
            await process.wait()

    async def _run_background_shell_command(
        self,
        shell_command: str,
        background_task: BackgroundExecTask,
        env: dict[str, str],
    ) -> str:
        process_kwargs = {}
        if os.name == "nt":
            process_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            process_kwargs["start_new_session"] = True

        try:
            process = await asyncio.create_subprocess_shell(
                shell_command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=background_task.work_dir,
                env=env,
                **process_kwargs,
            )
            background_task.process = process
            background_task.status = "running"
            readers = [
                asyncio.create_task(self._read_background_output(process.stdout, background_task)),
                asyncio.create_task(self._read_background_output(process.stderr, background_task)),
            ]

            timed_out = False
            try:
                if background_task.stop_requested:
                    await self._terminate_background_process(process)
                else:
                    try:
                        await asyncio.wait_for(process.wait(), timeout=background_task.timeout)
                    except asyncio.TimeoutError:
                        timed_out = True
                        background_task.status = "timed_out"
                        await self._terminate_background_process(process)
            finally:
                await asyncio.gather(*readers, return_exceptions=True)

            output = "".join(background_task.output_chunks)
            if background_task.stop_requested:
                background_task.status = "stopped"
                return f"Shell command stopped by request:\n{output}"
            if timed_out:
                return (
                    f"Shell command timed out after {background_task.timeout} seconds: "
                    f"{shell_command}"
                )
            if process.returncode == 0:
                background_task.status = "completed"
                return f"Shell command output:\n{output}"
            background_task.status = "failed"
            return f"Shell command failed (exit {process.returncode}):\n{output}"
        except Exception as e:
            background_task.status = "failed"
            return f"Unexpected error while executing shell command: {e}"

    async def _stop_background_task(self, background_task: BackgroundExecTask):
        background_task.stop_requested = True
        background_task.notify_on_completion = False
        if background_task.process is not None:
            await self._terminate_background_process(background_task.process)

    async def _publish_background_exec_result(
        self,
        task_id: str,
        session: str,
        status: str,
        task: asyncio.Task[str],
    ):
        try:
            result = task.result()
        except asyncio.CancelledError:
            result = "Shell command was cancelled"
        except Exception as e:
            result = f"Unexpected error while executing shell command: {e}"

        try:
            status_text = {
                "completed": "completed",
                "timed_out": "timed out",
                "failed": "failed",
            }.get(status, "finished")
            message = f"Background shell command {status_text} (task_id: {task_id}):\n{result}"
            await self.ctx.publish_notice(
                session,
                MessageChain([Text(message)]),
                is_mentioned=True,
            )
        except Exception as e:
            logger.error(f"Failed to publish background shell command result for task {task_id}: {e}")

    def _on_background_exec_done(self, task_id: str, session: str, task: asyncio.Task[str]):
        background_task = self._background_exec_tasks.pop(task_id, None)
        if background_task is None or not background_task.notify_on_completion:
            return
        notice_task = asyncio.create_task(
            self._publish_background_exec_result(
                task_id,
                session,
                background_task.status,
                task,
            ),
            name=f"file_exec_notice_{task_id}",
        )
        self._background_notice_tasks.add(notice_task)
        notice_task.add_done_callback(self._background_notice_tasks.discard)

    def _is_path_allowed(self, path: str, allowed_prefixes: tuple) -> bool:
        """Check if path starts with an allowed prefix directory."""
        for prefix in allowed_prefixes:
            prefix = self._normalize_path(prefix)
            if prefix is None:
                continue
            prefix = prefix.rstrip('/')
            if path == prefix or path.startswith(prefix + '/'):
                return True
        return False

    @staticmethod
    def _resolve_path(path: str) -> Path:
        if path.startswith("data/"):
            return get_data_path() / path.removeprefix("data/")
        return Path(path)

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized = path.replace("\\", "/")
        normalized = posixpath.normpath(normalized)
        if normalized.startswith("../") or normalized == "..":
            return None
        return normalized

    @staticmethod
    def _read_file_lines(path: Path) -> list[str]:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)

    @staticmethod
    def _read_file_text(path: Path) -> str:
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _write_file_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _list_directory(path: Path) -> list[str]:
        return sorted(os.listdir(path))

    @staticmethod
    def _find_files(path: Path, pattern: str) -> list[Path]:
        matches = path.glob(pattern)
        return sorted(
            (match for match in matches if match.is_file()),
            key=lambda match: match.stat().st_mtime,
            reverse=True,
        )

    @register.tool(
        "read_file",
        "Read a plain text file (txt, html, py, etc..) or an image file (jpg, png, gif, etc..) in allowed read paths. Images follow the configured image processing mode: returned as raw image data attached to this result in native multimodal mode, or as a text description in VLM description mode.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path, must start with an allowed path prefix"},
                "offset": {"type": "integer", "description": "Which line to start reading, defaults to 1. Ignored for image files."},
                "limit": {"type": "integer", "description": "Maximum lines to read, defaults to 200. Ignored for image files."},
            },
            "required": ["path"]
        }
    )
    async def read_file(self, event: KiraMessageBatchEvent, path: str, offset: int = 1, limit: int = 200) -> str | ToolResult:
        if not self._is_file_session_allowed(event.sid):
            return "Permission denied: current session not allowed to access local files"

        path = self._normalize_path(path)
        if path is None:
            return "Permission denied: Path traversal detected"

        for rp in restricted_paths:
            if rp in path:
                return "Permission denied: Path contains restricted keywords"

        if not self._is_path_allowed(path, self.allowed_read_paths):
            return f"Permission denied: Path must start with one of: {', '.join(self.allowed_read_paths)}"

        ext = Path(path).suffix.lower()
        if ext in blocked_extensions:
            if ext not in readable_image_extensions:
                return "Multimedia and binary files are not allowed"
            return await self._read_image_file(event, path)

        try:
            abs_path = self._resolve_path(path)
            file_lines = await asyncio.to_thread(self._read_file_lines, abs_path)
            if offset > len(file_lines) or offset < 1:
                return "Offset out of range"

            selected = file_lines[offset-1:offset-1+limit]

            start_line = offset
            end_line = offset + len(selected) - 1
            truncated = end_line < len(file_lines)

            read_result = "".join(selected)
            if truncated:
                read_result += f"\n[Showing lines {start_line}-{end_line}. Use offset={end_line+1} to continue if needed.]"

            return read_result
        except Exception as e:
            return f"[Failed to read file: {e}]"

    async def _read_image_file(self, event: KiraMessageBatchEvent, path: str) -> str | ToolResult:
        """Read an image file according to the image processing mode.

        Native multimodal mode attaches the (possibly compressed) image data as
        a media reference so the main LLM sees it directly; VLM description mode
        returns the transcribed description instead. Both paths honor the global
        image compression settings, mirroring how incoming chat images are
        bounded before reaching a model.
        """
        abs_path = self._resolve_path(path)
        if not abs_path.is_file():
            return f"[Failed to read file: file not found: {path}]"

        capabilities = self.ctx.get_session_capabilities(event.sid) if self.ctx else {}
        image_recognition = capabilities.get("image_recognition") if isinstance(capabilities, dict) else None
        if not isinstance(image_recognition, dict):
            image_recognition = {}
        mode = image_recognition.get("mode", "vlm_description")

        compression_config = (
            self.ctx.config.get_config("bot_config.image_compression", {}) if self.ctx else {}
        )
        try:
            image_path, mime = await compress_image_file(abs_path, compression_config)
        except Exception as e:
            return f"[Failed to read file: {e}]"

        if mode == "native":
            message_id = event.messages[-1].message_id if event.messages else "read_file"
            media_ref = await store_session_media(
                Image(image=str(image_path), mime=mime), event.sid, message_id
            )
            return ToolResult(
                text=f"Image file: {path} ({mime}). The raw image data is attached as an image content part.",
                media_refs=[media_ref],
            )

        desc = await self._describe_image_file(image_path, mime, image_recognition)
        if not desc:
            return f"[Image description unavailable, file_path: {path}]"
        return f"[Image {desc}, file_path: {path}]"

    async def _describe_image_file(self, image_path: Path, mime: str, image_recognition: dict) -> str:
        """Transcribe an image file with the default VLM, reusing the shared description cache."""
        if not image_recognition.get("enabled", True):
            return ""

        desc_cache = None
        md5 = None
        try:
            from core.message_manager import ImageDescCache

            desc_cache = ImageDescCache(self.ctx.db)
            md5 = await Image(image=str(image_path), mime=mime).hash_image()
            cached_desc = await desc_cache.get(md5)
            if cached_desc:
                return cached_desc
        except Exception as e:
            logger.warning(f"Failed to read image desc cache for read_file: {e}")
            desc_cache = None

        desc = ""
        try:
            vlm_client = self.ctx.provider_mgr.get_default_vlm()
            desc = await desc_img(
                client=vlm_client,
                image=Image(image=str(image_path), mime=mime),
                prompt=str(image_recognition.get("desc_prompt", "") or "").strip() or None,
                lang=self.ctx.get_lang(),
            )
        except Exception as e:
            logger.error(f"Failed to describe image file for read_file: {e}")

        if desc and desc_cache and md5:
            try:
                await desc_cache.set(md5, desc)
            except Exception as e:
                logger.warning(f"Failed to cache read_file image desc: {e}")
        return desc

    @register.tool(
        "write_file",
        "Write content to a plain text file in allowed write paths. Creates the file if it doesn't exist, overwrites if it does.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path, must start with an allowed path prefix"},
                "content": {"type": "string", "description": "Content to write to the file"},
            },
            "required": ["path", "content"]
        }
    )
    async def write_file(self, event: KiraMessageBatchEvent, path: str, content: str) -> str:
        if not self._is_file_session_allowed(event.sid):
            return "Permission denied: current session not allowed to access local files"

        path = self._normalize_path(path)
        if path is None:
            return "Permission denied: Path traversal detected"

        for rp in restricted_paths:
            if rp in path:
                return "Permission denied: Path contains restricted keywords"

        if not self._is_path_allowed(path, self.allowed_write_paths):
            return f"Permission denied: Path must start with one of: {', '.join(self.allowed_write_paths)}"

        ext = Path(path).suffix.lower()
        if ext in blocked_extensions:
            return "Multimedia and binary files are not allowed"

        try:
            abs_path = self._resolve_path(path)
            await asyncio.to_thread(self._write_file_text, abs_path, content)
            return "File written successfully"
        except Exception as e:
            return f"Failed to write file: {e}"

    @register.tool(
        "edit_file",
        "Edit a plain text file by replacing exact text. The oldText must match exactly (including whitespace). Better use this tool when you only want to modify or add a part of content to a file instead of using `write_file` to re-write the entire file",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path, must start with an allowed path prefix"},
                "old_text": {"type": "string",
                             "description": "Exact text to find and replace (must match exactly, including whitespace)"},
                "new_text": {"type": "string", "description": "New text to replace the old text with"},
            },
            "required": ["path", "old_text", "new_text"]
        }
    )
    async def edit_file(self, event: KiraMessageBatchEvent, path: str, old_text: str, new_text: str) -> str:
        if not self._is_file_session_allowed(event.sid):
            return "Permission denied: current session not allowed to access local files"

        path = self._normalize_path(path)
        if path is None:
            return "Permission denied: Path traversal detected"

        for rp in restricted_paths:
            if rp in path:
                return "Permission denied: Path contains restricted keywords"

        if not self._is_path_allowed(path, self.allowed_write_paths):
            return f"Permission denied: Path must start with one of: {', '.join(self.allowed_write_paths)}"

        ext = Path(path).suffix.lower()
        if ext in blocked_extensions:
            return "Permission denied: Multimedia and binary files are not allowed"

        try:
            abs_path = self._resolve_path(path)
            content = await asyncio.to_thread(self._read_file_text, abs_path)

            if old_text == "":
                return "Error: old_text must not be empty."

            if old_text not in content:
                return "Error: old_text not found in file. Please check the content and try again."

            replacements = content.count(old_text)

            new_content = content.replace(old_text, new_text)

            await asyncio.to_thread(self._write_file_text, abs_path, new_content)
            return f"Successfully edited file: {path}, {replacements} replacement(s) made."
        except Exception as e:
            return f"Failed to edit file: {str(e)}"

    @register.tool(
        "list_files",
        "List files in a specified directory within allowed read paths",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path, must start with an allowed path prefix"},
                "offset": {"type": "integer", "description": "Which index to start displaying file or folder name, defaults to 1"},
                "limit": {"type": "integer", "description": "Maximum file count to display, defaults to 20"},
            },
            "required": ["path"]
        }
    )
    async def list_files(self, event: KiraMessageBatchEvent, path: str, offset: int = 1, limit: int = 20) -> str:
        if not self._is_file_session_allowed(event.sid):
            return "Permission denied: current session not allowed to access local files"

        path = self._normalize_path(path)
        if path is None:
            return "Permission denied: Path traversal detected"

        for rp in restricted_paths:
            if rp in path:
                return "Permission denied: Path contains restricted keywords"

        if not self._is_path_allowed(path, self.allowed_read_paths):
            return f"Permission denied: Path must start with one of: {', '.join(self.allowed_read_paths)}"

        try:
            abs_path = self._resolve_path(path)
            files = await asyncio.to_thread(self._list_directory, abs_path)

            if offset < 1 or offset > len(files):
                return "offset out of range"

            selected = files[offset - 1:offset - 1 + limit]

            start_index = offset
            end_index = offset + len(selected) - 1
            truncated = end_index < len(files)

            list_result = "\n".join(selected)
            if truncated:
                list_result += f"\n[Showing files of index {start_index}-{end_index}. Use offset={end_index + 1} to continue if needed.]"

            return list_result
        except Exception as e:
            return f"[Failed to list files: {e}]"

    # ------------------------------------------------------------------
    # grep / search_files helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_ripgrep() -> bool:
        return shutil.which("rg") is not None

    def _grep_guard(self, event: KiraMessageBatchEvent, path: str) -> tuple[str | None, str | None]:
        """Common permission guard for grep-like tools.

        Returns (normalized_path, None) on success or (None, error_message) on failure.
        """
        if not self._is_file_session_allowed(event.sid):
            return None, "Permission denied: current session not allowed to access local files"

        normalized = self._normalize_path(path)
        if normalized is None:
            return None, "Permission denied: Path traversal detected"

        for rp in restricted_paths:
            if rp in normalized:
                return None, "Permission denied: Path contains restricted keywords"

        if not self._is_path_allowed(normalized, self.allowed_read_paths):
            return None, f"Permission denied: Path must start with one of: {', '.join(self.allowed_read_paths)}"

        return normalized, None

    def _format_grep_results(self, lines: list[str], limit: int) -> str:
        """Trim results to limit and append truncation hint."""
        if limit > 0 and len(lines) > limit:
            lines = lines[:limit]
            result = "\n".join(lines)
            result += f"\n\n[Showing first {limit} results. Increase limit or narrow the search to see more.]"
            return result
        return "\n".join(lines) if lines else "No matches found."

    def _grep_with_rg(
        self,
        pattern: str,
        search_path: str,
        output_mode: str = "files_with_matches",
        context: int = 0,
        case_insensitive: bool = False,
        glob: str | None = None,
        multiline: bool = False,
        limit: int = 200,
    ) -> str:
        """Search file contents using ripgrep."""
        cmd = ["rg", "--no-heading", "--no-binary"]

        if output_mode == "files_with_matches":
            cmd.append("-l")
        elif output_mode == "count":
            cmd.append("--count")
        else:
            cmd.append("-n")
            if context > 0:
                cmd.extend(["-C", str(context)])

        if case_insensitive:
            cmd.append("-i")
        if multiline:
            cmd.extend(["-U", "--multiline-dotall"])
        if glob:
            cmd.extend(["--glob", glob])

        cmd.extend(["--", pattern, search_path])

        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=30,
                encoding="utf-8", errors="replace"
            )
            # rg exits 1 when no matches, 2 on error
            if result.returncode == 2:
                return f"ripgrep error: {result.stderr.strip()}"
            output = result.stdout.strip()
            if not output:
                return "No matches found."
            lines = output.splitlines()
            return self._format_grep_results(lines, limit)
        except subprocess.TimeoutExpired:
            return "Search timed out after 30 seconds."
        except Exception as e:
            return f"ripgrep execution failed: {e}"

    def _grep_with_python(
        self,
        pattern: str,
        search_path: str,
        original_path: str,
        output_mode: str = "files_with_matches",
        context: int = 0,
        case_insensitive: bool = False,
        glob: str | None = None,
        multiline: bool = False,
        limit: int = 200,
    ) -> str:
        """Search file contents using pure-Python re module."""
        if glob and ".." in glob:
            return "Error: glob pattern must not contain '..'"

        flags = re.IGNORECASE if case_insensitive else 0
        if multiline:
            flags |= re.DOTALL
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Invalid regex pattern: {e}"

        root = Path(search_path)
        if root.is_file():
            files = [root]
        elif root.is_dir():
            if glob:
                files = sorted(root.glob(glob), key=lambda p: p.stat().st_mtime, reverse=True)
            else:
                files = sorted(root.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        else:
            return f"Path not found: {search_path}"

        def _to_allowed_prefix(fp: Path) -> str:
            """Convert an absolute file path back to the user-facing allowed-prefix path."""
            rel_suffix = str(fp.relative_to(root)).replace("\\", "/")
            return f"{original_path.rstrip('/')}/{rel_suffix}"

        def _scan_file(fp: Path):
            """Scan a single file, returning (allowed_path, match_indices, total_matches) or None."""
            if not fp.is_file():
                return None
            if fp.suffix.lower() in blocked_extensions:
                return None
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return None

            if multiline:
                found = list(regex.finditer(content))
                if not found:
                    return None
                line_offsets = [0]
                for i, ch in enumerate(content):
                    if ch == "\n":
                        line_offsets.append(i + 1)
                indices = set()
                for m in found:
                    line_no = 0
                    for li, start in enumerate(line_offsets):
                        if start <= m.start():
                            line_no = li
                        else:
                            break
                    indices.add(line_no)
                return _to_allowed_prefix(fp), sorted(indices), len(found)
            else:
                file_lines = content.splitlines(keepends=True)
                indices = [i for i, line in enumerate(file_lines) if regex.search(line)]
                if not indices:
                    return None
                return _to_allowed_prefix(fp), indices, len(indices)

        lines: list[str] = []
        matched_files: list[str] = []
        file_count_map: dict[str, int] = {}

        for fp in files:
            scan_result = _scan_file(fp)
            if scan_result is None:
                continue
            rel, match_indices, count = scan_result
            matched_files.append(rel)
            file_count_map[rel] = count

            if output_mode == "content":
                content = fp.read_text(encoding="utf-8", errors="replace")
                file_lines = content.splitlines(keepends=True)
                shown: set[int] = set()
                for mi in match_indices:
                    start = max(0, mi - context)
                    end = min(len(file_lines), mi + context + 1)
                    for ci in range(start, end):
                        if ci not in shown:
                            shown.add(ci)
                            line_text = file_lines[ci].rstrip("\n\r")
                            marker = ":" if ci == mi else "-"
                            lines.append(f"{rel}:{ci + 1}{marker} {line_text}")

        if output_mode == "files_with_matches":
            lines = matched_files
            if not lines:
                return "No matches found."
            result = self._format_grep_results(lines, limit)
            if limit == 0 or len(matched_files) <= limit:
                result += f"\n\n[{len(matched_files)} files matched. Use output_mode=\"content\" to see matching lines.]"
            return result

        if output_mode == "count":
            lines = [f"{f}: {c}" for f, c in file_count_map.items()]
            if not lines:
                return "No matches found."
            return self._format_grep_results(lines, limit)

        # content mode
        if not lines:
            return "No matches found."
        total_matches = sum(file_count_map.values())
        result = self._format_grep_results(lines, limit)
        result += f"\n\n[{total_matches} matches across {len(matched_files)} files.]"
        return result

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @register.tool(
        "grep",
        (
            "Fast content search powered by ripgrep (with pure-Python fallback). "
            "Prefer this over reading files then searching manually. "
            "Supports regex patterns, glob filtering, context lines, and multiple output modes."
        ),
        {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The regex pattern to search for in file contents. Uses Python re syntax (ripgrep when available)."
                },
                "path": {
                    "type": "string",
                    "description": "File or directory path to search in. Must start with an allowed path prefix."
                },
                "output_mode": {
                    "type": "string",
                    "enum": ["files_with_matches", "content", "count"],
                    "description": "Output format. 'files_with_matches' (default) returns file paths only. 'content' returns matching lines with line numbers. 'count' returns match counts per file."
                },
                "context": {
                    "type": "integer",
                    "description": "Number of lines of context before and after each match. Only applies in 'content' mode. Defaults to 0."
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "If true, perform case-insensitive matching. Defaults to false."
                },
                "glob": {
                    "type": "string",
                    "description": "Glob pattern to filter which files to search (e.g. '*.py', '**/*.ts'). Searches all files if omitted."
                },
                "multiline": {
                    "type": "boolean",
                    "description": "If true, '.' in the pattern matches newlines and patterns can span multiple lines. Defaults to false."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of result lines to return. Defaults to 200. Use 0 for unlimited."
                },
            },
            "required": ["pattern", "path"]
        }
    )
    async def grep(
        self, event: KiraMessageBatchEvent, pattern: str, path: str,
        output_mode: str = "files_with_matches", context: int = 0,
        case_insensitive: bool = False, glob: str = None,
        multiline: bool = False, limit: int = 200,
    ) -> str:
        path, err = self._grep_guard(event, path)
        if err:
            return err

        abs_path = str(self._resolve_path(path))
        if not os.path.exists(abs_path):
            return f"Path not found: {path}"

        if self._has_ripgrep():
            return await asyncio.to_thread(
                self._grep_with_rg,
                pattern, abs_path, output_mode, context,
                case_insensitive, glob, multiline, limit,
            )
        else:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(
                        self._grep_with_python,
                        pattern, abs_path, path, output_mode, context,
                        case_insensitive, glob, multiline, limit,
                    ),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                return "Search timed out after 30 seconds."

    @register.tool(
        "search_files",
        (
            "Fast file search by glob pattern. Returns matching file paths sorted by modification time (most recent first). "
            "Use this to find files by name or extension, e.g. '**/*.py' or 'src/**/*.ts'. "
            "For searching file contents, use the grep tool instead."
        ),
        {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files. Examples: '**/*.py', 'src/**/*.ts', '*.json'. Use '**' to match any depth."
                },
                "path": {
                    "type": "string",
                    "description": "Directory path to search in. Must start with an allowed path prefix. Defaults to the first allowed read path."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of file paths to return. Defaults to 100."
                },
            },
            "required": ["pattern"]
        }
    )
    async def search_files(self, event: KiraMessageBatchEvent, pattern: str, path: str = None, limit: int = 100) -> str:
        if not self._is_file_session_allowed(event.sid):
            return "Permission denied: current session not allowed to access local files"

        if ".." in pattern:
            return "Error: glob pattern must not contain '..'"

        # Default to first allowed read path
        if path is None:
            if self.allowed_read_paths:
                path = self.allowed_read_paths[0]
            else:
                return "No allowed read paths configured"

        path = self._normalize_path(path)
        if path is None:
            return "Permission denied: Path traversal detected"

        for rp in restricted_paths:
            if rp in path:
                return "Permission denied: Path contains restricted keywords"

        if not self._is_path_allowed(path, self.allowed_read_paths):
            return f"Permission denied: Path must start with one of: {', '.join(self.allowed_read_paths)}"

        try:
            abs_path = self._resolve_path(path)
            if not abs_path.is_dir():
                return f"Not a directory: {path}"

            files = await asyncio.to_thread(self._find_files, abs_path, pattern)

            if not files:
                return "No files found."

            total = len(files)
            if limit > 0:
                files = files[:limit]

            rel_paths = []
            for f in files:
                rel_suffix = str(f.relative_to(abs_path)).replace("\\", "/")
                rel = f"{path.rstrip('/')}/{rel_suffix}"
                rel_paths.append(rel)

            result = "\n".join(rel_paths)
            if limit > 0 and total > limit:
                result += f"\n\n[Showing first {limit} of {total} files. Adjust limit to see more.]"
            else:
                result += f"\n\n[{total} files found.]"

            return result
        except Exception as e:
            return f"Failed to search files: {e}"

    @register.tool(
        "exec",
        "Execute a shell command. Proactively narrow its output to the current goal and retrieve only enough information to make the needed judgment. Prefer the command's own filtering, quantity, range, or summary capabilities; avoid dumping complete logs, large files, recursive directory listings, or other irrelevant content. Expand the scope gradually only when the available information is insufficient. DO NOT execute any harmful commands.",
        {
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "description": "Command to execute"},
                "work_dir": {
                    "type": "string",
                    "description": "Optional existing working directory. Relative paths are resolved from the application root."
                },
                "background": {
                    "type": "boolean",
                    "description": "Whether to run the command in the background. Waits for the configured background wait time before returning a task ID, then sends the completed result to this session. Defaults to false."
                }
            },
            "required": ["cmd"]
        }
    )
    async def exec(self, event: KiraMessageBatchEvent, cmd: str, work_dir: str | None = None, background: bool = False) -> str:
        if not self._is_exec_session_allowed(event.sid):
            return "Permission denied: current session not allowed to execute shell commands"

        shell_command = cmd.strip()

        exec_work_dir = get_root_path()
        if work_dir is not None:
            if not isinstance(work_dir, str) or not work_dir.strip():
                return "Working directory must be a non-empty string"
            try:
                exec_work_dir = Path(work_dir).expanduser()
                if not exec_work_dir.is_absolute():
                    exec_work_dir = get_root_path() / exec_work_dir
                exec_work_dir = exec_work_dir.resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                return f"Working directory not found: {work_dir}"

            if not exec_work_dir.is_dir():
                return f"Working directory is not a directory: {work_dir}"

        # Check deny list
        if self.exec_command_deny_list:
            cmd_lower = shell_command.lower()
            for blocked in self.exec_command_deny_list:
                blocked_lower = blocked.lower()
                if cmd_lower == blocked_lower or cmd_lower.startswith(blocked_lower + ' ') or cmd_lower.startswith(blocked_lower + '\t'):
                    logger.warning(f'Shell command blocked by deny list "{blocked}": {shell_command}')
                    return f'Shell command blocked by deny list: "{blocked}" is not allowed.'

        # Resolve python path if it's a python command
        for py_prefix in ("python ", "python3 "):
            if shell_command.startswith(py_prefix):
                import sys
                shell_command = f'"{sys.executable}" ' + shell_command[len(py_prefix):]

        # Resolve pip path if it's a pip command
        for pip_prefix in ("pip ", "pip3 "):
            if shell_command.startswith(pip_prefix):
                import sys
                shell_command = f'"{sys.executable}" -m pip ' + shell_command[len(pip_prefix):]

        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        if os.name == 'nt':
            shell_command = f'chcp 65001 >nul && {shell_command}'

        logger.info(f'Executing shell command: {shell_command} (cwd: {exec_work_dir})')
        if not background:
            return await asyncio.to_thread(
                self._run_shell_command,
                shell_command,
                self._exec_timeout,
                env,
                exec_work_dir,
            )

        task_id = f"exec-{uuid4().hex}"
        background_task = BackgroundExecTask(
            task_id=task_id,
            session=event.sid,
            work_dir=exec_work_dir,
            timeout=self._background_exec_timeout,
        )
        command_task = asyncio.create_task(
            self._run_background_shell_command(shell_command, background_task, env),
            name=f"exec_task_{task_id}",
        )
        background_task.execution_task = command_task
        self._background_exec_tasks[task_id] = background_task
        command_task.add_done_callback(
            lambda task: self._on_background_exec_done(task_id, event.sid, task)
        )
        try:
            return await asyncio.wait_for(
                asyncio.shield(command_task),
                timeout=self._background_exec_wait_seconds,
            )
        except asyncio.TimeoutError:
            background_task.notify_on_completion = True
            return (
                f"Shell command is running in the background (task_id: {task_id}). "
                "The result will be sent to this session when it completes."
            )
        except asyncio.CancelledError:
            background_task.notify_on_completion = False
            await self._stop_background_task(background_task)
            try:
                await asyncio.shield(command_task)
            except asyncio.CancelledError:
                pass
            finally:
                self._background_exec_tasks.pop(task_id, None)
            raise

    @register.tool(
        "manage_background_exec",
        "List, inspect output from, or stop background shell commands started in the current session.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "output", "stop"],
                    "description": "Use 'list' to view running tasks, 'output' to view a task's current output, or 'stop' to stop a task.",
                },
                "task_id": {
                    "type": "string",
                    "description": "Required for the 'output' and 'stop' actions."
                },
            },
            "required": ["action"],
        },
    )
    async def manage_background_exec(
        self,
        event: KiraMessageBatchEvent,
        action: str,
        task_id: str | None = None,
    ) -> str:
        if not self._is_exec_session_allowed(event.sid):
            return "Permission denied: current session not allowed to manage shell commands"

        if action == "list":
            session_tasks = [
                task for task in self._background_exec_tasks.values()
                if task.session == event.sid
            ]
            if not session_tasks:
                return "No background tasks are currently running."

            return "Running background tasks:\n" + "\n".join(
                (
                    f"- {task.task_id} | status: {task.status} | "
                    f"elapsed: {int(monotonic() - task.started_at)}s | "
                    f"output: {sum(len(chunk) for chunk in task.output_chunks)} chars"
                )
                for task in session_tasks
            )

        if action not in {"output", "stop"}:
            return "Invalid action. Use one of: list, output, stop."
        if not task_id:
            return f"task_id is required for the '{action}' action"

        background_task = self._background_exec_tasks.get(task_id)
        if background_task is None or background_task.session != event.sid:
            return f"Background task not found: {task_id}"

        if action == "output":
            output = "".join(background_task.output_chunks)
            if not output:
                return f"No output has been produced yet for task {task_id}."
            return f"Current output for task {task_id}:\n{output}"

        await self._stop_background_task(background_task)
        return f"Stop requested for background task {task_id}."
