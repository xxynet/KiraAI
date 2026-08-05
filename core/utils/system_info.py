import platform
import psutil


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
        pass

    try:
        physical_cores = psutil.cpu_count(logical=False)
        if physical_cores is not None and physical_cores > 0:
            profile["cpu_physical_cores"] = physical_cores
    except Exception:
        pass

    try:
        logical_cores = psutil.cpu_count(logical=True)
        if logical_cores is not None and logical_cores > 0:
            profile["cpu_logical_cores"] = logical_cores
    except Exception:
        pass

    try:
        machine = platform.machine().strip().lower()
        if machine:
            profile["architecture"] = _ARCHITECTURE_ALIASES.get(machine, machine[:32])
    except Exception:
        pass

    return profile
