# modules/application/reporting.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from modules.domain.results import AssistantResponse


def _structured_payload(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data")
    if isinstance(data, dict):
        structured = data.get("structured_content")
        if isinstance(structured, dict):
            return structured

    message = str(result.get("message") or "").strip()
    if message.startswith("{") and message.endswith("}"):
        try:
            parsed = json.loads(message)
        except (ValueError, TypeError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _compact_message(message: str, *, fallback: str) -> str:
    cleaned = " ".join(str(message).split()).strip()
    if not cleaned or (cleaned.startswith("{") and cleaned.endswith("}")):
        return fallback
    if len(cleaned) > 240:
        return cleaned[:237].rstrip() + "..."
    return cleaned


def _telegram_summary(
    records: list[dict[str, Any]],
    *,
    language: str,
) -> tuple[str, str, bool] | None:
    telegram_records = [
        record
        for record in records
        if "telegram" in str(record.get("name") or "").casefold()
    ]
    if not telegram_records:
        return None

    for record in reversed(telegram_records):
        name = str(record.get("name") or "").casefold()
        result = _result_from_record(record)
        payload = _structured_payload(result)
        if name.endswith("send_message") and result.get("success"):
            arguments = record.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            recipient = str(
                payload.get("chat")
                or payload.get("username")
                or arguments.get("chat_identifier")
                or ""
            ).strip()
            if language == "en":
                return (
                    f"Done. Message sent{f' to {recipient}' if recipient else ''}.",
                    "Done. The message was sent.",
                    True,
                )
            return (
                "Готово. Сообщение отправлено"
                + (f" пользователю {recipient}" if recipient else "")
                + ".",
                "Готово. Сообщение отправлено.",
                True,
            )

    last_result = _result_from_record(telegram_records[-1])
    payload = _structured_payload(last_result)
    if payload.get("status") == "not_found":
        query = str(payload.get("query") or "").strip()
        if language == "en":
            return (
                f"I couldn't find {query or 'that chat'}. Send the exact @username.",
                "I couldn't find that chat. Send the exact username.",
                False,
            )
        return (
            f"Не нашла {f'«{query}»' if query else 'этот чат'}. "
            "Назови точный @username.",
            "Не нашла этот чат. Назови точное имя пользователя.",
            False,
        )
    return None


@dataclass(slots=True)
class ToolExecutionSummary:
    display_text: str
    speech_text: str

    success: bool
    error_code: str | None

    successful_count: int
    failed_count: int
    unverified_count: int


def _result_from_record(
    record: dict[str, Any],
) -> dict[str, Any]:
    result = record.get("result")

    if isinstance(result, dict):
        return result

    return {}


def _verification_state(
    result: dict[str, Any],
) -> bool | None:
    verification = result.get("verification")

    if not isinstance(verification, dict):
        return None

    verified = verification.get("verified")

    if isinstance(verified, bool):
        return verified

    return None


def _human_tool_name(tool_name: str) -> str:
    names = {
        "open_application": "Запуск приложения",
        "open_application_batch": "Запуск нескольких приложений",
        "close_application": "Закрытие приложения",
        "focus_window": "Фокусировка окна",
        "press_keyboard_combination": "Нажатие клавиш",
        "type_text": "Ввод текста",
        "write_in_application": "Запись в приложение",
        "open_url_in_browser": "Открытие сайта в вашем браузере",
        "open_telegram_chat": "Открытие чата Telegram",
        "create_workspace_project": "Создание проекта",
        "run_terminal_command": "Терминальная команда",
        "execute_python_code": "Выполнение кода",
        "set_reminder": "Создание напоминания",
        "save_to_memory": "Сохранение в память",
        "create_quick_note": "Создание заметки",
        "change_volume": "Изменение громкости",
        "open_website": "Открытие сайта",
        "scrape_webpage": "Чтение веб-страницы",
    }

    return names.get(tool_name, tool_name)


def _specialized_speech_summary(
    records: list[dict[str, Any]],
    *,
    failed_count: int,
) -> str | None:
    if failed_count > 0:
        first_failure = next(
            (
                record
                for record in records
                if not bool(
                    _result_from_record(
                        record
                    ).get("success")
                )
            ),
            None,
        )

        if first_failure is None:
            return None

        result = _result_from_record(
            first_failure
        )

        message = str(
            result.get("message")
            or "Причина ошибки не указана."
        )

        return "Не получилось. " + _compact_message(
            message,
            fallback="Инструмент завершился с ошибкой.",
        )

    tool_names = {
        str(record.get("name") or "")
        for record in records
    }

    if "write_in_application" in tool_names:
        return "Готово. Текст введён и проверен."

    if "type_text" in tool_names:
        return "Готово. Текст введён в активное окно."

    if "create_workspace_project" in tool_names:
        return "Готово. Проект создан."

    if "run_terminal_command" in tool_names:
        return "Готово. Команда выполнена."

    if "set_reminder" in tool_names:
        return "Готово. Напоминание установлено."

    if "open_application" in tool_names:
        return "Готово. Приложение запущено."

    if "open_application_batch" in tool_names:
        return "Несколько приложений запущены."

    if "close_application" in tool_names:
        return "Готово. Приложение закрыто."

    return None


def _english_result_message(
    result: dict[str, Any],
    *,
    success: bool,
) -> str:
    """Keep deterministic English reports English, even for localized tools."""
    message = str(result.get("message") or "").strip()
    if (
        message
        and not (message.startswith("{") and message.endswith("}"))
        and not any("А" <= char <= "я" or char in "Ёё" for char in message)
    ):
        return message

    data = result.get("data")
    if isinstance(data, dict):
        path = str(data.get("path") or data.get("file_path") or "").strip()
        if path:
            return f"Created or updated: {path}" if success else f"Failed for: {path}"

    if success:
        return "The action completed successfully."

    code = str(result.get("code") or "TOOL_FAILED").strip()
    return f"The action failed ({code})."


def _build_english_tool_execution_summary(
    records: list[dict[str, Any]],
    *,
    budget_exhausted: bool,
) -> ToolExecutionSummary:
    if not records:
        return ToolExecutionSummary(
            display_text="There are no confirmed tool results.",
            speech_text="There are no confirmed results yet.",
            success=False,
            error_code="NO_CONFIRMED_TOOL_RESULTS",
            successful_count=0,
            failed_count=0,
            unverified_count=0,
        )

    english_names = {
        "open_application": "Open application",
        "open_application_batch": "Open multiple applications",
        "close_application": "Close application",
        "focus_window": "Focus window",
        "press_keyboard_combination": "Press keyboard shortcut",
        "type_text": "Type text",
        "write_in_application": "Write in application",
        "open_url_in_browser": "Open website in your browser",
        "open_telegram_chat": "Open Telegram chat",
        "create_workspace_project": "Create project",
        "run_terminal_command": "Run terminal command",
        "execute_python_code": "Run code",
        "set_reminder": "Set reminder",
        "save_to_memory": "Save to memory",
        "create_quick_note": "Create note",
        "change_volume": "Change volume",
        "open_website": "Open website",
        "scrape_webpage": "Read webpage",
    }
    lines: list[str] = []
    successful_count = 0
    failed_count = 0
    unverified_count = 0
    tool_names: set[str] = set()

    for record in records:
        tool_name = str(record.get("name") or "unknown")
        tool_names.add(tool_name)
        result = _result_from_record(record)
        success = bool(result.get("success"))
        verified = _verification_state(result)
        if success:
            successful_count += 1
            status = "Completed"
            if verified is True:
                verification_suffix = " [verified]"
            elif verified is False:
                verification_suffix = " [verification failed]"
            else:
                verification_suffix = " [not independently verified]"
                unverified_count += 1
        else:
            failed_count += 1
            status = "Failed"
            verification_suffix = ""

        lines.append(
            f"{status}: {_english_result_message(result, success=success)}"
            f"{verification_suffix}"
        )

    if budget_exhausted:
        lines.append("The agent step limit was reached.")
    if budget_exhausted:
        lines = ["The agent step limit was reached."]
    elif failed_count:
        lines = [
            next(
                line for line in reversed(lines)
                if line.startswith("Failed:")
            )
        ]
    elif len(lines) > 1:
        lines = [lines[-1]]

    if failed_count:
        speech_text = f"The action finished with {failed_count} error(s)."
    elif "write_in_application" in tool_names:
        speech_text = "The application is open and the text was entered."
    elif "type_text" in tool_names:
        speech_text = "The text was entered in the active window."
    elif "open_application" in tool_names:
        speech_text = "The application is open."
    elif "set_reminder" in tool_names:
        speech_text = "The reminder is set."
    else:
        speech_text = f"Done. {successful_count} action(s) completed."
    if budget_exhausted:
        speech_text += " The step limit was reached."

    response_success = (
        failed_count == 0
        and successful_count > 0
        and not budget_exhausted
    )
    error_code = None
    if budget_exhausted:
        error_code = "AGENT_BUDGET_EXHAUSTED"
    elif failed_count:
        error_code = "ONE_OR_MORE_TOOLS_FAILED"

    return ToolExecutionSummary(
        display_text="\n".join(lines),
        speech_text=speech_text,
        success=response_success,
        error_code=error_code,
        successful_count=successful_count,
        failed_count=failed_count,
        unverified_count=unverified_count,
    )


def build_tool_execution_summary(
    records: list[dict[str, Any]],
    *,
    budget_exhausted: bool = False,
    language: str = "ru",
) -> ToolExecutionSummary:
    telegram_summary = _telegram_summary(records, language=language)
    if telegram_summary is not None:
        text, speech_text, completed = telegram_summary
        failed_count = sum(
            not bool(_result_from_record(record).get("success"))
            for record in records
        )
        successful_count = len(records) - failed_count
        return ToolExecutionSummary(
            display_text=text,
            speech_text=speech_text,
            success=completed and failed_count == 0 and not budget_exhausted,
            error_code=(
                "AGENT_BUDGET_EXHAUSTED"
                if budget_exhausted
                else "GOAL_INCOMPLETE"
                if not completed
                else "ONE_OR_MORE_TOOLS_FAILED"
                if failed_count
                else None
            ),
            successful_count=successful_count,
            failed_count=failed_count,
            unverified_count=0,
        )

    if language == "en":
        return _build_english_tool_execution_summary(
            records,
            budget_exhausted=budget_exhausted,
        )

    if not records:
        return ToolExecutionSummary(
            display_text=(
                "Подтверждённых результатов "
                "инструментов нет."
            ),
            speech_text=(
                "Подтверждённых результатов пока нет."
            ),
            success=False,
            error_code="NO_CONFIRMED_TOOL_RESULTS",
            successful_count=0,
            failed_count=0,
            unverified_count=0,
        )

    lines: list[str] = []

    successful_count = 0
    failed_count = 0
    unverified_count = 0

    for record in records:
        tool_name = str(
            record.get("name")
            or "unknown"
        )
        result = _result_from_record(record)

        success = bool(result.get("success"))
        message = str(
            result.get("message")
            or "Описание результата отсутствует."
        )

        verification_state = (
            _verification_state(result)
        )

        if success:
            successful_count += 1
            status = "Выполнено"

            if verification_state is True:
                verification_suffix = (
                    " [проверено]"
                )
            elif verification_state is False:
                verification_suffix = (
                    " [проверка не пройдена]"
                )
            else:
                verification_suffix = (
                    " [без дополнительной проверки]"
                )
                unverified_count += 1

        else:
            failed_count += 1
            status = "Ошибка"
            verification_suffix = ""

        lines.append(
            f"{status}: "
            + _compact_message(
                message,
                fallback=("Готово." if success else "Действие не выполнено."),
            )
            + verification_suffix
        )

    if budget_exhausted:
        lines.append(
            "Лимит агентных шагов был достигнут."
        )

    # Подробные инструменты, счётчики и timings уже видны в execution timeline.
    # Финальная реплика Nova должна оставаться короткой и человеческой.
    if budget_exhausted:
        lines = ["Лимит агентных шагов был достигнут."]
    elif failed_count:
        lines = [
            next(
                line for line in reversed(lines)
                if line.startswith("Ошибка:")
            )
        ]
    elif len(lines) > 1:
        lines = [lines[-1]]

    speech_text = _specialized_speech_summary(
        records,
        failed_count=failed_count,
    )

    if speech_text is None:
        if failed_count > 0:
            speech_text = (
                f"Не получилось. Ошибок: {failed_count}."
            )
        else:
            speech_text = (
                "Готово."
            )

    if budget_exhausted:
        speech_text += (
            " Лимит шагов был достигнут."
        )

    response_success = (
        failed_count == 0
        and successful_count > 0
        and not budget_exhausted
    )

    error_code: str | None = None

    if budget_exhausted:
        error_code = "AGENT_BUDGET_EXHAUSTED"
    elif failed_count > 0:
        error_code = "ONE_OR_MORE_TOOLS_FAILED"

    return ToolExecutionSummary(
        display_text="\n".join(lines),
        speech_text=speech_text,
        success=response_success,
        error_code=error_code,
        successful_count=successful_count,
        failed_count=failed_count,
        unverified_count=unverified_count,
    )


def build_assistant_response_from_tools(
    records: list[dict[str, Any]],
    *,
    budget_exhausted: bool = False,
    language: str = "ru",
) -> AssistantResponse:
    summary = build_tool_execution_summary(
        records,
        budget_exhausted=budget_exhausted,
        language=language,
    )

    return AssistantResponse(
        display_text=summary.display_text,
        speech_text=summary.speech_text,
        success=summary.success,
        error_code=summary.error_code,
        data={
            "successful_count": (
                summary.successful_count
            ),
            "failed_count": summary.failed_count,
            "unverified_count": (
                summary.unverified_count
            ),
            "budget_exhausted": budget_exhausted,
        },
    )
