"""Детерминированный ledger обязательных результатов пользовательской цели."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _contains(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


@dataclass(frozen=True, slots=True)
class GoalRequirement:
    key: str
    description: str
    tools: frozenset[str]


@dataclass(frozen=True, slots=True)
class GoalLedger:
    requirements: tuple[GoalRequirement, ...] = ()

    @classmethod
    def from_request(cls, text: str, available_tools: set[str]) -> "GoalLedger":
        normalized = str(text).lower().replace("ё", "е")
        requirements: list[GoalRequirement] = []

        def require(key: str, description: str, candidates: set[str]) -> None:
            usable = candidates & available_tools
            if usable and all(item.key != key for item in requirements):
                requirements.append(
                    GoalRequirement(key, description, frozenset(usable))
                )

        browser_context = _contains(normalized, (
            "браузер", "сайт", "страниц", "url", "ссылк", "openrouter",
            "опенроутер", "личный кабинет",
        ))
        if browser_context and _contains(normalized, (
            "открой", "зайди", "перейди", "включи", "open ", "visit ",
        )):
            require(
                "browser_navigation",
                "Открыть нужную страницу, а не только браузер или поиск.",
                {"browser_open_url", "open_website"},
            )
        if browser_context and _contains(normalized, (
            "проверь", "посмотри", "прочитай", "покажи", "активност",
            "что там", "найди на", "check ", "read ",
        )):
            require(
                "browser_inspection",
                "Прочитать или зафиксировать фактическое содержимое страницы.",
                {"browser_get_page_text", "browser_screenshot", "scrape_webpage"},
            )
        if _contains(normalized, (
            "скрин", "снимок страницы", "screenshot",
        )):
            require(
                "screenshot",
                "Создать запрошенный снимок результата.",
                {"browser_screenshot", "take_screenshot", "capture_screenshot"},
            )

        code_context = _contains(normalized, (
            "код", "проект", "репозитор", ".py", ".ts", ".tsx", ".js",
            ".go", "readme", "roadmap", ".md", "файл", "traceback",
            "pytest", "npm test",
        ))
        mutation_requested = _contains(normalized, (
            "исправ", "почини", "измени", "отредакт", "перепиши", "замени",
            "создай файл", "запиши в файл", "добавь в", "удали из",
        ))
        if code_context and mutation_requested:
            require(
                "workspace_change",
                "Внести реальное изменение в workspace.",
                {
                    "apply_text_patch", "write_text_file",
                    "edit_file_transactionally", "create_workspace_project",
                },
            )
            documentation_only = _contains(normalized, (
                "readme", "roadmap", ".md",
            )) and not _contains(normalized, (
                "код", "проект", ".py", ".ts", ".tsx", ".js", ".go",
            ))
            if documentation_only:
                require(
                    "workspace_verification",
                    "Проверить diff изменённого документа.",
                    {"get_file_diff"},
                )
            else:
                require(
                    "workspace_verification",
                    "Проверить изменение тестом, сборкой или исполнимой командой.",
                    {
                        "run_project_tests", "run_terminal_command",
                        "execute_cmd_command", "execute_python_code",
                    },
                )
        elif code_context and _contains(normalized, ("прочитай", "покажи файл")):
            require(
                "file_read",
                "Прочитать запрошенный файл.",
                {"read_text_file", "read_artifact"},
            )

        telegram_context = _contains(normalized, (
            "telegram", "телеграм", "телегу",
        ))
        messaging_requested = _contains(normalized, (
            "напиши", "написать", "ответь", "ответить", "отправь",
            "отправить", "сообщение", "send ", "reply ",
        ))
        if telegram_context and messaging_requested:
            require(
                "telegram_send",
                "Отправить сообщение точному Telegram-получателю реальным send tool.",
                {
                    "mcp_telegram_business_send_message",
                    "mcp_telegram_send_message",
                },
            )

        app_context = _contains(normalized, (
            "приложен", "программ", "блокнот", "калькулятор",
            "discord", "vscode", "vs code",
        )) and not browser_context and not telegram_context
        writing_requested = _contains(normalized, (
            "напиши", "введи", "вставь", "напечатай", "отправь",
        ))
        if app_context and _contains(normalized, (
            "открой", "запусти", "включи",
        )):
            require(
                "application_open",
                "Открыть или сфокусировать нужное приложение.",
                {"open_and_focus", "open_application", "focus_window"},
            )
        if app_context and writing_requested:
            require(
                "application_write",
                "Ввести запрошенный текст в целевое приложение.",
                {"write_in_application", "type_text"},
            )

        if _contains(normalized, ("закоммить", "сделай коммит", "git commit")):
            require(
                "git_commit",
                "Создать реальный Git commit после проверки изменений.",
                {"git_commit"},
            )

        return cls(tuple(requirements))

    @property
    def tool_hints(self) -> set[str]:
        return {
            tool
            for requirement in self.requirements
            for tool in requirement.tools
        }

    def unmet(self, tool_results: list[dict[str, Any]]) -> list[GoalRequirement]:
        successful_tools = {
            str(item.get("name") or "")
            for item in tool_results
            if isinstance(item.get("result"), dict)
            and bool(item["result"].get("success"))
        }
        return [
            requirement
            for requirement in self.requirements
            if not (requirement.tools & successful_tools)
        ]

    def prompt(self) -> str:
        if not self.requirements:
            return ""
        lines = [
            "GOAL COMPLETION LEDGER:",
            "До завершения задачи закрой каждый обязательный результат реальным "
            "успешным tool result:",
        ]
        lines.extend(
            f"- [ ] {item.description} Допустимые tools: "
            + ", ".join(sorted(item.tools))
            for item in self.requirements
        )
        return "\n".join(lines)

    @staticmethod
    def gate_prompt(unmet: list[GoalRequirement]) -> str:
        lines = [
            "COMPLETION GATE: предыдущий ответ попытался завершить задачу, но "
            "обязательные результаты ещё не подтверждены:",
        ]
        lines.extend(f"- {item.description}" for item in unmet)
        lines.append(
            "Не сообщай об успехе. Сейчас вызови tool для следующего незакрытого "
            "результата либо верни один конкретный blocker из tool result."
        )
        return "\n".join(lines)
