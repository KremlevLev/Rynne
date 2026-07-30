from __future__ import annotations

from modules.brain.bypass import (
    check_instant_app_launch,
    is_complex_request,
)


class RecordingLauncher:
    def __init__(self) -> None:
        self.targets: list[str] = []

    def launch_by_name(
        self,
        target: str,
    ) -> tuple[bool, str]:
        self.targets.append(target)
        return True, f"Открыто: {target}"


def test_instant_launch_accepts_only_atomic_command() -> None:
    launcher = RecordingLauncher()

    handled, _ = check_instant_app_launch(
        "Открой блокнот",
        launcher,
    )

    assert handled
    assert launcher.targets == ["блокнот"]


def test_instant_launch_does_not_cut_off_follow_up_goal() -> None:
    launcher = RecordingLauncher()
    request = (
        "Включи браузер а в нём OpenRouter "
        "там чекни мою активность"
    )

    handled, _ = check_instant_app_launch(
        request,
        launcher,
    )

    assert not handled
    assert launcher.targets == []
    assert is_complex_request(request)
