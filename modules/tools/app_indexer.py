# modules/tools/app_indexer.py
from __future__ import annotations

import ctypes
import logging
import os
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional, Tuple

from modules.domain.results import ToolResult

logger = logging.getLogger("AppIndexer")


SYSTEM_FALLBACKS = {
    "explorer": "explorer.exe",
    "проводник": "explorer.exe",
    "notepad": "notepad.exe",
    "блокнот": "notepad.exe",
    "calc": "calc.exe",
    "calculator": "calc.exe",
    "калькулятор": "calc.exe",
    "cmd": "cmd.exe",
    "консоль": "cmd.exe",
    "командная строка": "cmd.exe",
    "taskmgr": "taskmgr.exe",
    "диспетчер задач": "taskmgr.exe",
    "powershell": "powershell.exe",
    "пауэршелл": "powershell.exe",
    "paint": "mspaint.exe",
    "паинт": "mspaint.exe",
    "regedit": "regedit.exe",
    "редактор реестра": "regedit.exe",
}

RUSSIAN_ALIASES = {
    "обсидиан": "obsidian",
    "обсидиана": "obsidian",
    "обсидиану": "obsidian",
    "обсядем": "obsidian",
    "дискорд": "discord",
    "дискорда": "discord",
    "дискорду": "discord",
    "хром": "google chrome",
    "хрома": "google chrome",
    "хрому": "google chrome",
    "гугл": "google chrome",
    "браузер": "google chrome",
    "стим": "steam",
    "стима": "steam",
    "стиму": "steam",
    "телеграм": "telegram",
    "телеграма": "telegram",
    "телеграму": "telegram",
    "телега": "telegram",
    "телегу": "telegram",
    "спотифай": "spotify",
    "спотифая": "spotify",
    "спотифаю": "spotify",
    "проводник": "explorer",
    "проводника": "explorer",
    "проводнику": "explorer",
    "блокнот": "notepad",
    "блокнота": "notepad",
    "блокноту": "notepad",
    "калькулятор": "calculator",
    "калькулятора": "calculator",
    "калькуле": "calculator",
    "вс код": "visual studio code",
    "вэ эс код": "visual studio code",
    "код": "visual studio code",
    "пауэршелл": "powershell",
    "диспетчер задач": "taskmgr",
    "редактор реестра": "regedit",
}

# Conservative pool for requests such as "open five applications". It avoids
# uninstallers, administrative consoles and arbitrary Start Menu entries.
SAFE_BATCH_APPLICATIONS = (
    "notepad",
    "calculator",
    "explorer",
    "paint",
    "google chrome",
    "visual studio code",
    "telegram",
    "discord",
    "spotify",
    "steam",
)


@dataclass(slots=True, frozen=True)
class AppMatch:
    query: str
    matched_name: str
    path: str
    score: float
    match_type: str


def normalize_app_name(value: str) -> str:
    normalized = str(value).lower().replace("ё", "е")
    normalized = re.sub(r"[^\w\s.-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(" .-")


def get_visible_window_titles() -> list[str]:
    try:
        user32 = ctypes.windll.user32
    except AttributeError:
        return []

    titles: list[str] = []

    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )

    def callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True

            length = user32.GetWindowTextLengthW(hwnd)

            if length <= 0:
                return True

            buffer = ctypes.create_unicode_buffer(length + 1)

            user32.GetWindowTextW(hwnd, buffer, length + 1)

            title = buffer.value.strip()

            if title:
                titles.append(title)

        except Exception:
            logger.debug("Не удалось прочитать заголовок окна.", exc_info=True)

        return True

    callback_reference = callback_type(callback)
    user32.EnumWindows(callback_reference, 0)

    return titles


class WindowsAppIndexer:
    def __init__(self) -> None:
        self.apps_cache: dict[str, str] = {}
        self.index_all_apps()

    @staticmethod
    def _get_start_menu_paths() -> list[Path]:
        paths: list[Path] = []

        app_data = os.getenv("APPDATA", "").strip()

        if app_data:
            paths.append(
                Path(app_data)
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
            )

        program_data = os.getenv("PROGRAMDATA", r"C:\ProgramData").strip()

        if program_data:
            paths.append(
                Path(program_data)
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
            )

        return paths

    def index_all_apps(self) -> None:
        indexed_apps: dict[str, str] = {}

        for base_path in self._get_start_menu_paths():
            if not base_path.exists():
                logger.debug("Каталог меню Пуск отсутствует: %s", base_path)
                continue

            try:
                for shortcut_path in base_path.rglob("*"):
                    if not shortcut_path.is_file():
                        continue

                    if shortcut_path.suffix.lower() != ".lnk":
                        continue

                    app_name = normalize_app_name(shortcut_path.stem)

                    if not app_name:
                        continue

                    indexed_apps.setdefault(app_name, str(shortcut_path))

            except OSError:
                logger.exception("Не удалось просканировать %s.", base_path)

        self.apps_cache = indexed_apps

        logger.info("Индексация ПО завершена. Найдено ярлыков: %s", len(self.apps_cache))

    @staticmethod
    def _resolve_alias(query: str) -> str:
        normalized_query = normalize_app_name(query)
        alias_target = RUSSIAN_ALIASES.get(normalized_query, normalized_query)
        return normalize_app_name(alias_target)

    def _find_system_fallback(self, query: str) -> AppMatch | None:
        query_clean = normalize_app_name(query)
        alias_target = self._resolve_alias(query_clean)

        executable = SYSTEM_FALLBACKS.get(query_clean) or SYSTEM_FALLBACKS.get(alias_target)

        if not executable:
            return None

        return AppMatch(
            query=query,
            matched_name=alias_target,
            path=executable,
            score=1.0,
            match_type="system_exact",
        )

    def find_app(self, query: str) -> AppMatch | None:
        query_clean = normalize_app_name(query)

        if not query_clean:
            return None

        system_match = self._find_system_fallback(query_clean)

        if system_match is not None:
            return system_match

        alias_target = self._resolve_alias(query_clean)

        candidates: list[AppMatch] = []

        for cached_name, path in self.apps_cache.items():
            normalized_name = normalize_app_name(cached_name)

            if normalized_name == query_clean:
                score = 1.0
                match_type = "exact"
            elif normalized_name == alias_target:
                score = 0.99
                match_type = "alias"
            elif normalized_name.startswith(alias_target):
                score = 0.92
                match_type = "prefix"
            elif alias_target.startswith(normalized_name):
                score = 0.88
                match_type = "reverse_prefix"
            elif alias_target in normalized_name:
                score = 0.84
                match_type = "substring"
            elif normalized_name in alias_target:
                score = 0.80
                match_type = "reverse_substring"
            else:
                score = SequenceMatcher(None, alias_target, normalized_name).ratio()
                match_type = "fuzzy"

            candidates.append(
                AppMatch(
                    query=query,
                    matched_name=cached_name,
                    path=path,
                    score=score,
                    match_type=match_type,
                )
            )

        if not candidates:
            return None

        best_match = max(candidates, key=lambda item: item.score)

        if best_match.score < 0.72:
            return None

        return best_match

    def find_app_path(self, query: str) -> Optional[str]:
        match = self.find_app(query)

        if match is None:
            return None

        return match.path

    @staticmethod
    def _expected_window_terms(app_name: str, match: AppMatch) -> set[str]:
        terms = {
            normalize_app_name(app_name),
            normalize_app_name(match.matched_name),
            normalize_app_name(RUSSIAN_ALIASES.get(normalize_app_name(app_name), app_name)),
        }

        executable_stem = normalize_app_name(Path(match.path).stem)

        if executable_stem:
            terms.add(executable_stem)

        return {term for term in terms if len(term) >= 3}

    @staticmethod
    def _find_matching_window(titles: set[str], expected_terms: set[str]) -> str | None:
        for title in titles:
            if any(term in title for term in expected_terms):
                return title

        return None

    def launch_by_name(self, app_name: str) -> Tuple[bool, str]:
        match = self.find_app(app_name)

        if match is None:
            return (False, f"Приложение '{app_name}' не найдено.")

        if match.match_type == "fuzzy" and match.score < 0.82:
            return (
                False,
                f"Найдено похожее приложение '{match.matched_name}', но уверенность слишком низкая: {match.score:.0%}.",
            )

        expected_terms = self._expected_window_terms(app_name, match)

        before_titles = {normalize_app_name(title) for title in get_visible_window_titles()}

        existing_window = self._find_matching_window(before_titles, expected_terms)

        try:
            os.startfile(match.path)
        except OSError as exc:
            logger.exception("Windows не смогла запустить %s.", match.path)
            return (False, f"Ошибка запуска '{app_name}': {exc}")
        except Exception as exc:
            logger.exception("Не удалось запустить %s.", app_name)
            return (False, f"Непредвиденная ошибка запуска: {exc}")

        deadline = time.monotonic() + 8.0
        last_new_titles: set[str] = set()

        while time.monotonic() < deadline:
            time.sleep(0.25)

            current_titles = {normalize_app_name(title) for title in get_visible_window_titles()}

            matching_window = self._find_matching_window(current_titles, expected_terms)

            if matching_window:
                if existing_window:
                    return (
                        True,
                        f"Приложение '{match.matched_name}' уже было открыто. Запрос передан существующему экземпляру.",
                    )

                return (True, f"Приложение '{match.matched_name}' запущено, окно обнаружено.")

            last_new_titles = current_titles - before_titles

        if last_new_titles:
            logger.info("После запуска появились окна с неожиданными заголовками: %s", sorted(last_new_titles))

        return (True, f"Запрос на запуск '{match.matched_name}' передан Windows, но появление окна не подтверждено.")

    def launch_batch(self, count: int) -> ToolResult:
        """Launch a bounded number of ordinary applications."""
        resolved_count = max(2, min(10, int(count)))
        selected: list[str] = []
        seen_paths: set[str] = set()

        for app_name in SAFE_BATCH_APPLICATIONS:
            match = self.find_app(app_name)
            if match is None or match.path in seen_paths:
                continue
            selected.append(app_name)
            seen_paths.add(match.path)
            if len(selected) >= resolved_count:
                break

        results: list[dict[str, object]] = []
        for app_name in selected:
            success, message = self.launch_by_name(app_name)
            results.append(
                {
                    "app_name": app_name,
                    "success": success,
                    "message": message,
                }
            )

        successful = sum(
            bool(item["success"])
            for item in results
        )
        data = {
            "requested_count": resolved_count,
            "attempted_count": len(results),
            "successful_count": successful,
            "results": results,
        }

        if successful == resolved_count:
            return ToolResult.ok(
                f"Запущено приложений: {successful}.",
                data=data,
            )

        return ToolResult.failure(
            "APPLICATION_BATCH_PARTIAL",
            (
                f"Запущено {successful} из запрошенных "
                f"{resolved_count} приложений."
            ),
            data=data,
        )
