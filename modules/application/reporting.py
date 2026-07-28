# modules/application/reporting.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modules.domain.results import AssistantResponse


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

        return (
            "Сэр, операция завершилась с ошибкой. "
            + message
        )

    tool_names = {
        str(record.get("name") or "")
        for record in records
    }

    if "write_in_application" in tool_names:
        return (
            "Сэр, приложение открыто, и текст введён."
        )

    if "type_text" in tool_names:
        return (
            "Сэр, текст введён в активное окно."
        )

    if "create_workspace_project" in tool_names:
        return (
            "Сэр, проект успешно создан. "
            "Подробности показаны на экране."
        )

    if "run_terminal_command" in tool_names:
        return (
            "Сэр, терминальная команда выполнена. "
            "Результат показан на экране."
        )

    if "set_reminder" in tool_names:
        return "Сэр, напоминание установлено."

    if "open_application" in tool_names:
        return "Сэр, приложение запущено."

    if "open_application_batch" in tool_names:
        return "Несколько приложений запущены."

    if "close_application" in tool_names:
        return "Сэр, приложение закрыто."

    return None


def build_tool_execution_summary(
    records: list[dict[str, Any]],
    *,
    budget_exhausted: bool = False,
) -> ToolExecutionSummary:
    if not records:
        return ToolExecutionSummary(
            display_text=(
                "Подтверждённых результатов "
                "инструментов нет."
            ),
            speech_text=(
                "Сэр, подтверждённых результатов нет."
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
            (
                f"{status} — "
                f"{_human_tool_name(tool_name)}: "
                f"{message}"
                f"{verification_suffix}"
            )
        )

    if budget_exhausted:
        lines.append(
            "Лимит агентных шагов был достигнут."
        )

    lines.append(
        (
            f"Итого: успешно — {successful_count}, "
            f"с ошибкой — {failed_count}, "
            f"без дополнительной проверки — "
            f"{unverified_count}."
        )
    )

    speech_text = _specialized_speech_summary(
        records,
        failed_count=failed_count,
    )

    if speech_text is None:
        if failed_count > 0:
            speech_text = (
                f"Сэр, операция завершена. "
                f"Ошибок: {failed_count}."
            )
        else:
            speech_text = (
                f"Сэр, операция выполнена. "
                f"Успешных действий: "
                f"{successful_count}."
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
) -> AssistantResponse:
    summary = build_tool_execution_summary(
        records,
        budget_exhausted=budget_exhausted,
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
