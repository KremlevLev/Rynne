# modules/ui/premium_desktop.py
"""
Новый премиальный Desktop UI для Nova.

Это entry point для нового UI, который:
  - использует AppShell с sidebar, workspace и context panel;
  - подписывается на существующие события через event bus;
  - отправляет команды через существующие интерфейсы;
  - не содержит логики агента;
  - не делает прямых вызовов к провайдерам, MCP или базе.

Старый desktop.py сохраняется как fallback за feature flag.
"""
from __future__ import annotations

import queue
import sys
from typing import Any

from PySide6.QtCore import Qt

from modules.ui.desktop_protocol import make_command
from modules.ui.theme import theme
from modules.ui.shell import AppShell
from modules.ui.chat import ChatView, ChatMessage, Composer, ToolActivityCard
from modules.ui.orb import NovaOrb, VoiceOverlay
from modules.ui.command_palette import CommandPalette, Command
from modules.ui.task_view import TaskView
from modules.ui.primitives import EmptyState, Button


def run_premium_desktop(
    *,
    event_queue,
    command_queue,
) -> None:
    """
    Точка входа для нового премиального Desktop UI.

    Подписывается на события из event_queue и отображает их
    через новые компоненты. Команды отправляются в command_queue.
    """
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return

    app = QApplication(sys.argv)

    # Применяем design tokens
    theme.set_mode("dark")

    # Создаём AppShell
    shell = AppShell()
    shell.show()
    shell.raise_()
    shell.activateWindow()

    # --- Центральный экран: чат ---
    chat_view = ChatView()
    composer = Composer(
        on_submit=lambda text, opts: _submit_request(
            command_queue, text, opts
        ),
        on_voice_toggle=lambda: _toggle_voice(command_queue),
    )

    chat_container = shell.workspace
    chat_container.addWidget(chat_view)

    # --- Task View (скрыт пока нет активной задачи) ---
    task_view = TaskView(
        on_pause=lambda: _send_command(command_queue, "pause_task"),
        on_cancel=lambda: _send_command(command_queue, "cancel_task"),
        on_approve=lambda: _send_command(command_queue, "approve_task"),
    )
    chat_container.addWidget(task_view)
    # QStackedWidget управляет видимостью сам; setCurrentWidget
    # переключает между chat_view и task_view.
    chat_container.setCurrentWidget(chat_view)

    # Добавляем composer в центральный layout (внизу, под чатом)
    shell._center_layout.setStretchFactor(shell.workspace, 1)
    shell._center_layout.addWidget(composer)

    # --- Command Palette ---
    palette = CommandPalette()
    shell.overlay_layout.addWidget(palette)
    palette.hide()
    _register_palette_commands(palette, shell, command_queue)

    # --- Voice Overlay ---
    voice_overlay = VoiceOverlay(
        on_stop=lambda: _send_command(command_queue, "cancel_current_request")
    )
    shell.overlay_layout.addWidget(voice_overlay)
    shell.overlay_layout.setAlignment(voice_overlay, Qt.AlignBottom | Qt.AlignHCenter)
    voice_overlay.hide()

    # --- Event loop ---
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
    )


def _submit_request(
    command_queue: queue.Queue,
    text: str,
    options: dict[str, Any],
) -> None:
    """Отправляет запрос пользователя через command_queue."""
    _send_command(
        command_queue,
        "submit_user_request",
        {
            "text": text,
            "profile": options.get("profile", "assistant"),
            "model_mode": options.get("model_mode", "auto"),
        },
    )


def _toggle_voice(command_queue: queue.Queue) -> None:
    """Переключает голосовой режим."""
    _send_command(command_queue, "toggle_voice_mode")


def _send_command(
    command_queue: queue.Queue,
    action: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Отправляет команду в command_queue."""
    command = make_command(action, payload)
    try:
        command_queue.put_nowait(command)
    except queue.Full:
        pass


def _register_palette_commands(
    palette: CommandPalette,
    shell: AppShell,
    command_queue: queue.Queue,
) -> None:
    """Регистрирует команды в command palette."""
    palette.add_commands([
        Command(
            "Новая задача",
            category="Session",
            hotkey="Ctrl+N",
            icon="✚",
            callback=lambda: _send_command(command_queue, "new_task"),
        ),
        Command(
            "Начать голосовой режим",
            category="Voice",
            hotkey="Ctrl+Shift+Space",
            icon="🎙",
            callback=lambda: _send_command(command_queue, "toggle_voice_mode"),
        ),
        Command(
            "Открыть настройки",
            category="General",
            hotkey="Ctrl+,",
            icon="⚙",
            callback=lambda: _send_command(command_queue, "open_settings"),
        ),
        Command(
            "Переключить модель",
            category="Models",
            icon="🤖",
            callback=lambda: _send_command(command_queue, "switch_model"),
        ),
        Command(
            "Пауза активной задачи",
            category="Task",
            icon="⏸",
            callback=lambda: _send_command(command_queue, "pause_task"),
        ),
        Command(
            "Отменить активную задачу",
            category="Task",
            icon="⏹",
            callback=lambda: _send_command(command_queue, "cancel_task"),
        ),
        Command(
            "Открыть MCP менеджер",
            category="Integrations",
            icon="🔌",
            callback=lambda: _send_command(command_queue, "open_mcp_manager"),
        ),
        Command(
            "Открыть диагностику",
            category="Advanced",
            icon="📊",
            callback=lambda: _send_command(command_queue, "open_diagnostics"),
        ),
    ])


def _run_event_loop(
    *,
    app: Any,
    shell: AppShell,
    chat_view: ChatView,
    composer: Composer,
    task_view: TaskView,
    palette: CommandPalette,
    voice_overlay: VoiceOverlay,
    event_queue: queue.Queue,
    command_queue: queue.Queue,
) -> None:
    """Главный event loop — обрабатывает события из event_queue."""
    from PySide6.QtCore import QTimer, QTimer as _QTimer

    def process_events() -> None:
        for _ in range(100):
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
            )

    timer = QTimer(app)
    timer.timeout.connect(process_events)
    timer.start(50)

    # Горячие клавиши
    from PySide6.QtGui import QShortcut, QKeySequence

    # Ctrl+K — command palette
    shortcut = QShortcut(QKeySequence("Ctrl+K"), shell)
    shortcut.activated.connect(palette.show_palette)

    # Ctrl+, — настройки
    settings_shortcut = QShortcut(QKeySequence("Ctrl+,"), shell)
    settings_shortcut.activated.connect(
        lambda: _send_command(command_queue, "open_settings")
    )

    # Ctrl+N — новая задача
    new_task_shortcut = QShortcut(QKeySequence("Ctrl+N"), shell)
    new_task_shortcut.activated.connect(
        lambda: _send_command(command_queue, "new_task")
    )

    # Ctrl+Enter — отправить
    send_shortcut = QShortcut(QKeySequence("Ctrl+Return"), shell)
    send_shortcut.activated.connect(composer._on_send_clicked)

    # Ctrl+Shift+Space — голосовой overlay
    voice_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Space"), shell)
    voice_shortcut.activated.connect(
        lambda: voice_overlay.show_overlay()
    )

    app.exec()


def _handle_event(
    event: dict[str, Any],
    *,
    shell: AppShell,
    chat_view: ChatView,
    composer: Composer,
    task_view: TaskView,
    palette: CommandPalette,
    voice_overlay: VoiceOverlay,
    command_queue: queue.Queue | None = None,
) -> None:
    """Обрабатывает одно событие из event_queue."""
    event_type = event.get("event_type", "")
    payload = event.get("payload", {})

    if event_type == "shutdown":
        shell.close()
        return

    if event_type == "runtime":
        state = str(payload.get("state", "НЕИЗВЕСТНО"))
        active = payload.get("active", False)

        state_labels = {
            "SLEEPING": ("offline", "Спит"),
            "LISTENING": ("active", "Слушает"),
            "THINKING": ("active", "Думает"),
            "WORKING": ("active", "Работает"),
            "SPEAKING": ("active", "Говорит"),
            "ERROR": ("danger", "Ошибка"),
        }
        status, label = state_labels.get(state, ("idle", state))
        shell.set_status(status, label)

        # Обновляем voice overlay
        if state == "LISTENING":
            voice_overlay.show_overlay()
            voice_overlay.set_state("listening")
        elif state == "THINKING":
            voice_overlay.set_state("thinking")
        elif state == "WORKING":
            voice_overlay.set_state("working")
        elif state == "SPEAKING":
            voice_overlay.set_state("speaking")
        elif state == "SLEEPING":
            voice_overlay.hide_overlay()

    elif event_type == "user_message":
        msg = ChatMessage(
            author="Вы",
            text=str(payload.get("text", "")),
            is_user=True,
            timestamp=_format_time(payload),
            status="sent",
        )
        chat_view.add_message(msg)

    elif event_type == "assistant_message":
        msg = ChatMessage(
            author="Nova",
            text=str(payload.get("display_text", "")),
            is_user=False,
            timestamp=_format_time(payload),
            status="sent",
        )
        chat_view.add_message(msg)

        # Добавляем действия
        if payload.get("success"):
            msg.add_action("Открыть", lambda: None)
        else:
            def _retry() -> None:
                if command_queue is not None:
                    _send_command(
                        command_queue, "retry_last"
                    )
            msg.add_action("Повторить", _retry)

    elif event_type == "tool_started":
        # Добавляем ToolActivityCard в чат
        tool_name = str(payload.get("tool_name", ""))
        description = str(payload.get("description", ""))
        card = ToolActivityCard(
            tool_name=tool_name,
            description=description or tool_name,
            status="active",
        )
        chat_view.add_widget(card)

    elif event_type == "tool_completed":
        # Обновляем последнюю ToolActivityCard
        if chat_view._messages:
            last_msg = chat_view._messages[-1]
            if last_msg._artifacts:
                last_artifact = last_msg._artifacts[-1]
                if isinstance(last_artifact, ToolActivityCard):
                    last_artifact.set_status("success")
                    last_artifact.set_duration(
                        str(payload.get("duration", ""))
                    )
                    last_artifact.set_details(
                        str(payload.get("result", ""))
                    )

    elif event_type == "task_started":
        # Переключаемся на task_view (если shell имеет workspace)
        if hasattr(shell, "workspace"):
            shell.workspace.setCurrentWidget(task_view)
        task_view.show()
        task_view.set_title(str(payload.get("title", "Новая задача")))
        task_view.set_status("active", "Выполняется")
        task_view.set_task_id(str(payload.get("task_id", "")))

        plan = payload.get("plan", [])
        for step in plan:
            task_view.add_plan_step(
                str(step.get("text", "")),
                status=step.get("status", "pending"),
            )

    elif event_type == "task_progress":
        plan = payload.get("plan", [])
        for i, step in enumerate(plan):
            task_view.set_step_status(
                i, step.get("status", "pending")
            )

        # Добавляем событие в timeline
        task_view.add_timeline_event(
            _format_time(payload),
            str(payload.get("description", "")),
            status=payload.get("status", "completed"),
        )

    elif event_type == "task_completed":
        task_view.set_status("success", "Завершена")
        task_view.add_timeline_event(
            _format_time(payload),
            "Задача завершена",
            status="success",
        )

    elif event_type == "task_failed":
        task_view.set_status("danger", "Ошибка")
        task_view.add_timeline_event(
            _format_time(payload),
            f"Ошибка: {payload.get('error', '')}",
            status="failed",
        )

    elif event_type == "approval_requested":
        task_view.show_approval(
            title="Nova просит разрешение",
            description=str(payload.get("description", "")),
            details=str(payload.get("details", "")),
        )

    elif event_type == "processes":
        # Обновляем список процессов в task_view или context_panel
        items = payload.get("items", [])
        if hasattr(task_view, "_processes"):
            task_view._processes = items

    elif event_type == "memories":
        # Обновляем список воспоминаний
        items = payload.get("items", [])
        if hasattr(task_view, "_memories"):
            task_view._memories = items

    elif event_type == "permissions":
        # Показываем pending permissions
        items = payload.get("items", [])
        if items:
            task_view.show()
            shell.workspace.setCurrentWidget(task_view)
            first = items[0]
            task_view.show_approval(
                title="Nova просит разрешение",
                description=str(first.get("message", "")),
                details=(
                    f"Инструмент: {first.get('tool_name', '')}\n"
                    f"Риск: {first.get('risk', '')}\n"
                    f"Категория: {first.get('category', '')}"
                ),
            )

    elif event_type == "command_result":
        # Логируем результат команды
        msg = ChatMessage(
            author="Система",
            text=f"Команда: {payload.get('message', '')}",
            is_user=False,
            timestamp=_format_time(payload),
            status="sent",
        )
        chat_view.add_message(msg)

    elif event_type == "preferences":
        # Обновляем UI из preferences
        pass

    elif event_type == "models":
        # Обновляем статус модели
        active_provider = payload.get("active_provider", "")
        active_model = payload.get("active_model", "")
        if not active_provider and not active_model:
            # Fallback: попробуем извлечь из вложенных структур
            providers = payload.get("providers", {})
            if isinstance(providers, dict):
                for prov_name, prov_data in providers.items():
                    if isinstance(prov_data, dict) and prov_data.get("active"):
                        active_provider = prov_name
                        active_model = prov_data.get("model", "")
                        break
        shell.set_model(f"{active_provider}: {active_model}")


def _format_time(payload: dict[str, Any]) -> str:
    """Форматирует время из payload."""
    import time

    ts = payload.get("created_at", time.time())
    return time.strftime("%H:%M:%S", time.localtime(ts))
