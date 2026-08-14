import os
import re
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
from core.chat.message_elements import Text
from core.provider import LLMRequest

from core.utils.path_utils import get_data_path, get_root_path

restricted_paths = ['~/.ssh/', '~/.gnupg/', '~/.aws/', '~/.config/gh/', '.pem',
                    '.p12', 'key', 'secret', 'password', 'token', 'credential']

blocked_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg',
                      '.mp3', '.mp4', '.wav', '.ogg', '.flac', '.aac', '.silk', '.slk',
                      '.slac', '.amr', '.avi', '.mkv', '.mov', '.flv', '.wmv',
                      '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.exe', '.bin',
                      '.dll', '.so', '.dylib', '.pdf', '.doc', '.docx', '.xls', '.xlsx',
                      '.ppt', '.pptx', '.iso', '.img', '.dmg'}

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


class FilePlugin(BasePlugin):
    """
    FilePlugin
    """
    
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.allowed_sessions = list()
        self.allowed_exec_sessions = list()
        self.exec_deny_list = list()
        self.allowed_read_paths = tuple()
        self.allowed_write_paths = tuple()

        self._exec_timeout = 30
        self._background_exec_timeout = 300
        self._background_exec_wait_seconds = 2
        self._background_exec_tasks: dict[str, BackgroundExecTask] = {}
        self._background_notice_tasks: set[asyncio.Task] = set()

    async def initialize(self):
        self.allowed_sessions = self.plugin_cfg.get("allowed_sessions", [])
        self.allowed_exec_sessions = self.plugin_cfg.get("allowed_exec_sessions", [])
        self.exec_deny_list = self.plugin_cfg.get("exec_deny_list", [])
        self._exec_timeout = self._get_positive_int_config("exec_timeout", 30)
        self._background_exec_timeout = self._get_positive_int_config(
            "background_exec_timeout", 300
        )
        self._background_exec_wait_seconds = self._get_positive_int_config(
            "background_exec_wait_seconds", 2
        )
        base_read = ["data/files", "data/temp", "data/skills"]
        base_write = ["data/files", "data/temp"]
        extra_paths_cfg = self.plugin_cfg.get("extra_paths", {})
        extra_read = extra_paths_cfg.get("extra_read_paths", [])
        extra_write = extra_paths_cfg.get("extra_write_paths", [])
        self.allowed_read_paths = tuple(base_read + extra_read)
        self.allowed_write_paths = tuple(base_write + extra_write)

    def _get_positive_int_config(self, key: str, default: int) -> int:
        value = self.plugin_cfg.get(key, default)
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
        enabled = self.plugin_cfg.get("enabled_tools")
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

    @register.tool(
        "read_file",
        "Read a plain text file (txt, html, py, etc..) in allowed read paths",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path, must start with an allowed path prefix"},
                "offset": {"type": "integer", "description": "Which line to start reading, defaults to 1"},
                "limit": {"type": "integer", "description": "Maximum lines to read, defaults to 200"},
            },
            "required": ["path"]
        }
    )
    async def read_file(self, event: KiraMessageBatchEvent, path: str, offset: int = 1, limit: int = 200) -> str:
        if event.sid not in self.allowed_sessions:
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
            return "Multimedia and binary files are not allowed"

        try:
            abs_path = self._resolve_path(path)
            with open(abs_path, 'r', encoding="utf-8") as f:
                file_lines = f.readlines()
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
        if event.sid not in self.allowed_sessions:
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
            with open(abs_path, 'w', encoding="utf-8") as f:
                f.write(content)
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
        if event.sid not in self.allowed_sessions:
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

            with open(abs_path, 'r', encoding="utf-8") as f:
                content = f.read()

            if old_text == "":
                return "Error: old_text must not be empty."

            if old_text not in content:
                return "Error: old_text not found in file. Please check the content and try again."

            replacements = content.count(old_text)

            new_content = content.replace(old_text, new_text)

            abs_path.parent.mkdir(parents=True, exist_ok=True)
            with open(abs_path, 'w', encoding="utf-8") as f:
                f.write(new_content)

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
        if event.sid not in self.allowed_sessions:
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

            files = sorted(os.listdir(abs_path))

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
        if event.sid not in self.allowed_sessions:
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
            return self._grep_with_rg(
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
        if event.sid not in self.allowed_sessions:
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

            matches = sorted(
                abs_path.glob(pattern),
                key=lambda p: p.stat().st_mtime if p.is_file() else 0,
                reverse=True,
            )

            # Filter to files only
            files = [m for m in matches if m.is_file()]

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
        "Execute a shell command, DO NOT execute any harmful commands",
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
        if event.sid not in self.allowed_exec_sessions:
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
        if self.exec_deny_list:
            cmd_lower = shell_command.lower()
            for blocked in self.exec_deny_list:
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
        if event.sid not in self.allowed_exec_sessions:
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
