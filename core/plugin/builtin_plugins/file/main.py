import os
import re
import shutil
import posixpath
import subprocess

from pathlib import Path

from core.plugin import BasePlugin, logger, on, Priority, register
from core.chat import KiraMessageBatchEvent
from core.provider import LLMRequest

from core.utils.path_utils import get_data_path

restricted_paths = ['~/.ssh/', '~/.gnupg/', '~/.aws/', '~/.config/gh/', '.pem',
                    '.p12', 'key', 'secret', 'password', 'token', 'credential']

blocked_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg',
                      '.mp3', '.mp4', '.wav', '.ogg', '.flac', '.aac', '.silk', '.slk',
                      '.slac', '.amr', '.avi', '.mkv', '.mov', '.flv', '.wmv',
                      '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.exe', '.bin',
                      '.dll', '.so', '.dylib', '.pdf', '.doc', '.docx', '.xls', '.xlsx',
                      '.ppt', '.pptx', '.iso', '.img', '.dmg'}

ALL_TOOL_NAMES = ["read_file", "write_file", "edit_file", "list_files", "grep", "search_files", "exec"]


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

    async def initialize(self):
        self.allowed_sessions = self.plugin_cfg.get("allowed_sessions", [])
        self.allowed_exec_sessions = self.plugin_cfg.get("allowed_exec_sessions", [])
        self.exec_deny_list = self.plugin_cfg.get("exec_deny_list", [])
        base_read = ["data/files", "data/temp", "data/skills"]
        base_write = ["data/files", "data/temp"]
        extra_paths_cfg = self.plugin_cfg.get("extra_paths", {})
        extra_read = extra_paths_cfg.get("extra_read_paths", [])
        extra_write = extra_paths_cfg.get("extra_write_paths", [])
        self.allowed_read_paths = tuple(base_read + extra_read)
        self.allowed_write_paths = tuple(base_write + extra_write)

    @on.llm_request(priority=Priority.LOW)
    async def filter_tools(self, event: KiraMessageBatchEvent, req: LLMRequest, *_):
        enabled = self.plugin_cfg.get("enabled_tools")
        if not enabled:
            return
        disabled = set(ALL_TOOL_NAMES) - set(enabled)
        if disabled:
            req.tool_set.remove(*disabled)

    async def terminate(self):
        pass

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

            if old_text not in content:
                return f"Error: old_text not found in file. Please check the content and try again."

            replacements = len(re.findall(re.escape(old_text), content))

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
            result += f"\n\n[Showing first {limit} results. Adjust limit or use offset to see more.]"
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

        cmd.extend([pattern, search_path])

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
        output_mode: str = "files_with_matches",
        context: int = 0,
        case_insensitive: bool = False,
        glob: str | None = None,
        multiline: bool = False,
        limit: int = 200,
    ) -> str:
        """Search file contents using pure-Python re module."""
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

        lines: list[str] = []
        matched_files: list[str] = []
        file_count_map: dict[str, int] = {}

        for fp in files:
            if not fp.is_file():
                continue
            if fp.suffix.lower() in blocked_extensions:
                continue
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            file_lines = content.splitlines(keepends=True)
            match_indices = [
                i for i, line in enumerate(file_lines) if regex.search(line)
            ]
            if not match_indices:
                continue

            rel = str(fp).replace("\\", "/")
            matched_files.append(rel)
            file_count_map[rel] = len(match_indices)

            if output_mode == "content":
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
            return self._grep_with_python(
                pattern, abs_path, output_mode, context,
                case_insensitive, glob, multiline, limit,
            )

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
                rel = str(f.relative_to(abs_path)).replace("\\", "/")
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
            },
            "required": ["cmd"]
        }
    )
    async def exec(self, event: KiraMessageBatchEvent, cmd: str) -> str:
        if event.sid not in self.allowed_exec_sessions:
            return "Permission denied: current session not allowed to execute shell commands"

        import subprocess

        shell_command = cmd.strip()

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

        exec_timeout = 30  # seconds

        logger.info(f'Executing shell command: {shell_command} (cwd: {os.getcwd()})')
        try:
            result = subprocess.run(
                shell_command, shell=True, capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=exec_timeout, env=env, encoding='utf-8', errors='replace'
            )
            output = (result.stdout or '') + (result.stderr or '')
            if result.returncode == 0:
                return f'Shell command output:\n{output}'
            else:
                return f'Shell command failed (exit {result.returncode}):\n{output}'
        except subprocess.TimeoutExpired:
            return f'Shell command timed out after {exec_timeout} seconds: {shell_command}'
        except Exception as e:
            return f'Unexpected error while executing shell command: {e}'
