from pathlib import Path

from scripts import rynne_wake_bridge as bridge


def test_wake_bridge_never_launches_standalone_tauri_debug_binary():
    source = (Path(__file__).parents[1] / "scripts" / "rynne_wake_bridge.py").read_text(encoding="utf-8")

    assert 'target" / "debug" / "rynne-desktop.exe' not in source
    assert "rynne-wake-launch.log" in source
    assert "process.poll()" in source


def test_wake_bridge_does_not_start_dev_runtime_unless_explicitly_enabled():
    source = (Path(__file__).parents[1] / "scripts" / "rynne_wake_bridge.py").read_text(encoding="utf-8")
    assert 'os.getenv("RYNNE_WAKE_ALLOW_DEV", "").strip() == "1"' in source


def test_wake_bridge_prefers_explicit_production_executable(monkeypatch, tmp_path):
    executable = tmp_path / "rynne-desktop.exe"
    executable.touch()
    monkeypatch.setenv("RYNNE_DESKTOP_EXE", str(executable))
    monkeypatch.setattr(bridge, "_registered_executables", lambda: [])

    candidates = bridge.installed_executable_candidates()

    assert candidates[0] == executable


def test_registry_display_icon_suffix_is_removed():
    path = bridge._clean_registry_path(r'"C:\\Apps\\Rynne\\rynne-desktop.exe",0')
    assert path == Path(r"C:\Apps\Rynne\rynne-desktop.exe")


def test_packaged_bridge_waits_for_cloud_configuration():
    source = (Path(__file__).parents[1] / "scripts" / "rynne_wake_bridge.py").read_text(encoding="utf-8")
    assert "waiting for desktop settings" in source
    assert "load_runtime_env()" in source
