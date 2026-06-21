import os
import posixpath

from pathlib import Path

from core.plugin import BasePlugin, logger, register
from core.chat import KiraMessageBatchEvent

from core.utils.path_utils import get_data_path

restricted_paths = ['~/.ssh/', '~/.gnupg/', '~/.aws/', '~/.config/gh/', '.pem',
                    '.p12', 'key', 'secret', 'password', 'token', 'credential']

blocked_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg',
                      '.mp3', '.mp4', '.wav', '.ogg', '.flac', '.aac', '.silk', '.slk',
                      '.slac', '.amr', '.avi', '.mkv', '.mov', '.flv', '.wmv',
                      '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.exe', '.bin',
                      '.dll', '.so', '.dylib', '.pdf', '.doc', '.docx', '.xls', '.xlsx',
                      '.ppt', '.pptx', '.iso', '.img', '.dmg'}


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

            import re

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
