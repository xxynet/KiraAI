import json
from pathlib import Path

from core.plugin import plugin_registry
from core.utils.path_utils import resolve_manifest_icon_path


def test_resolve_manifest_icon_path_accepts_relative_image(tmp_path):
    icon = tmp_path / "assets" / "logo.svg"
    icon.parent.mkdir()
    icon.write_text("<svg></svg>", encoding="utf-8")

    assert resolve_manifest_icon_path(tmp_path, "assets/logo.svg") == icon.resolve()


def test_resolve_manifest_icon_path_rejects_paths_outside_manifest_directory(tmp_path):
    outside_icon = tmp_path.parent / "outside.png"
    outside_icon.write_bytes(b"not an image")

    assert resolve_manifest_icon_path(tmp_path, "../outside.png") is None
    assert resolve_manifest_icon_path(tmp_path, str(outside_icon)) is None


def test_resolve_manifest_icon_path_rejects_non_image_files(tmp_path):
    script = tmp_path / "main.py"
    script.write_text("print('not an icon')", encoding="utf-8")

    assert resolve_manifest_icon_path(tmp_path, "main.py") is None


def test_builtin_manifest_icons_resolve_within_their_directories():
    project_root = Path(__file__).parents[1]

    for component_root in (
        project_root / "core" / "adapter" / "src",
        project_root / "core" / "provider" / "src",
    ):
        for manifest_path in component_root.glob("*/manifest.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert resolve_manifest_icon_path(manifest_path.parent, manifest.get("icon")), manifest_path
            if "icon-dark" in manifest:
                assert resolve_manifest_icon_path(manifest_path.parent, manifest["icon-dark"]), manifest_path


def test_plugin_info_includes_resolved_manifest_icons(monkeypatch, tmp_path):
    icon = tmp_path / "icon.svg"
    dark_icon = tmp_path / "icon-dark.svg"
    icon.write_text("<svg></svg>", encoding="utf-8")
    dark_icon.write_text("<svg></svg>", encoding="utf-8")
    monkeypatch.setitem(plugin_registry._plugin_module_paths, "test-plugin", tmp_path)

    info = plugin_registry.PluginManager._build_plugin_info(
        "test-plugin", {"icon": "icon.svg", "icon-dark": "icon-dark.svg"},
    )

    assert info.icon == icon.resolve()
    assert info.icon_dark == dark_icon.resolve()
