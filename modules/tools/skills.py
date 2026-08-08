# modules/tools/skills.py
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import pyperclip

from modules.domain.results import (
    ToolResult,
    VerificationResult,
)
from modules.tools.app_indexer import (
    WindowsAppIndexer,
    normalize_app_name,
    get_visible_window_titles,
)


logger = logging.getLogger("Skills")


class WindowsSkills:
    """
    Высокоуровневые Windows-навыки Nova.

    Каждый навык объединяет несколько атомарных операций
    в один вызов с проверкой результата.
    """

    def __init__(
        self,
        *,
        app_launcher: WindowsAppIndexer,
        list_windows: Callable[..., str],
        focus_window: Callable[..., str],
        press_hotkey: Callable[..., str],
        type_text: Callable[..., str],
        get_active_window_title: Callable[..., str],
        obsidian_config_path: Path | None = None,
        open_uri: Callable[[str], object] | None = None,
        clipboard_get: Callable[[], str] | None = None,
        clipboard_set: Callable[[str], object] | None = None,
    ) -> None:
        self.app_launcher = app_launcher
        self.list_windows = list_windows
        self.focus_window = focus_window
        self.press_hotkey = press_hotkey
        self.type_text = type_text
        self.get_active_window_title = get_active_window_title
        self.obsidian_config_path = obsidian_config_path or (
            Path(os.getenv("APPDATA", "")) / "obsidian" / "obsidian.json"
        )
        self.open_uri = open_uri or os.startfile
        self.clipboard_get = clipboard_get or pyperclip.paste
        self.clipboard_set = clipboard_set or pyperclip.copy

    @staticmethod
    def _is_obsidian(app_name: str) -> bool:
        return "obsidian" in normalize_app_name(app_name)

    def _active_obsidian_vault(self) -> Path | None:
        try:
            payload = json.loads(
                self.obsidian_config_path.read_text(encoding="utf-8")
            )
            vaults = payload.get("vaults", {})
            if not isinstance(vaults, dict):
                return None
            candidates = [
                item
                for item in vaults.values()
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            ]
            candidates.sort(
                key=lambda item: (
                    bool(item.get("open")),
                    float(item.get("ts", 0)),
                ),
                reverse=True,
            )
            for item in candidates:
                path = Path(str(item["path"])).expanduser()
                if path.is_dir():
                    return path
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            logger.exception("Не удалось определить активный Obsidian vault.")
        return None

    @staticmethod
    def _note_title(text: str) -> str:
        match = re.search(r"(?m)^\s*#{1,6}\s+(.+?)\s*$", text)
        title = match.group(1).strip() if match else "Nova note"
        title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", title)
        title = re.sub(r"\s+", " ", title).strip(" .")
        return title[:100] or "Nova note"

    @staticmethod
    def _unique_note_path(vault: Path, title: str) -> Path:
        candidate = vault / f"{title}.md"
        index = 2
        while candidate.exists():
            candidate = vault / f"{title} {index}.md"
            index += 1
        return candidate

    def _write_obsidian_note(self, text: str) -> ToolResult | None:
        vault = self._active_obsidian_vault()
        if vault is None:
            return None

        note_path = self._unique_note_path(vault, self._note_title(text))
        persisted_text = text.rstrip() + "\n"
        try:
            note_path.write_text(persisted_text, encoding="utf-8")
            observed_text = note_path.read_text(encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(
                "OBSIDIAN_NOTE_WRITE_FAILED",
                f"Не удалось создать заметку в Obsidian vault: {exc}",
                data={"vault_path": str(vault)},
            )

        if observed_text != persisted_text:
            return ToolResult.failure(
                "OBSIDIAN_NOTE_VERIFY_FAILED",
                "Файл заметки создан, но проверка содержимого не совпала с исходным текстом.",
                data={"path": str(note_path)},
            )

        relative_path = note_path.relative_to(vault).as_posix()
        uri = (
            "obsidian://open?vault="
            + quote(vault.name, safe="")
            + "&file="
            + quote(relative_path, safe="/")
        )
        try:
            self.open_uri(uri)
        except OSError:
            logger.exception("Заметка создана, но Obsidian URI не открылся.")

        return ToolResult.ok(
            f"Заметка '{note_path.stem}' создана в Obsidian и проверена по файлу.",
            data={
                "application": "Obsidian",
                "path": str(note_path),
                "vault_path": str(vault),
                "characters_written": len(text),
                "content_visually_verified": False,
                "content_file_verified": True,
            },
            verification=VerificationResult(
                verified=True,
                method="obsidian_file_roundtrip",
                confidence=1.0,
                details=f"Файл перечитан после записи: {note_path}",
            ),
        )

    def _verify_editor_text(self, expected_text: str) -> tuple[bool, str]:
        sentinel = f"nova_verify_{time.time_ns()}"
        try:
            old_clipboard = str(self.clipboard_get())
            self.clipboard_set(sentinel)
            self.press_hotkey("ctrl+a")
            self.press_hotkey("ctrl+c")
            time.sleep(0.25)
            observed = str(self.clipboard_get())
            self.press_hotkey("right")
            self.clipboard_set(old_clipboard)
        except Exception as exc:
            return False, f"Не удалось прочитать содержимое редактора: {exc}"

        normalized_expected = expected_text.replace("\r\n", "\n").strip()
        normalized_observed = observed.replace("\r\n", "\n").strip()
        if observed == sentinel:
            return False, "Приложение не отдало выделенный текст в буфер обмена."
        if (
            normalized_observed == normalized_expected
            or normalized_expected in normalized_observed
        ):
            return True, "Вставленный текст считан обратно из активного редактора."
        return False, "Содержимое редактора не совпало с отправленным текстом."

    @staticmethod
    def _result_failed(result: str) -> bool:
        lowered = result.lower()

        markers = (
            "ошибка",
            "не удалось",
            "не найден",
            "отказ",
            "заблокирован",
            "access denied",
            "permission denied",
        )

        return any(marker in lowered for marker in markers)

    def write_in_application(
        self,
        app_name: str,
        text: str,
        create_new_document: bool = True,
    ) -> ToolResult:
        """
        Открывает приложение, фокусирует окно, создаёт новый документ
        и вводит текст. Проверяет активное окно перед вводом.
        """
        clean_app_name = app_name.strip()
        clean_text = text.strip()

        if not clean_app_name:
            return ToolResult.failure("EMPTY_APPLICATION_NAME", "Название приложения не указано.")

        if not clean_text:
            return ToolResult.failure("EMPTY_TEXT", "Текст для записи не указан.")

        if len(clean_text) > 100_000:
            return ToolResult.failure("TEXT_TOO_LARGE", "За один вызов разрешено ввести до 100000 символов.")

        # Шаг 1: запуск приложения.
        launch_success, launch_message = self.app_launcher.launch_by_name(clean_app_name)

        if not launch_success:
            return ToolResult.failure("APPLICATION_LAUNCH_FAILED", launch_message)

        if create_new_document and self._is_obsidian(clean_app_name):
            obsidian_result = self._write_obsidian_note(clean_text)
            if obsidian_result is not None:
                return obsidian_result

        # Даем приложению время на активацию окна.
        time.sleep(0.8)

        # Шаг 2: фокусировка окна.
        focus_result = str(self.focus_window(clean_app_name))

        if self._result_failed(focus_result):
            match = self.app_launcher.find_app(clean_app_name)

            if match is not None:
                focus_result = str(self.focus_window(match.matched_name))

        if self._result_failed(focus_result):
            return ToolResult.failure(
                "WINDOW_FOCUS_FAILED",
                f"Приложение запущено, но его окно не удалось сфокусировать: {focus_result}",
                data={"launch_message": launch_message},
            )

        # Шаг 3: создание нового документа.
        if create_new_document:
            hotkey_result = str(self.press_hotkey("ctrl+n"))

            if self._result_failed(hotkey_result):
                return ToolResult.failure(
                    "NEW_DOCUMENT_FAILED",
                    f"Окно сфокусировано, но не удалось создать новый документ: {hotkey_result}",
                )

            time.sleep(0.3)

        # Шаг 4: проверка активного окна перед вводом.
        active_title = str(self.get_active_window_title()).strip()
        match = self.app_launcher.find_app(clean_app_name)

        expected_names = {clean_app_name.lower()}

        if match is not None:
            expected_names.add(match.matched_name.lower())

        if not active_title or not any(expected_name in active_title.lower() for expected_name in expected_names):
            return ToolResult.failure(
                "ACTIVE_WINDOW_CHANGED",
                f"Ввод отменен: активное окно больше не соответствует приложению '{clean_app_name}'. Текущее окно: '{active_title or 'неизвестно'}'.",
            )

        # Шаг 5: ввод текста.
        typing_result = str(self.type_text(clean_text))

        if self._result_failed(typing_result):
            return ToolResult.failure("TEXT_INPUT_FAILED", typing_result)

        time.sleep(0.35)
        verified, verification_details = self._verify_editor_text(clean_text)
        if not verified:
            focus_result = str(self.focus_window(clean_app_name))
            if not self._result_failed(focus_result):
                self.press_hotkey("ctrl+a")
                retry_result = str(self.type_text(clean_text))
                if not self._result_failed(retry_result):
                    time.sleep(0.35)
                    verified, verification_details = self._verify_editor_text(
                        clean_text
                    )

        if not verified:
            return ToolResult.failure(
                "TEXT_NOT_OBSERVED",
                (
                    "Текст был отправлен приложению, но Nova не смогла "
                    "считать его обратно. Успех не подтверждён."
                ),
                data={
                    "application": clean_app_name,
                    "characters_sent": len(clean_text),
                    "active_window": active_title,
                    "verification_details": verification_details,
                },
            )

        return ToolResult.ok(
            f"Текст введен в приложение '{clean_app_name}'.",
            data={
                "application": clean_app_name,
                "characters_written": len(clean_text),
                "new_document_requested": create_new_document,
                "launch_result": launch_message,
                "focus_result": focus_result,
                "content_visually_verified": True,
            },
            verification=VerificationResult(
                verified=True,
                method="clipboard_roundtrip",
                confidence=0.98,
                details=verification_details,
            ),
        )

    def open_and_focus(
        self,
        app_name: str,
    ) -> ToolResult:
        """
        Открывает приложение и фокусирует его окно.
        """
        clean_app_name = app_name.strip()

        if not clean_app_name:
            return ToolResult.failure("EMPTY_APPLICATION_NAME", "Название приложения не указано.")

        launch_success, launch_message = self.app_launcher.launch_by_name(clean_app_name)

        if not launch_success:
            return ToolResult.failure("APPLICATION_LAUNCH_FAILED", launch_message)

        time.sleep(0.5)

        focus_result = str(self.focus_window(clean_app_name))

        if self._result_failed(focus_result):
            match = self.app_launcher.find_app(clean_app_name)

            if match is not None:
                focus_result = str(self.focus_window(match.matched_name))

        if self._result_failed(focus_result):
            return ToolResult.failure(
                "WINDOW_FOCUS_FAILED",
                f"Приложение запущено, но окно не сфокусировано: {focus_result}",
            )

        return ToolResult.ok(
            f"Приложение '{clean_app_name}' открыто и сфокусировано.",
            data={
                "application": clean_app_name,
                "launch_result": launch_message,
                "focus_result": focus_result,
            },
        )
