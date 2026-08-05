from unittest.mock import MagicMock, patch

from core.telemetry.client import TelemetryClient
from core.utils.system_info import collect_system_profile


def test_collect_system_profile():
    memory = MagicMock(total=16 * 1024 * 1024 * 1024)

    with (
        patch("core.utils.system_info.psutil.virtual_memory", return_value=memory),
        patch(
            "core.utils.system_info.psutil.cpu_count",
            side_effect=lambda logical: 16 if logical else 8,
        ),
        patch("core.utils.system_info.platform.machine", return_value="x86_64"),
    ):
        assert collect_system_profile() == {
            "memory_total_mb": 16384,
            "cpu_physical_cores": 8,
            "cpu_logical_cores": 16,
            "architecture": "amd64",
        }


def test_collect_system_profile_omits_unavailable_values():
    with (
        patch("core.utils.system_info.psutil.virtual_memory", side_effect=OSError),
        patch("core.utils.system_info.psutil.cpu_count", return_value=None),
        patch("core.utils.system_info.platform.machine", return_value=""),
    ):
        assert collect_system_profile() == {}


def test_system_startup_includes_system_profile():
    telemetry = object.__new__(TelemetryClient)
    telemetry.country_code = "CN"
    telemetry.send_event = MagicMock()
    profile = {
        "memory_total_mb": 8192,
        "cpu_physical_cores": 4,
        "cpu_logical_cores": 8,
        "architecture": "arm64",
    }

    with patch("core.telemetry.client.collect_system_profile", return_value=profile):
        telemetry.send_system_startup(python_version="3.12.0")

    event_type, data = telemetry.send_event.call_args.args
    assert event_type == "system_startup"
    assert data["python_version"] == "3.12.0"
    assert data["country_code"] == "CN"
    assert {key: data[key] for key in profile} == profile
