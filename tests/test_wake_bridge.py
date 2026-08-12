from pathlib import Path


def test_wake_bridge_never_launches_standalone_tauri_debug_binary():
    source = (Path(__file__).parents[1] / "scripts" / "rynne_wake_bridge.py").read_text(encoding="utf-8")

    assert 'target" / "debug" / "rynne-desktop.exe' not in source
    assert "rynne-wake-launch.log" in source
    assert "process.poll()" in source
