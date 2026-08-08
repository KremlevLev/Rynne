# tests/test_skills_v2.py
from __future__ import annotations

import json
from pathlib import Path

from modules.tools.skills import WindowsSkills
from modules.tools.app_indexer import WindowsAppIndexer


class FakeAppLauncher:
    def launch_by_name(self, app_name: str) -> tuple[bool, str]:
        return True, f"Opened {app_name}"

    def find_app(self, app_name: str):
        return None


def test_write_in_application_rejects_empty_app_name() -> None:
    skills = WindowsSkills(
        app_launcher=WindowsAppIndexer(),
        list_windows=lambda: "",
        focus_window=lambda x: "Окно сфокусировано.",
        press_hotkey=lambda x: "Комбинация нажата.",
        type_text=lambda x: "Текст введён.",
        get_active_window_title=lambda: "Obsidian",
    )

    result = skills.write_in_application(
        app_name="",
        text="test",
    )

    assert not result.success
    assert result.code == "EMPTY_APPLICATION_NAME"


def test_write_in_application_rejects_empty_text() -> None:
    skills = WindowsSkills(
        app_launcher=WindowsAppIndexer(),
        list_windows=lambda: "",
        focus_window=lambda x: "Окно сфокусировано.",
        press_hotkey=lambda x: "Комбинация нажата.",
        type_text=lambda x: "Текст введён.",
        get_active_window_title=lambda: "Obsidian",
    )

    result = skills.write_in_application(
        app_name="Obsidian",
        text="",
    )

    assert not result.success
    assert result.code == "EMPTY_TEXT"


def test_open_and_focus_rejects_empty_name() -> None:
    skills = WindowsSkills(
        app_launcher=WindowsAppIndexer(),
        list_windows=lambda: "",
        focus_window=lambda x: "Окно сфокусировано.",
        press_hotkey=lambda x: "Комбинация нажата.",
        type_text=lambda x: "Текст введён.",
        get_active_window_title=lambda: "",
    )

    result = skills.open_and_focus(app_name="")

    assert not result.success
    assert result.code == "EMPTY_APPLICATION_NAME"


def test_obsidian_write_creates_and_rechecks_real_note(tmp_path: Path) -> None:
    vault = tmp_path / "My Vault"
    vault.mkdir()
    config = tmp_path / "obsidian.json"
    config.write_text(json.dumps({
        "vaults": {
            "vault-id": {
                "path": str(vault),
                "open": True,
                "ts": 10,
            },
        },
    }), encoding="utf-8")
    opened_uris: list[str] = []
    skills = WindowsSkills(
        app_launcher=FakeAppLauncher(),
        list_windows=lambda: "",
        focus_window=lambda value: "focused",
        press_hotkey=lambda value: "pressed",
        type_text=lambda value: "typed",
        get_active_window_title=lambda: "Obsidian",
        obsidian_config_path=config,
        open_uri=opened_uris.append,
    )

    result = skills.write_in_application(
        app_name="Obsidian",
        text="# Стих\n\nМеж звёзд летит мой тихий свет.",
    )

    assert result.success
    assert result.verification.verified is True
    assert result.verification.method == "obsidian_file_roundtrip"
    note = vault / "Стих.md"
    assert note.read_text(encoding="utf-8") == (
        "# Стих\n\nМеж звёзд летит мой тихий свет.\n"
    )
    assert opened_uris and opened_uris[0].startswith("obsidian://open?")


def test_generic_editor_never_claims_success_without_readback() -> None:
    clipboard = {"value": "initial"}
    skills = WindowsSkills(
        app_launcher=FakeAppLauncher(),
        list_windows=lambda: "",
        focus_window=lambda value: "focused",
        press_hotkey=lambda value: "pressed",
        type_text=lambda value: "typed",
        get_active_window_title=lambda: "Notepad",
        clipboard_get=lambda: clipboard["value"],
        clipboard_set=lambda value: clipboard.__setitem__("value", value),
    )

    result = skills.write_in_application(
        app_name="Notepad",
        text="Expected text",
    )

    assert not result.success
    assert result.code == "TEXT_NOT_OBSERVED"
    assert result.verification.verified is False


def test_selection_includes_high_level_skills() -> None:
    from modules.tools.selection import select_tool_names

    result = select_tool_names(
        "Открой Obsidian и напиши стих",
        has_image=False,
    )

    assert "write_in_application" in result
    assert "open_and_focus" in result


def test_selection_includes_skills_for_complex_command() -> None:
    from modules.tools.selection import select_tool_names

    result = select_tool_names(
        "Включи обсидиан, сделай там заметку и напиши стих",
        has_image=False,
    )

    assert "write_in_application" in result
    assert "open_and_focus" in result


def test_open_telegram_chat_uses_search_shortcut_and_contact() -> None:
    actions: list[tuple[str, str]] = []
    skills = WindowsSkills(
        app_launcher=FakeAppLauncher(),
        list_windows=lambda: "",
        focus_window=lambda value: actions.append(("focus", value)) or "focused",
        press_hotkey=lambda value: actions.append(("hotkey", value)) or "pressed",
        type_text=lambda value: actions.append(("type", value)) or "typed",
        get_active_window_title=lambda: "Telegram Web - Google Chrome",
    )

    result = skills.open_telegram_chat("Владислав")

    assert result.success
    assert result.verification.verified is None
    assert actions == [
        ("focus", "chrome"),
        ("hotkey", "ctrl+f"),
        ("type", "Владислав"),
        ("hotkey", "enter"),
    ]


def test_open_telegram_chat_refuses_wrong_active_tab() -> None:
    skills = WindowsSkills(
        app_launcher=FakeAppLauncher(),
        list_windows=lambda: "",
        focus_window=lambda value: "focused",
        press_hotkey=lambda value: "pressed",
        type_text=lambda value: "typed",
        get_active_window_title=lambda: "Search - Google Chrome",
    )

    result = skills.open_telegram_chat("Владислав")

    assert not result.success
    assert result.code == "TELEGRAM_WEB_NOT_ACTIVE"
