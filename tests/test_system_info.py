from unittest.mock import MagicMock, patch

from core.telemetry.client import TelemetryClient
from core.utils.system_info import collect_system_profile, get_anonymous_machine_id


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


def test_get_anonymous_machine_id_hashes_os_identifier():
    with (
        patch("core.utils.system_info.platform.system", return_value="Linux"),
        patch("core.utils.system_info._get_linux_machine_id", return_value="raw-machine-id"),
    ):
        machine_id = get_anonymous_machine_id()

    assert machine_id == "343ef004ec38558596fe299811da5d61626d15ea55324b7ee7931149035cb985"
    assert "raw-machine-id" not in machine_id


def test_get_anonymous_machine_id_returns_none_when_unavailable():
    with (
        patch("core.utils.system_info.platform.system", return_value="Linux"),
        patch("core.utils.system_info._get_linux_machine_id", return_value=None),
    ):
        assert get_anonymous_machine_id() is None


def test_system_startup_includes_system_profile():
    telemetry = object.__new__(TelemetryClient)
    telemetry.country_code = "CN"
    telemetry.machine_id = "anonymous-machine-id"
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
    assert data["machine_id"] == "anonymous-machine-id"
    assert {key: data[key] for key in profile} == profile


def test_telemetry_payload_omits_machine_id_for_non_startup_event():
    telemetry = object.__new__(TelemetryClient)
    telemetry.client_uuid = "installation-id"

    payload = telemetry._build_payload("heartbeat", {"uptime_ms": 10})

    assert payload["client_uuid"] == "installation-id"
    assert "machine_id" not in payload["data"]
