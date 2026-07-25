# tests/test_ui_state_mapping.py
"""
Тесты для state-to-UI mapping.

Проверяют, что события из backend корректно отображаются в UI:
  - runtime state → sidebar status
  - user_message → chat message
  - assistant_message → chat message
  - task_started → task view
  - task_progress → plan + timeline
  - task_completed → success
  - approval_requested → approval card
"""
from __future__ import annotations

import queue
import time

import pytest

from modules.ui.theme import theme
from modules.ui.premium_desktop import _handle_event, _format_time
from modules.ui.command_palette import Command, CommandPalette


class _FakeShell:
    """Фиктивный AppShell для тестов."""

    def __init__(self) -> None:
        self.status = None
        self.model = None

    def set_status(self, status: str, label: str = "") -> None:
        self.status = (status, label)

    def set_model(self, model_name: str) -> None:
        self.model = model_name


class _FakeChatView:
    """Фиктивный ChatView для тестов."""

    def __init__(self) -> None:
        self.messages: list = []

    def add_message(self, msg) -> None:
        self.messages.append(msg)


class _FakeComposer:
    pass


class _FakeTaskView:
    """Фиктивный TaskView для тестов."""

    def __init__(self) -> None:
        self.title = ""
        self.status = None
        self.task_id = None
        self.plan_steps: list = []
        self.timeline_events: list = []
        self.approval_shown = False
        self.approval_title = ""
        self.approval_desc = ""
        self.shown = False
        self.hidden = False

    def show(self) -> None:
        self.shown = True

    def hide(self) -> None:
        self.hidden = True

    def set_title(self, title: str) -> None:
        self.title = title

    def set_status(self, status: str, label: str = "") -> None:
        self.status = (status, label)

    def set_task_id(self, task_id: str) -> None:
        self.task_id = task_id

    def set_step_status(self, index: int, status: str) -> None:
        pass

    def add_plan_step(self, text: str, status: str = "pending"):
        self.plan_steps.append((text, status))

    def add_timeline_event(self, time_str, desc, *, status="completed", details=""):
        self.timeline_events.append((time_str, desc, status, details))

    def show_approval(self, title, description, *, details=""):
        self.approval_shown = True
        self.approval_title = title
        self.approval_desc = description

    class _PlanView:
        def set_step_status(self, index, status):
            pass

    _plan_view = _PlanView()


class _FakePalette:
    pass


class _FakeVoiceOverlay:
    def __init__(self) -> None:
        self.visible = False
        self.state = None

    def show_overlay(self) -> None:
        self.visible = True

    def hide_overlay(self) -> None:
        self.visible = False

    def set_state(self, state: str) -> None:
        self.state = state


class TestStateToUIMapping:
    """Тесты state-to-UI mapping."""

    def _make_event(self, event_type: str, payload: dict | None = None) -> dict:
        return {
            "event_type": event_type,
            "payload": payload or {},
            "created_at": time.time(),
        }

    def test_runtime_sleeping(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("runtime", {"state": "SLEEPING", "active": False}),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert shell.status == ("offline", "Спит")
        assert voice.visible is False

    def test_runtime_listening(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("runtime", {"state": "LISTENING", "active": True}),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert shell.status == ("active", "Слушает")
        assert voice.visible is True
        assert voice.state == "listening"

    def test_runtime_thinking(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("runtime", {"state": "THINKING", "active": True}),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert shell.status == ("active", "Думает")
        assert voice.state == "thinking"

    def test_runtime_working(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("runtime", {"state": "WORKING", "active": True}),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert shell.status == ("active", "Работает")
        assert voice.state == "working"

    def test_runtime_speaking(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("runtime", {"state": "SPEAKING", "active": True}),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert shell.status == ("active", "Говорит")
        assert voice.state == "speaking"

    def test_runtime_error(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("runtime", {"state": "ERROR", "active": False}),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert shell.status == ("danger", "Ошибка")

    def test_user_message(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("user_message", {"text": "Привет!"}),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert len(chat.messages) == 1
        msg = chat.messages[0]
        assert msg._text == "Привет!"
        assert msg._is_user is True

    def test_assistant_message_success(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("assistant_message", {
                "display_text": "Готово!",
                "success": True,
            }),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert len(chat.messages) == 1
        msg = chat.messages[0]
        assert msg._text == "Готово!"
        assert msg._is_user is False

    def test_assistant_message_failure(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("assistant_message", {
                "display_text": "Ошибка",
                "success": False,
            }),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert len(chat.messages) == 1
        msg = chat.messages[0]
        assert msg._text == "Ошибка"

    def test_task_started(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("task_started", {
                "title": "Исследование MCP",
                "task_id": "task_123",
                "plan": [
                    {"text": "Собрать источники", "status": "completed"},
                    {"text": "Проверить документацию", "status": "active"},
                    {"text": "Создать заметку", "status": "pending"},
                ],
            }),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert task.shown is True
        assert task.title == "Исследование MCP"
        assert task.status == ("active", "Выполняется")
        assert task.task_id == "task_123"
        assert len(task.plan_steps) == 3

    def test_task_progress(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        # Сначала стартуем задачу
        _handle_event(
            self._make_event("task_started", {
                "title": "Тест",
                "task_id": "task_1",
                "plan": [
                    {"text": "Шаг 1", "status": "pending"},
                    {"text": "Шаг 2", "status": "pending"},
                ],
            }),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        # Затем обновляем прогресс
        _handle_event(
            self._make_event("task_progress", {
                "plan": [
                    {"text": "Шаг 1", "status": "completed"},
                    {"text": "Шаг 2", "status": "active"},
                ],
                "description": "Выполняю шаг 2",
            }),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert len(task.timeline_events) == 1
        assert task.timeline_events[0][1] == "Выполняю шаг 2"

    def test_task_completed(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("task_completed", {}),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert task.status == ("success", "Завершена")
        assert len(task.timeline_events) == 1
        assert task.timeline_events[0][2] == "success"

    def test_task_failed(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("task_failed", {"error": "Таймаут"}),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert task.status == ("danger", "Ошибка")
        assert len(task.timeline_events) == 1
        assert "Таймаут" in task.timeline_events[0][1]

    def test_approval_requested(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("approval_requested", {
                "description": "Отправить письмо 3 получателям?",
                "details": "Кому: alice@example.com",
            }),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert task.approval_shown is True
        assert "письмо" in task.approval_desc

    def test_models_event(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        _handle_event(
            self._make_event("models", {
                "active_provider": "groq",
                "active_model": "llama-3.1-8b-instant",
            }),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert shell.model == "groq: llama-3.1-8b-instant"

    def test_shutdown_event(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        closed = []
        shell.close = lambda: closed.append(True)

        _handle_event(
            self._make_event("shutdown", {}),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

        assert closed == [True]

    def test_unknown_event_type(self) -> None:
        shell = _FakeShell()
        chat = _FakeChatView()
        composer = _FakeComposer()
        task = _FakeTaskView()
        palette = _FakePalette()
        voice = _FakeVoiceOverlay()

        # Не должно падать
        _handle_event(
            self._make_event("unknown_event", {}),
            shell=shell, chat_view=chat, composer=composer,
            task_view=task, palette=palette, voice_overlay=voice,
        )

    def test_format_time(self) -> None:
        payload = {"created_at": time.time()}
        result = _format_time(payload)
        assert len(result) == 8  # HH:MM:SS
        assert result.count(":") == 2

    def test_format_time_missing(self) -> None:
        payload = {}
        result = _format_time(payload)
        assert len(result) == 8


class TestApprovalActions:
    """Тесты для approval actions."""

    def test_approval_show_hide(self) -> None:
        from modules.ui.task_view import TaskView

        approvals: list[str] = []

        task = TaskView(
            on_approve=lambda: approvals.append("approved"),
            on_cancel=lambda: approvals.append("cancelled"),
        )

        task.show_approval(
            title="Тест",
            description="Подтвердить действие?",
        )

        assert task._approval_card is not None
        assert approvals == []

        # Имитируем одобрение
        task._on_approve_clicked()
        assert approvals == ["approved"]
        assert task._approval_card is None

    def test_approval_reject(self) -> None:
        from modules.ui.task_view import TaskView

        approvals: list[str] = []

        task = TaskView(
            on_approve=lambda: approvals.append("approved"),
        )

        task.show_approval(
            title="Тест",
            description="Подтвердить?",
        )

        task._on_reject_approval()
        assert task._approval_card is None
        assert approvals == []

    def test_approval_replace(self) -> None:
        from modules.ui.task_view import TaskView

        task = TaskView()

        task.show_approval("Первый", "Первое подтверждение")
        first_card = task._approval_card
        assert first_card is not None

        task.show_approval("Второй", "Второе подтверждение")
        assert task._approval_card is not None
        assert task._approval_card is not first_card


class TestTaskLifecycle:
    """Тесты для task lifecycle."""

    def test_plan_step_status_transitions(self) -> None:
        from modules.ui.task_view import PlanStep

        step = PlanStep("Тестовый шаг", status="pending")

        step.set_status("active")
        assert step._status == "active"

        step.set_status("completed")
        assert step._status == "completed"

        step.set_status("failed")
        assert step._status == "failed"

        step.set_status("skipped")
        assert step._status == "skipped"

    def test_plan_view_add_and_clear(self) -> None:
        from modules.ui.task_view import PlanView

        plan = PlanView()
        plan.add_step("Шаг 1", "pending")
        plan.add_step("Шаг 2", "pending")
        assert len(plan._steps) == 2

        plan.clear()
        assert len(plan._steps) == 0

    def test_timeline_add_and_clear(self) -> None:
        from modules.ui.task_view import TimelineView, TimelineEvent

        timeline = TimelineView()
        event1 = TimelineEvent("10:00", "Действие 1", status="completed")
        event2 = TimelineEvent("10:01", "Действие 2", status="completed")

        timeline.add_event(event1)
        timeline.add_event(event2)
        assert len(timeline._events) == 2

        timeline.clear()
        assert len(timeline._events) == 0

    def test_task_view_clear(self) -> None:
        from modules.ui.task_view import TaskView

        task = TaskView()
        task.add_plan_step("Шаг 1")
        task.add_timeline_event("10:00", "Событие")
        task.show_approval("Тест", "Подтверждение")

        task.clear()
        assert len(task._plan_view._steps) == 0
        assert len(task._timeline._events) == 0
        assert task._approval_card is None


class TestCleanupSubscriptions:
    """Тесты для cleanup subscriptions."""

    def test_command_palette_clear(self) -> None:
        palette = CommandPalette()
        palette.add_command(Command("Команда 1"))
        palette.add_command(Command("Команда 2"))
        assert len(palette._commands) == 2

        palette.clear()
        assert len(palette._commands) == 0
        assert len(palette._filtered) == 0

    def test_command_palette_fuzzy_filter(self) -> None:
        palette = CommandPalette()
        palette.add_command(Command("Новая задача"))
        palette.add_command(Command("Открыть настройки"))
        palette.add_command(Command("Отменить задачу"))

        results = palette._fuzzy_filter("задач")
        assert len(results) == 2  # "Новая задача" и "Отменить задачу"

    def test_command_palette_empty_filter(self) -> None:
        palette = CommandPalette()
        palette.add_command(Command("Команда 1"))
        palette.add_command(Command("Команда 2"))

        results = palette._fuzzy_filter("")
        assert len(results) == 2
