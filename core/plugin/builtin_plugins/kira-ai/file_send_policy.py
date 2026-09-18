"""Send policy helpers for the <file> tag.

The tag is an egress channel for local files, so it applies path-safety rules
aligned with the agent plugin's ``read_file`` tool: traversal and restricted
keyword checks everywhere, an always-open base path set, and the agent
plugin's ``extra_read_paths`` gated by its file_access session list. The
agent plugin config is read straight from ``plugins/agent.json`` to keep this
plugin decoupled from the agent plugin instance.
"""

import json
import os
import posixpath
from typing import Optional

from core.logging_manager import get_logger
from core.utils.path_utils import get_config_path, get_data_path

message_logger = get_logger("message", "cyan")

# Directories any session may send through the <file> tag. They mirror the
# agent plugin's base write paths, where tool-produced attachments land.
FILE_TAG_BASE_PATHS = ("data/files", "data/temp")

# Mirrors the restricted keyword list of the agent plugin's read_file tool
# (core/plugin/builtin_plugins/agent/main.py); keep the two lists in sync.
RESTRICTED_PATHS = ['~/.ssh/', '~/.gnupg/', '~/.aws/', '~/.config/gh/', '.pem',
                    '.p12', 'key', 'secret', 'password', 'token', 'credential']

# Session permission modes, mirroring the agent plugin's file_access config.
ALLOW_LIST = "allow_list"
DENY_LIST = "deny_list"


def read_agent_file_access() -> dict:
    """Read the agent plugin's ``file_access`` section straight from its config file.

    Reading ``plugins/agent.json`` keeps the <file> tag decoupled from the
    agent plugin instance. A missing or unreadable file yields an empty dict,
    which only disables the extra send paths, never the base ones.
    """
    config_path = get_config_path() / "plugins" / "agent.json"
    try:
        with config_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        message_logger.warning(f"Failed to read agent plugin config for <file> tag: {e}")
        return {}
    if not isinstance(cfg, dict):
        return {}
    section = cfg.get("file_access")
    return section if isinstance(section, dict) else {}


def normalize_send_path(path: str) -> Optional[str]:
    """Normalize a send path and reject ``..`` traversal, mirroring read_file."""
    normalized = path.replace("\\", "/")
    normalized = posixpath.normpath(normalized)
    if normalized.startswith("../") or normalized == "..":
        return None
    return normalized


def path_matches_prefixes(path: str, prefixes: list[str]) -> bool:
    for prefix in prefixes:
        prefix = str(prefix).replace("\\", "/").rstrip("/")
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def is_session_allowed_for_extra_paths(sid: str, section: dict) -> bool:
    """Apply the agent plugin's file_access allow_list/deny_list semantics.

    An unknown session (empty sid) never qualifies, so a missing caller
    context can not leak the extra paths through deny_list mode.
    """
    if not sid:
        return False
    mode = str(section.get("permission_mode", "allow_list")).strip().lower()
    if mode not in (ALLOW_LIST, DENY_LIST):
        mode = ALLOW_LIST
    raw_list = section.get("session_list")
    sessions = []
    if isinstance(raw_list, list):
        for entry in raw_list:
            if isinstance(entry, bool) or not isinstance(entry, (str, int)):
                continue
            text = str(entry).strip()
            if text:
                sessions.append(text)
    listed = sid in sessions
    return listed if mode == ALLOW_LIST else not listed


def collect_extra_send_prefixes(section: dict) -> list[str]:
    """Resolve the agent plugin's extra_read_paths into absolute prefix strings."""
    extra = section.get("extra_read_paths")
    if not isinstance(extra, list):
        return []
    data_root = get_data_path()
    prefixes = []
    for entry in extra:
        if not isinstance(entry, str) or not entry.strip():
            continue
        normalized = normalize_send_path(entry.strip())
        if normalized is None:
            continue
        if normalized.startswith("data/"):
            normalized = str(data_root / normalized.removeprefix("data/"))
        prefixes.append(normalized)
    return prefixes


def resolve_local_send_path(value: str, sid: str = "") -> Optional[str]:
    """Resolve a <file> tag local path against the send policy.

    Returns the absolute path when the file is sendable, else ``None``:
    ``data/files`` and ``data/temp`` are open to every session, while the
    agent plugin's ``extra_read_paths`` additionally require the session to
    pass its file_access allow/deny list. Existence of the file is not
    checked here; callers decide how to handle missing files.
    """
    normalized = normalize_send_path(value)
    if normalized is None:
        message_logger.warning(f"<file> tag rejected path traversal: {value}")
        return None

    for rp in RESTRICTED_PATHS:
        if rp in normalized:
            message_logger.warning(f"<file> tag rejected restricted path: {normalized}")
            return None

    data_root = get_data_path()
    if normalized.startswith("data/"):
        abs_path = str(data_root / normalized.removeprefix("data/"))
    elif os.path.isabs(normalized):
        abs_path = normalized
    else:
        return None
    abs_path = abs_path.replace("\\", "/")

    base_prefixes = [
        str(data_root / base.removeprefix("data/")).replace("\\", "/")
        for base in FILE_TAG_BASE_PATHS
    ]
    if not path_matches_prefixes(abs_path, base_prefixes):
        section = read_agent_file_access()
        if not path_matches_prefixes(abs_path, collect_extra_send_prefixes(section)):
            message_logger.warning(f"<file> tag rejected path outside send policy: {normalized}")
            return None
        if not is_session_allowed_for_extra_paths(sid, section):
            message_logger.warning(f"<file> tag rejected extra path for session {sid or 'unknown'}")
            return None

    return abs_path
