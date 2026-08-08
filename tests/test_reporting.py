# tests/test_reporting.py
from __future__ import annotations

from modules.application.reporting import (
    build_assistant_response_from_tools,
    build_tool_execution_summary,
)
from modules.domain.results import (
    ToolResult,
    VerificationResult,
)


def create_record(
    name: str,
    result: ToolResult,
) -> dict:
    return {
        "tool_call_id": f"call_{name}",
        "name": name,
        "arguments": {},
        "result": result.to_dict(),
    }


def test_empty_records_return_failure() -> None:
    response = build_assistant_response_from_tools(
        []
    )

    assert not response.success
    assert (
        response.error_code
        == "NO_CONFIRMED_TOOL_RESULTS"
    )


def test_successful_write_has_short_speech() -> None:
    records = [
        create_record(
            "open_application",
            ToolResult.ok(
                "Приложение открыто.",
            ),
        ),
        create_record(
            "type_text",
            ToolResult.ok(
                "Текст введён.",
            ),
        ),
    ]

    response = build_assistant_response_from_tools(
        records
    )

    assert response.success
    assert "текст введён" in (
        response.speech_text.lower()
    )

    # Голосовой итог не должен перечислять весь техлог.
    assert len(response.speech_text) < 200


def test_failed_tool_makes_response_failed() -> None:
    records = [
        create_record(
            "open_application",
            ToolResult.failure(
                "APPLICATION_NOT_FOUND",
                "Приложение не найдено.",
            ),
        )
    ]

    response = build_assistant_response_from_tools(
        records
    )

    assert not response.success
    assert (
        response.error_code
        == "ONE_OR_MORE_TOOLS_FAILED"
    )
    assert "не найдено" in (
        response.speech_text.lower()
    )


def test_budget_exhaustion_is_reported() -> None:
    records = [
        create_record(
            "get_current_time",
            ToolResult.ok(
                "Время получено.",
            ),
        )
    ]

    response = build_assistant_response_from_tools(
        records,
        budget_exhausted=True,
    )

    assert not response.success
    assert (
        response.error_code
        == "AGENT_BUDGET_EXHAUSTED"
    )
    assert "лимит" in response.speech_text.lower()


def test_verified_result_is_marked() -> None:
    records = [
        create_record(
            "create_workspace_project",
            ToolResult.ok(
                "Проект создан.",
                verification=VerificationResult(
                    verified=True,
                    method="filesystem_readback",
                    confidence=1.0,
                ),
            ),
        )
    ]

    summary = build_tool_execution_summary(
        records
    )

    assert summary.success
    assert "[проверено]" in summary.display_text
    assert summary.unverified_count == 0


def test_unverified_result_is_counted() -> None:
    records = [
        create_record(
            "type_text",
            ToolResult.ok(
                "Текст отправлен.",
            ),
        )
    ]

    summary = build_tool_execution_summary(
        records
    )

    assert summary.success
    assert summary.unverified_count == 1
    assert (
        "без дополнительной проверки"
        in summary.display_text
    )


def test_reporting_does_not_need_llm() -> None:
    """
    Сам факт синхронного вызова подтверждает, что reporting не
    обращается к NovaLLM и не требует event loop.
    """
    records = [
        create_record(
            "set_reminder",
            ToolResult.ok(
                "Напоминание установлено.",
            ),
        )
    ]

    response = build_assistant_response_from_tools(
        records
    )

    assert response.success
    assert (
        response.speech_text
        == "Сэр, напоминание установлено."
    )


def test_english_reporting_does_not_leak_russian_wrapper_text() -> None:
    records = [
        create_record(
            "write_in_application",
            ToolResult.ok(
                "Текст введён в приложение.",
                verification=VerificationResult(
                    verified=True,
                    method="readback",
                    confidence=1.0,
                ),
            ),
        )
    ]

    response = build_assistant_response_from_tools(
        records,
        language="en",
    )

    assert response.success
    assert "Completed — Write in application" in response.display_text
    assert "[verified]" in response.display_text
    assert "The application is open" in response.speech_text
