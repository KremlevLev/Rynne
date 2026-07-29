"""Реальные interaction-тесты нового Qt UI без mock-виджетов."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from modules.ui.chat import Composer
from modules.ui.control_center import ProcessesPage, SettingsPage
from modules.ui.shell import AppShell
from modules.ui.task_view import TaskView


def test_sidebar_click_switches_workspace() -> None:
    shell = AppShell()
    chat = QWidget()
    memory = QWidget()
    shell.add_workspace_screen("chat", chat, title="Диалог")
    shell.add_workspace_screen("memory", memory, title="Память")
    shell.show_screen("chat")

    shell.sidebar._items_by_key["memory"].click()

    assert shell.workspace.currentWidget() is memory
    assert shell._page_title.text() == "Память"
    assert shell.sidebar._current_item is shell.sidebar._items_by_key["memory"]


def test_composer_send_button_submits_real_options() -> None:
    submitted: list[tuple[str, dict]] = []
    composer = Composer(
        on_submit=lambda text, options: submitted.append((text, options))
    )
    composer.set_text("Проверь проект")
    coding_index = composer._mode_select.findData("coding")
    composer._mode_select.setCurrentIndex(coding_index)

    composer._send_btn.click()

    assert submitted == [
        (
            "Проверь проект",
            {
                "profile": "assistant",
                "model_mode": "coding",
                "attachments": [],
            },
        )
    ]
    assert composer._input.toPlainText() == ""


def test_process_stop_action_emits_backend_command_data() -> None:
    page = ProcessesPage()
    requested: list[tuple[str, bool]] = []
    page.stop_requested.connect(
        lambda process_id, force: requested.append((process_id, force))
    )
    page.set_items(
        [
            {
                "process_id": "proc_1",
                "label": "server",
                "pid": 123,
                "status": "running",
                "is_running": True,
                "command": ["python", "-m", "http.server"],
            }
        ]
    )

    card = page._content.itemAt(0).widget()
    button = card.actions.itemAt(0).widget()
    button.click()

    assert requested == [("proc_1", False)]


def test_settings_snapshot_does_not_echo_commands() -> None:
    page = SettingsPage()
    changes: list[tuple[str, object]] = []
    page.preference_changed.connect(
        lambda key, value: changes.append((key, value))
    )

    page.set_preferences(
        {
            "assistant_profile": "engineer",
            "model_mode": "coding",
            "tts_enabled": False,
            "cloud_enabled": True,
            "history_enabled": True,
            "proactive_vision_enabled": False,
        }
    )
    assert changes == []

    page._tts.click()
    assert changes == [("tts_enabled", True)]

    page._proactive_vision.click()
    assert changes[-1] == (
        "proactive_vision_enabled",
        True,
    )


def test_approval_reject_is_routed_to_backend_callback() -> None:
    denied: list[bool] = []
    task = TaskView(on_deny=lambda: denied.append(True))
    task.show_approval(
        "Разрешение",
        "Выполнить действие?",
    )
    task._on_reject_approval()

    assert denied == [True]
    assert task._approval_card is None
