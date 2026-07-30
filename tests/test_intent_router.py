# tests/test_intent_router.py
from __future__ import annotations

from modules.input_hub.models import (
    Attachment,
    AttachmentType,
    UserRequest,
)
from modules.routing.decision import (
    ExecutionStrategy,
    IntentKind,
)
from modules.routing.intent import (
    DeterministicIntentRouter,
)


def create_router() -> DeterministicIntentRouter:
    return DeterministicIntentRouter()


def test_chat_request() -> None:
    decision = create_router().route(
        "Привет"
    )

    assert (
        decision.strategy
        == ExecutionStrategy.CHAT
    )
    assert decision.intent == IntentKind.CHAT
    assert decision.expected_model_calls == 1
    assert not decision.needs_tools


def test_open_application_is_direct() -> None:
    decision = create_router().route(
        "Открой блокнот"
    )

    assert (
        decision.strategy
        == ExecutionStrategy.DIRECT
    )
    assert (
        decision.intent
        == IntentKind.APPLICATION_OPEN
    )
    assert decision.needs_model is False
    assert decision.required_tools == {
        "open_application"
    }


def test_write_in_application_uses_one_skill() -> None:
    decision = create_router().route(
        (
            "Открой Obsidian и напиши "
            "стих о космосе"
        )
    )

    assert (
        decision.strategy
        == ExecutionStrategy.SKILL
    )
    assert (
        decision.intent
        == IntentKind.APPLICATION_WRITE
    )
    assert decision.selected_skill == (
        "write_in_application"
    )
    assert decision.required_tools == {
        "write_in_application"
    }
    assert decision.expected_model_calls == 1
    assert decision.expected_tool_calls == 1


def test_write_without_topic_requires_clarification() -> None:
    decision = create_router().route(
        "Напиши в Obsidian"
    )

    assert (
        decision.strategy
        == ExecutionStrategy.CLARIFY
    )
    assert decision.needs_clarification
    assert (
        decision.clarification_question
        is not None
    )


def test_launch_all_applications_requires_clarification() -> None:
    decision = create_router().route(
        "Запусти все приложения, которые можешь"
    )

    assert (
        decision.strategy
        == ExecutionStrategy.CLARIFY
    )
    assert (
        decision.intent
        == IntentKind.APPLICATION_BATCH
    )
    assert decision.expected_model_calls == 0


def test_launch_application_range_uses_bounded_batch_tool() -> None:
    decision = create_router().route(
        "Запусти 5-10 приложений на моём компьютере"
    )

    assert decision.strategy == ExecutionStrategy.DIRECT
    assert decision.intent == IntentKind.APPLICATION_BATCH
    assert decision.selected_skill == "open_application_batch"
    assert decision.arguments == {"count": 5}
    assert decision.required_tools == {"open_application_batch"}
    assert decision.expected_model_calls == 0


def test_time_is_direct() -> None:
    decision = create_router().route(
        "Который час?"
    )

    assert (
        decision.strategy
        == ExecutionStrategy.DIRECT
    )
    assert decision.required_tools == {
        "get_current_time"
    }
    assert decision.expected_model_calls == 0


def test_model_selection_is_local() -> None:
    decision = create_router().route(
        "Переключись на быструю модель"
    )

    assert (
        decision.intent
        == IntentKind.MODEL_SELECTION
    )
    assert (
        decision.strategy
        == ExecutionStrategy.DIRECT
    )
    assert not decision.needs_model


def test_mode_selection_is_local() -> None:
    decision = create_router().route(
        "Включи приватный режим"
    )

    assert (
        decision.intent
        == IntentKind.MODE_SELECTION
    )
    assert not decision.needs_model


def test_complex_development_request_uses_plan() -> None:
    decision = create_router().route(
        (
            "Сначала проверь проект, затем "
            "запусти тесты и исправь ошибки"
        )
    )

    assert (
        decision.strategy
        == ExecutionStrategy.PLAN
    )
    assert (
        decision.intent
        == IntentKind.DEVELOPMENT
    )
    assert decision.needs_model
    assert decision.needs_tools


def test_image_request_uses_vision() -> None:
    request = UserRequest.from_text(
        "Что здесь?",
        attachments=[
            Attachment(
                attachment_type=(
                    AttachmentType.SCREENSHOT
                ),
                path="screen.png",
            )
        ],
    )

    decision = create_router().route(
        request
    )

    assert decision.intent == IntentKind.VISION
    assert decision.needs_model
    assert decision.needs_tools


def test_browser_request_uses_browser_tools() -> None:
    decision = create_router().route(
        "Открой сайт и прочитай страницу"
    )

    assert decision.intent == IntentKind.WEB
    assert "browser_open_url" in (
        decision.required_tools
    )


def test_unknown_action_uses_one_skill_turn() -> None:
    decision = create_router().route(
        "Сделай что-нибудь полезное"
    )

    assert (
        decision.strategy
        == ExecutionStrategy.SKILL
    )
    assert decision.expected_model_calls == 1


def test_file_check_is_not_misclassified_as_chat() -> None:
    decision = create_router().route(
        "Проверь этот файл и найди ошибку"
    )

    assert decision.intent != IntentKind.CHAT
    assert decision.needs_tools
def test_run_tests_is_not_application_open() -> None:
    decision = create_router().route(
        "Запусти тесты"
    )

    assert (
        decision.intent
        == IntentKind.DEVELOPMENT
    )
    assert (
        decision.strategy
        != ExecutionStrategy.DIRECT
    )


def test_open_site_is_not_application_open() -> None:
    decision = create_router().route(
        "Открой сайт example.com"
    )

    assert decision.intent == IntentKind.WEB
    assert (
        decision.strategy
        == ExecutionStrategy.SKILL
    )
    assert "browser_open_url" in (
        decision.required_tools
    )


def test_open_browser_is_application_open() -> None:
    decision = create_router().route(
        "Открой браузер"
    )

    assert (
        decision.intent
        == IntentKind.APPLICATION_OPEN
    )
    assert (
        decision.strategy
        == ExecutionStrategy.DIRECT
    )
    assert decision.arguments[
        "app_name"
    ] == "браузер"


def test_openrouter_goal_is_web_not_application_launch() -> None:
    decision = create_router().route(
        "Включи OpenRouter и посмотри там мою активность"
    )

    assert decision.intent == IntentKind.WEB
    assert decision.strategy == ExecutionStrategy.SKILL
    assert "browser_open_url" in decision.required_tools


def test_browser_with_follow_up_goal_is_not_direct() -> None:
    decision = create_router().route(
        (
            "Включи браузер а в нём OpenRouter "
            "там чекни мою активность"
        )
    )

    assert decision.intent == IntentKind.WEB
    assert decision.strategy == ExecutionStrategy.SKILL
    assert decision.needs_tools


def test_open_project_is_development_not_app() -> None:
    decision = create_router().route(
        "Открой проект и запусти тесты"
    )

    assert (
        decision.intent
        == IntentKind.DEVELOPMENT
    )


def test_multi_step_development_expected_calls_are_bounded() -> None:
    decision = create_router().route(
        (
            "Сначала проверь проект, затем "
            "запусти тесты и исправь ошибки"
        )
    )

    assert (
        decision.expected_model_calls
        <= 2
    )
    assert (
        decision.expected_tool_calls
        <= 4
    )
