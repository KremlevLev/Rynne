# tests/test_ui_smoke.py
"""
Smoke test для нового UI.

Проверяет, что все модули UI можно импортировать без ошибок
(без запуска Qt-приложения).
"""
from __future__ import annotations

import pytest


class TestUISmoke:
    """Smoke tests для UI-модулей."""

    def test_import_theme(self) -> None:
        from modules.ui.theme import Theme, theme
        assert isinstance(theme, Theme)

    def test_import_primitives(self) -> None:
        from modules.ui.primitives import (
            Button,
            IconButton,
            Input,
            Card,
            Badge,
            StatusIndicator,
            AnimationLayer,
            ReducedMotionMixin,
        )
        # Проверяем, что классы существуют
        assert Button is not None
        assert IconButton is not None
        assert Input is not None
        assert Card is not None
        assert Badge is not None
        assert StatusIndicator is not None
        assert AnimationLayer is not None
        assert ReducedMotionMixin is not None

    def test_import_shell(self) -> None:
        from modules.ui.shell import (
            AppShell,
            Sidebar,
            SidebarItem,
            ContextPanel,
        )
        assert AppShell is not None
        assert Sidebar is not None
        assert SidebarItem is not None
        assert ContextPanel is not None

    def test_import_chat(self) -> None:
        from modules.ui.chat import (
            ChatMessage,
            ChatView,
            Composer,
            ToolActivityCard,
            ErrorCard,
            ArtifactCard,
        )
        assert ChatMessage is not None
        assert ChatView is not None
        assert Composer is not None
        assert ToolActivityCard is not None
        assert ErrorCard is not None
        assert ArtifactCard is not None

    def test_import_orb(self) -> None:
        from modules.ui.orb import NovaOrb, VoiceOverlay
        assert NovaOrb is not None
        assert VoiceOverlay is not None

    def test_import_command_palette(self) -> None:
        from modules.ui.command_palette import (
            CommandPalette,
            Command,
        )
        assert CommandPalette is not None
        assert Command is not None

    def test_import_task_view(self) -> None:
        from modules.ui.task_view import (
            TaskView,
            PlanView,
            PlanStep,
            TimelineView,
            TimelineEvent,
        )
        assert TaskView is not None
        assert PlanView is not None
        assert PlanStep is not None
        assert TimelineView is not None
        assert TimelineEvent is not None

    def test_import_premium_desktop(self) -> None:
        from modules.ui.premium_desktop import (
            run_premium_desktop,
            _handle_event,
            _submit_request,
            _send_command,
            _format_time,
        )
        assert run_premium_desktop is not None
        assert _handle_event is not None
        assert _submit_request is not None
        assert _send_command is not None
        assert _format_time is not None

    def test_import_desktop_service_premium(self) -> None:
        from modules.ui.desktop_service import (
            DesktopService,
            _desktop_process_entry,
        )
        assert DesktopService is not None
        assert _desktop_process_entry is not None

    def test_theme_tokens_consistent(self) -> None:
        """Проверяет, что токены theme согласованы."""
        from modules.ui.theme import (
            DARK_COLORS,
            LIGHT_COLORS,
            RADIUS,
            SPACING,
            FONT_SIZES,
            DURATIONS,
            EASING,
            SHADOWS,
        )

        # Все цвета должны быть строками
        for key, value in DARK_COLORS.items():
            assert isinstance(value, str), f"Color {key} is not str"

        # Radius должен содержать нужные ключи
        for key in ["sm", "md", "lg", "xl", "pill"]:
            assert key in RADIUS

        # Spacing должен содержать нужные ключи
        for key in ["xs", "sm", "md", "lg", "xl"]:
            assert key in SPACING

        # Durations
        for key in ["micro", "hover", "panel", "orbLoop"]:
            assert key in DURATIONS

        # Easing
        assert "easeOut" in EASING
        assert "easeInOut" in EASING

    def test_send_command_creates_valid_command(self) -> None:
        """Проверяет, что _send_command создаёт валидную команду."""
        import queue
        from modules.ui.premium_desktop import _send_command
        from modules.ui.desktop_protocol import validate_command

        q: queue.Queue = queue.Queue()
        _send_command(q, "test_action", {"key": "value"})

        command = q.get_nowait()
        valid, error = validate_command(command)
        assert valid is True
        assert error is None
        assert command["action"] == "test_action"
        assert command["payload"]["key"] == "value"

#    def test_command_palette_commands(self) -> None:
#        """Проверяет, что command palette регистрирует команды."""
#        from modules.ui.command_palette import CommandPalette, Command
#
#        palette = CommandPalette()
#        palette.add_command(Command("Test 1"))
#        palette.add_command(Command("Test 2"))
#        assert len(palette._commands) == 2

#    def test_chat_message_creation(self) -> None:
#        """Проверяет создание сообщения чата."""
#        from modules.ui.chat import ChatMessage
#
#        msg = ChatMessage(
#            author="Nova",
#            text="Привет!",
#            is_user=False,
#        )
#        assert msg._text == "Привет!"
#        assert msg._is_user is False
#
#        msg.set_text("Обновлённый текст")
#        assert msg._text == "Обновлённый текст"

#    def test_task_view_creation(self) -> None:
#        """Проверяет создание task view."""
#        from modules.ui.task_view import TaskView
#
#        task = TaskView()
#        assert task._task_id is None
#
#        task.set_title("Тестовая задача")
#        assert task.title == "Тестовая задача"
#
#        step = task.add_plan_step("Шаг 1", "pending")
#        assert step._status == "pending"
#
#        task.add_timeline_event("10:00", "Событие")
#        assert len(task._timeline._events) == 1

#    def test_nova_orb_state(self) -> None:
#        """Проверяет управление состоянием орба."""
#        from modules.ui.orb import NovaOrb
#
#        # Создаём орб без Qt (без show)
#        orb = NovaOrb(size=24)
#        assert orb.get_state() == "idle"
#
#        orb.set_state("listening")
#        assert orb.get_state() == "listening"
#
#        orb.set_mic_level(0.5)
#        assert orb._mic_level == 0.5

    def test_all_ui_modules_importable(self) -> None:
        """Проверяет, что все UI-модули можно импортировать."""
        import modules.ui.theme
        import modules.ui.primitives
        import modules.ui.shell
        import modules.ui.chat
        import modules.ui.orb
        import modules.ui.command_palette
        import modules.ui.task_view
        import modules.ui.premium_desktop
        import modules.ui.desktop_service

        assert modules.ui.theme is not None
        assert modules.ui.primitives is not None
        assert modules.ui.shell is not None
        assert modules.ui.chat is not None
        assert modules.ui.orb is not None
        assert modules.ui.command_palette is not None
        assert modules.ui.task_view is not None
        assert modules.ui.premium_desktop is not None
        assert modules.ui.desktop_service is not None
