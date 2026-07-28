"""Современный Desktop UI Nova.

Модуль остаётся тонким presentation layer: получает сериализуемые события
от CoreDesktopBridge и отправляет команды обратно через multiprocessing queue.
"""
from __future__ import annotations

import queue
import sys
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication

from modules.ui.chat import (
    ArtifactCard,
    ChatMessage,
    ChatView,
    Composer,
    ToolActivityCard,
)
from modules.ui.command_palette import Command, CommandPalette
from modules.ui.control_center import (
    IntegrationsPage,
    MemoryPage,
    ProcessesPage,
    SettingsPage,
)
from modules.ui.desktop_protocol import make_command
from modules.ui.orb import VoiceOverlay
from modules.ui.shell import AppShell
from modules.ui.task_view import TaskView
from modules.ui.theme import theme


def run_premium_desktop(*, event_queue, command_queue) -> None:
    """Запускает UI-процесс и связывает реальные экраны с IPC-командами."""
    app = QApplication(sys.argv)
    app.setApplicationName("Nova")
    app.setOrganizationName("Nova")
    app.setFont(QFont("Segoe UI", 10))
    theme.set_mode("dark")

    state: dict[str, Any] = {
        "activity_cards": {},
        "seen_requests": set(),
        "permission_id": "",
        "active_task_id": "",
    }

    shell = AppShell()
    chat_view = ChatView()
    composer = Composer(
        on_submit=lambda text, options: _submit_request(
            command_queue, text, options
        ),
        on_voice_toggle=lambda: _toggle_voice(command_queue),
    )
    task_view = TaskView(
        on_pause=lambda: _send_task_command(
            command_queue, "pause_task", state
        ),
        on_cancel=lambda: _send_task_command(
            command_queue, "cancel_task", state
        ),
        on_approve=lambda: _approve_permission(command_queue, state),
        on_deny=lambda: _deny_permission(command_queue, state),
    )
    processes_page = ProcessesPage()
    memory_page = MemoryPage()
    integrations_page = IntegrationsPage()
    settings_page = SettingsPage()

    shell.add_workspace_screen(
        "chat",
        chat_view,
        title="Диалог",
        subtitle="Поставьте задачу — Nova сама выберет оркестратор и инструменты",
    )
    shell.add_workspace_screen(
        "tasks",
        task_view,
        title="Задачи",
        subtitle="План, прогресс и действия активного оркестратора",
    )
    shell.add_workspace_screen(
        "processes",
        processes_page,
        title="Процессы",
        subtitle="Фоновые процессы, которыми управляет Nova",
    )
    shell.add_workspace_screen(
        "memory",
        memory_page,
        title="Память",
        subtitle="Факты, доступные агенту между сессиями",
    )
    shell.add_workspace_screen(
        "integrations",
        integrations_page,
        title="MCP-интеграции",
        subtitle="Реальные серверы и зарегистрированные инструменты",
    )
    shell.add_workspace_screen(
        "settings",
        settings_page,
        title="Настройки",
        subtitle="Профиль, модель, приватность и поведение Nova",
    )
    shell.show_screen("chat")
    shell._center_layout.addWidget(composer)

    palette = CommandPalette()
    shell.overlay_layout.addWidget(palette)
    palette.hide()
    _register_palette_commands(palette, shell, command_queue, composer)

    voice_overlay = VoiceOverlay(
        on_stop=lambda: _send_command(command_queue, "cancel_current_request")
    )
    shell.overlay_layout.addWidget(voice_overlay)
    shell.overlay_layout.setAlignment(
        voice_overlay, Qt.AlignBottom | Qt.AlignHCenter
    )
    voice_overlay.hide()

    chat_view.starter_selected.connect(
        lambda prompt: (composer.set_text(prompt), composer.focus_input())
    )
    shell.new_task_requested.connect(
        lambda: _start_new_task(shell, chat_view, task_view, composer, command_queue)
    )
    shell.navigate.connect(
        lambda section: _on_navigate(section, command_queue)
    )
    processes_page.stop_requested.connect(
        lambda process_id, force: _send_command(
            command_queue,
            "stop_process",
            {"process_id": process_id, "force": force},
        )
    )
    processes_page.refresh_requested.connect(
        lambda: _send_command(command_queue, "refresh")
    )
    memory_page.delete_requested.connect(
        lambda key: _send_command(
            command_queue, "delete_memory", {"key": key}
        )
    )
    memory_page.clear_requested.connect(
        lambda: _send_command(command_queue, "clear_memories")
    )
    integrations_page.refresh_requested.connect(
        lambda: _send_command(command_queue, "refresh")
    )
    settings_page.preference_changed.connect(
        lambda key, value: _send_command(
            command_queue,
            "set_preference",
            {"key": key, "value": value},
        )
    )

    shell.show()
    shell.raise_()
    shell.activateWindow()
    composer.focus_input()

    _install_shortcuts(
        shell=shell,
        composer=composer,
        palette=palette,
        voice_overlay=voice_overlay,
        command_queue=command_queue,
    )
    _run_event_loop(
        app=app,
        shell=shell,
        chat_view=chat_view,
        composer=composer,
        task_view=task_view,
        palette=palette,
        voice_overlay=voice_overlay,
        event_queue=event_queue,
        command_queue=command_queue,
        processes_page=processes_page,
        memory_page=memory_page,
        integrations_page=integrations_page,
        settings_page=settings_page,
        state=state,
    )


def _submit_request(
    command_queue: queue.Queue,
    text: str,
    options: dict[str, Any],
) -> None:
    _send_command(
        command_queue,
        "submit_user_request",
        {
            "text": text,
            "profile": options.get("profile", "assistant"),
            "model_mode": options.get("model_mode", "auto"),
            "selected_model": options.get("selected_model"),
            "attachments": options.get("attachments", []),
        },
    )


def _toggle_voice(command_queue: queue.Queue) -> None:
    _send_command(command_queue, "toggle_voice_mode")


def _send_command(
    command_queue: queue.Queue,
    action: str,
    payload: dict[str, Any] | None = None,
) -> None:
    command = make_command(action, payload)
    try:
        command_queue.put_nowait(command)
    except queue.Full:
        return


def _send_task_command(
    command_queue: queue.Queue,
    action: str,
    state: dict[str, Any],
) -> None:
    _send_command(
        command_queue,
        action,
        {"task_id": str(state.get("active_task_id", ""))},
    )


def _approve_permission(
    command_queue: queue.Queue,
    state: dict[str, Any],
) -> None:
    operation_id = str(state.get("permission_id", ""))
    if operation_id:
        _send_command(
            command_queue,
            "confirm_permission",
            {"operation_id": operation_id},
        )


def _deny_permission(
    command_queue: queue.Queue,
    state: dict[str, Any],
) -> None:
    operation_id = str(state.get("permission_id", ""))
    if operation_id:
        _send_command(
            command_queue,
            "deny_permission",
            {"operation_id": operation_id},
        )


def _start_new_task(
    shell: AppShell,
    chat_view: ChatView,
    task_view: TaskView,
    composer: Composer,
    command_queue: queue.Queue,
) -> None:
    chat_view.clear()
    task_view.clear()
    shell.sidebar.activate("chat")
    shell.context_panel.hide_panel()
    composer.set_disabled(False)
    composer.set_mode("Safe autonomy")
    composer.focus_input()
    _send_command(command_queue, "new_task")


def _on_navigate(section: str, command_queue: queue.Queue) -> None:
    if section in {"processes", "memory", "integrations", "settings", "tasks"}:
        _send_command(command_queue, "refresh")


def _register_palette_commands(
    palette: CommandPalette,
    shell: AppShell,
    command_queue: queue.Queue,
    composer: Composer | None = None,
) -> None:
    def show(key: str) -> None:
        shell.sidebar.activate(key)

    palette.add_commands(
        [
            Command(
                "Новая задача",
                category="Session",
                hotkey="Ctrl+N",
                icon="+",
                callback=lambda: shell.new_task_requested.emit(),
            ),
            Command(
                "Открыть диалог",
                category="Navigation",
                icon="⌁",
                callback=lambda: show("chat"),
            ),
            Command(
                "Открыть задачи",
                category="Navigation",
                icon="✓",
                callback=lambda: show("tasks"),
            ),
            Command(
                "Открыть процессы",
                category="Navigation",
                icon="▣",
                callback=lambda: show("processes"),
            ),
            Command(
                "Открыть память",
                category="Navigation",
                icon="◇",
                callback=lambda: show("memory"),
            ),
            Command(
                "Открыть MCP-интеграции",
                category="Navigation",
                icon="↗",
                callback=lambda: show("integrations"),
            ),
            Command(
                "Открыть настройки",
                category="Navigation",
                hotkey="Ctrl+,",
                icon="⚙",
                callback=lambda: show("settings"),
            ),
            Command(
                "Переключить голосовой режим",
                category="Voice",
                hotkey="Ctrl+Shift+Space",
                icon="◎",
                callback=lambda: _send_command(
                    command_queue, "toggle_voice_mode"
                ),
            ),
            Command(
                "Отменить текущий запрос",
                category="Task",
                icon="×",
                callback=lambda: _send_command(
                    command_queue, "cancel_current_request"
                ),
            ),
        ]
    )


def _install_shortcuts(
    *,
    shell: AppShell,
    composer: Composer,
    palette: CommandPalette,
    voice_overlay: VoiceOverlay,
    command_queue: queue.Queue,
) -> None:
    shortcuts: list[QShortcut] = []

    def bind(sequence: str, callback) -> None:
        shortcut = QShortcut(QKeySequence(sequence), shell)
        shortcut.activated.connect(callback)
        shortcuts.append(shortcut)

    bind("Ctrl+K", palette.show_palette)
    bind("Ctrl+,", lambda: shell.sidebar.activate("settings"))
    bind("Ctrl+N", shell.new_task_requested.emit)
    bind("Ctrl+Return", composer._on_send_clicked)
    bind(
        "Ctrl+Shift+Space",
        # Глобальный keyboard hook в main.py выполняет переключение режима.
        # Локальный QShortcut только показывает overlay: иначе одно физическое
        # нажатие при активном окне Nova отправляло toggle дважды.
        voice_overlay.show_overlay,
    )
    bind(
        "Escape",
        lambda: (
            palette.hide(),
            voice_overlay.hide_overlay(),
        ),
    )
    shell._nova_shortcuts = shortcuts


def _run_event_loop(
    *,
    app: QApplication,
    shell: AppShell,
    chat_view: ChatView,
    composer: Composer,
    task_view: TaskView,
    palette: CommandPalette,
    voice_overlay: VoiceOverlay,
    event_queue: queue.Queue,
    command_queue: queue.Queue,
    processes_page: ProcessesPage,
    memory_page: MemoryPage,
    integrations_page: IntegrationsPage,
    settings_page: SettingsPage,
    state: dict[str, Any],
) -> None:
    def process_events() -> None:
        for _ in range(120):
            try:
                event = event_queue.get_nowait()
            except queue.Empty:
                break
            except (BrokenPipeError, EOFError, OSError):
                break
            if not isinstance(event, dict):
                continue
            _handle_event(
                event,
                shell=shell,
                chat_view=chat_view,
                composer=composer,
                task_view=task_view,
                palette=palette,
                voice_overlay=voice_overlay,
                command_queue=command_queue,
                processes_page=processes_page,
                memory_page=memory_page,
                integrations_page=integrations_page,
                settings_page=settings_page,
                state=state,
            )

    timer = QTimer(app)
    timer.timeout.connect(process_events)
    timer.start(50)
    app._nova_event_timer = timer
    app.exec()


def _handle_event(
    event: dict[str, Any],
    *,
    shell: Any,
    chat_view: Any,
    composer: Any,
    task_view: Any,
    palette: Any,
    voice_overlay: Any,
    command_queue: queue.Queue | None = None,
    processes_page: ProcessesPage | None = None,
    memory_page: MemoryPage | None = None,
    integrations_page: IntegrationsPage | None = None,
    settings_page: SettingsPage | None = None,
    state: dict[str, Any] | None = None,
) -> None:
    """Применяет одно backend-событие к UI.

    Дополнительные экраны optional, чтобы mapping можно было тестировать
    без поднятия полного окна.
    """
    del palette
    state = state if state is not None else {}
    activity_cards: dict[str, ToolActivityCard] = state.setdefault(
        "activity_cards", {}
    )
    seen_requests: set[str] = state.setdefault("seen_requests", set())
    event_type = str(event.get("event_type", ""))
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}

    if event_type == "shutdown":
        shell.close()
        return

    if event_type == "runtime":
        runtime_state = str(payload.get("state", "UNKNOWN"))
        status_map = {
            "SLEEPING": ("offline", "Спит"),
            "LISTENING": ("active", "Слушает"),
            "THINKING": ("active", "Думает"),
            "WORKING": ("active", "Работает"),
            "SPEAKING": ("active", "Говорит"),
            "ERROR": ("danger", "Ошибка"),
        }
        status, label = status_map.get(runtime_state, ("idle", "Готова"))
        shell.set_status(status, label)
        if runtime_state == "LISTENING":
            voice_overlay.show_overlay()
            voice_overlay.set_state("listening")
            if hasattr(composer, "set_voice_state"):
                composer.set_voice_state(True, listening=True)
        elif runtime_state in {"THINKING", "WORKING", "SPEAKING"}:
            voice_overlay.set_state(runtime_state.lower())
        elif runtime_state == "SLEEPING":
            voice_overlay.hide_overlay()
            if hasattr(composer, "set_voice_state"):
                composer.set_voice_state(False)
        return

    if event_type == "request_started":
        request_id = str(payload.get("request_id", ""))
        text = str(payload.get("text", ""))
        if request_id and request_id not in seen_requests:
            seen_requests.add(request_id)
            chat_view.add_message(
                ChatMessage(
                    author="Вы",
                    text=text,
                    is_user=True,
                    timestamp=_format_time(payload),
                    status="в очереди",
                )
            )
        if hasattr(composer, "set_mode"):
            composer.set_mode("Nova работает…")
        if hasattr(shell, "show_screen"):
            shell.show_screen("chat")
        return

    if event_type == "request_cancelled":
        if hasattr(composer, "set_mode"):
            composer.set_mode("Запрос отменён")
        return

    if event_type == "request_failed":
        if hasattr(composer, "set_mode"):
            composer.set_mode("Ошибка выполнения")
        chat_view.add_message(
            ChatMessage(
                author="Nova",
                text=str(payload.get("error", "Запрос завершился ошибкой.")),
                is_user=False,
                timestamp=_format_time(payload),
                status="ошибка",
            )
        )
        return

    if event_type == "user_message":
        request_id = str(payload.get("request_id", ""))
        if request_id and request_id in seen_requests:
            return
        if request_id:
            seen_requests.add(request_id)
        chat_view.add_message(
            ChatMessage(
                author="Вы",
                text=str(payload.get("text", "")),
                is_user=True,
                timestamp=_format_time(payload),
                status="отправлено",
            )
        )
        return

    if event_type == "assistant_message":
        success = bool(payload.get("success", True))
        message = ChatMessage(
            author="Nova",
            text=str(payload.get("display_text", "")),
            is_user=False,
            timestamp=_format_time(payload),
            status="готово" if success else "ошибка",
        )
        if not success and command_queue is not None:
            message.add_action(
                "Повторить",
                lambda: _send_command(command_queue, "retry_last"),
            )
        _add_artifacts(message, payload, command_queue)
        chat_view.add_message(message)
        if hasattr(composer, "set_mode"):
            composer.set_mode("Safe autonomy")
        return

    if event_type == "proactive_suggestion":
        message_text = str(payload.get("message", "")).strip()
        reason = str(payload.get("reason", "")).strip()
        if reason:
            message_text = f"{message_text}\n\nПочему: {reason}"
        chat_view.add_message(
            ChatMessage(
                author="Nova",
                text=message_text,
                is_user=False,
                timestamp=_format_time(payload),
                status="предложение",
            )
        )
        if hasattr(shell, "show_screen"):
            shell.show_screen("chat")
        return

    if event_type == "tool_started":
        operation_id = str(
            payload.get("operation_id")
            or payload.get("tool_call_id")
            or f"tool-{len(activity_cards)}"
        )
        tool_name = str(payload.get("tool_name", "tool"))
        card = ToolActivityCard(
            tool_name=tool_name,
            description=str(payload.get("description") or _humanize_tool(tool_name)),
            status="active",
        )
        details = payload.get("details")
        if details:
            card.set_details(str(details))
        activity_cards[operation_id] = card
        chat_view.add_widget(card)
        return

    if event_type == "tool_completed":
        operation_id = str(
            payload.get("operation_id")
            or payload.get("tool_call_id")
            or ""
        )
        card = activity_cards.get(operation_id)
        if card is None:
            tool_name = str(payload.get("tool_name", "tool"))
            card = ToolActivityCard(
                tool_name=tool_name,
                description=_humanize_tool(tool_name),
            )
            chat_view.add_widget(card)
        success = bool(payload.get("success", True))
        card.set_status("success" if success else "danger")
        duration_ms = payload.get("duration_ms")
        if duration_ms is not None:
            card.set_duration(f"{int(duration_ms)} мс")
        card.set_details(str(payload.get("message") or payload.get("result") or ""))
        return

    if event_type == "task_started":
        state["active_task_id"] = str(payload.get("task_id", ""))
        if hasattr(task_view, "clear"):
            task_view.clear()
        if hasattr(shell, "show_screen"):
            shell.show_screen("tasks")
        task_view.show()
        task_view.set_title(str(payload.get("title", "Новая задача")))
        task_view.set_status("active", "Выполняется")
        task_view.set_task_id(state["active_task_id"])
        for step in payload.get("plan", []):
            if isinstance(step, dict):
                task_view.add_plan_step(
                    str(step.get("text", "")),
                    status=str(step.get("status", "pending")),
                )
        return

    if event_type == "task_progress":
        for index, step in enumerate(payload.get("plan", [])):
            if isinstance(step, dict):
                task_view.set_step_status(
                    index, str(step.get("status", "pending"))
                )
        task_view.add_timeline_event(
            _format_time(payload),
            str(payload.get("description", "Обновлён прогресс задачи")),
            status=str(payload.get("status", "completed")),
        )
        return

    if event_type in {"task_completed", "task_failed", "task_cancelled"}:
        if event_type == "task_completed":
            task_view.set_status("success", "Завершена")
            description = "Задача завершена"
            status = "success"
        elif event_type == "task_cancelled":
            task_view.set_status("offline", "Отменена")
            description = "Задача отменена"
            status = "skipped"
        else:
            task_view.set_status("danger", "Ошибка")
            description = f"Ошибка: {payload.get('error', '')}"
            status = "failed"
        task_view.add_timeline_event(
            _format_time(payload), description, status=status
        )
        return

    if event_type in {"approval_requested", "permissions"}:
        permission = payload
        if event_type == "permissions":
            items = payload.get("items", [])
            if not items:
                if hasattr(shell, "set_badge"):
                    shell.set_badge("tasks", 0)
                return
            permission = items[0] if isinstance(items[0], dict) else {}
            if hasattr(shell, "set_badge"):
                shell.set_badge("tasks", len(items))
        operation_id = str(permission.get("operation_id", ""))
        state["permission_id"] = operation_id
        if hasattr(shell, "show_screen"):
            shell.show_screen("tasks")
        task_view.show_approval(
            title="Nova просит разрешение",
            description=str(
                permission.get("description")
                or permission.get("message")
                or "Подтвердите действие."
            ),
            details=_permission_details(permission),
        )
        return

    if event_type == "processes":
        items = payload.get("items", [])
        if processes_page is not None:
            processes_page.set_items(items if isinstance(items, list) else [])
        if hasattr(shell, "set_badge"):
            running = sum(
                1
                for item in items
                if isinstance(item, dict) and item.get("is_running")
            )
            shell.set_badge("processes", running)
        return

    if event_type == "memories":
        items = payload.get("items", [])
        if memory_page is not None:
            memory_page.set_items(items if isinstance(items, list) else [])
        if hasattr(shell, "set_badge"):
            shell.set_badge("memory", len(items) if isinstance(items, list) else 0)
        return

    if event_type == "integrations":
        items = payload.get("items", [])
        if integrations_page is not None:
            integrations_page.set_items(
                items if isinstance(items, list) else []
            )
        if hasattr(shell, "set_badge"):
            connected = sum(
                1
                for item in items
                if isinstance(item, dict) and int(item.get("tools_count", 0) or 0) > 0
            )
            shell.set_badge("integrations", connected)
        return

    if event_type == "preferences":
        if settings_page is not None:
            settings_page.set_preferences(payload)
        if hasattr(composer, "set_mode"):
            profile = str(payload.get("assistant_profile", "assistant"))
            mode = str(payload.get("model_mode", "auto"))
            composer.set_mode(f"{profile} · {mode}")
        return

    if event_type == "models":
        shell.set_model(_model_label(payload))
        return

    if event_type == "command_result":
        if not bool(payload.get("success", False)):
            chat_view.add_message(
                ChatMessage(
                    author="Система",
                    text=str(payload.get("message", "Команда не выполнена.")),
                    is_user=False,
                    timestamp=_format_time(payload),
                    status="ошибка",
                )
            )


def _add_artifacts(
    message: ChatMessage,
    payload: dict[str, Any],
    command_queue: queue.Queue | None,
) -> None:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        data = payload.get("data", {})
        artifacts = data.get("artifacts", []) if isinstance(data, dict) else []
    for item in artifacts:
        path = str(item.get("path", "")) if isinstance(item, dict) else str(item)
        if not path:
            continue
        card = ArtifactCard(
            title=Path(path).name or path,
            artifact_type="file",
            subtitle=path,
            on_open=(
                (lambda target=path: _send_command(
                    command_queue, "open_artifact", {"path": target}
                ))
                if command_queue is not None
                else None
            ),
        )
        message.add_artifact(card)


def _permission_details(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    for label, key in (
        ("Инструмент", "tool_name"),
        ("Риск", "risk"),
        ("Категория", "category"),
        ("Операция", "operation_id"),
    ):
        value = payload.get(key)
        if value:
            lines.append(f"{label}: {value}")
    details = payload.get("details")
    if details:
        lines.append(str(details))
    return "\n".join(lines)


def _model_label(payload: dict[str, Any]) -> str:
    active_provider = str(payload.get("active_provider", ""))
    active_model = str(payload.get("active_model", ""))
    if active_provider or active_model:
        return ": ".join(filter(None, (active_provider, active_model)))
    for provider, data in payload.items():
        if not isinstance(data, dict):
            continue
        model = data.get("active_model") or data.get("model")
        if data.get("active") or model:
            return ": ".join(filter(None, (str(provider), str(model or ""))))
    return "auto"


def _humanize_tool(name: str) -> str:
    aliases = {
        "read_text_file": "Читает файл",
        "write_text_file": "Изменяет файл",
        "apply_text_patch": "Применяет патч",
        "run_terminal_command": "Выполняет команду",
        "search_web_tavily": "Ищет источники",
        "browser_open_url": "Открывает страницу",
        "execute_plan": "Запускает план",
        "start_background_plan": "Запускает фоновую задачу",
    }
    return aliases.get(name, name.replace("_", " ").strip().capitalize())


def _format_time(payload: dict[str, Any]) -> str:
    timestamp = payload.get("created_at", time.time())
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(timestamp)))
    except (TypeError, ValueError, OSError):
        return time.strftime("%H:%M:%S")
