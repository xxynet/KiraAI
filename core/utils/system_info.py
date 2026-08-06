import hashlib
import platform
import subprocess
from pathlib import Path
from typing import Optional

import psutil

from core.logging_manager import get_logger


logger = get_logger("system_info", "cyan")


_ARCHITECTURE_ALIASES = {
    "amd64": "amd64",
    "x86_64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "i386": "x86",
    "i686": "x86",
    "x86": "x86",
}


def collect_system_profile() -> dict[str, int | str]:
    """Collect a small snapshot of the system resources visible to the process."""
    profile: dict[str, int | str] = {}

    try:
        total_bytes = psutil.virtual_memory().total
        if total_bytes > 0:
            profile["memory_total_mb"] = max(1, round(total_bytes / (1024 * 1024)))
    except Exception:
        logger.debug("Failed to probe total system memory", exc_info=True)

    try:
        physical_cores = psutil.cpu_count(logical=False)
        if physical_cores is not None and physical_cores > 0:
            profile["cpu_physical_cores"] = physical_cores
    except Exception:
        logger.debug("Failed to probe physical CPU cores", exc_info=True)

    try:
        logical_cores = psutil.cpu_count(logical=True)
        if logical_cores is not None and logical_cores > 0:
            profile["cpu_logical_cores"] = logical_cores
    except Exception:
        logger.debug("Failed to probe logical CPU cores", exc_info=True)

    try:
        machine = platform.machine().strip().lower()
        if machine:
            profile["architecture"] = _ARCHITECTURE_ALIASES.get(machine, machine[:32])
    except Exception:
        logger.debug("Failed to probe CPU architecture", exc_info=True)

    return profile


def get_anonymous_machine_id() -> Optional[str]:
    """Return a stable, one-way identifier for the current operating system.

    The OS identifier is never persisted or sent over the network.  Hashing it
    makes the value useful only for correlating KiraAI installations running on
    the same machine.
    """
    try:
        system = platform.system()
        if system == "Windows":
            source_id = _get_windows_machine_id()
        elif system == "Linux":
            source_id = _get_linux_machine_id()
        elif system == "Darwin":
            source_id = _get_macos_machine_id()
        else:
            return None
    except Exception:
        logger.debug("Failed to obtain an operating-system machine identifier", exc_info=True)
        return None

    if not source_id:
        return None

    return hashlib.sha256(f"KiraAI machine ID v1\\0{source_id}".encode("utf-8")).hexdigest()


def _get_windows_machine_id() -> Optional[str]:
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
    return str(value).strip() or None


def _get_linux_machine_id() -> Optional[str]:
    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return None


def _get_macos_machine_id() -> Optional[str]:
    result = subprocess.run(
        ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
        capture_output=True,
        check=False,
        text=True,
        timeout=2,
    )
    for line in result.stdout.splitlines():
        if "IOPlatformUUID" not in line:
            continue
        _, _, value = line.partition("=")
        value = value.strip().strip('"')
        if value:
            return value
    return None
