# modules/ui/core_bridge.py
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from modules.tools.permissions import (
    PermissionManager,
)
from modules.ui.desktop_protocol import (
    DesktopTransport,
    validate_command,
)
from modules.application.preferences import (
    PreferencesManager,
)
from modules.input_hub.coordinator import (
    InputCoordinator,
)
from modules.input_hub.models import (
    AssistantProfile,
    Attachment,
    AttachmentType,
    ModelSelectionMode,
    RequestSource,
)


logger = logging.getLogger("CoreDesktopBridge")


class CoreDesktopBridge:
    """
    Передаёт состояние Nova в UI и маршрутизирует команды UI.
    """

    def __init__(
        self,
        *,
        desktop: DesktopTransport,
        process_manager,
        memory_store,
        mode_manager=None,
        permission_manager: PermissionManager,
        llm,
        runtime,
        input_coordinator: (
            InputCoordinator | None
        ) = None,
        preferences: (
            PreferencesManager | None
        ) = None,
        cancel_current_request=None,
        plan_service=None,
        background_plan_manager=None,
        mcp_gateway=None,
        proactive_context_store=None,
    ) -> None:
        self.desktop = desktop
        self.process_manager = (
            process_manager
        )
        self.memory_store = memory_store
        self.permission_manager = (
            permission_manager
        )
        self.llm = llm
        self.runtime = runtime
        self.mode_manager = mode_manager

        self.input_coordinator = (
            input_coordinator
        )
        self.preferences = preferences
        self.cancel_current_request = (
            cancel_current_request
        )
        self.plan_service = plan_service
        self.background_plan_manager = (
            background_plan_manager
        )
        self.mcp_gateway = mcp_gateway
        self.proactive_context_store = (
            proactive_context_store
        )
        self._last_submission: dict[str, Any] | None = None
        self._reported_plan_ids: set[str] = set()
        self._reported_bg_ids: set[str] = set()
        self._reported_completed_ids: set[str] = set()
        self._plan_fingerprints: dict[str, tuple[str, ...]] = {}
        self._bg_fingerprints: dict[str, str] = {}

    def _preferences_payload(self, snapshot=None) -> dict[str, Any]:
        current = snapshot or (
            self.preferences.snapshot()
            if self.preferences is not None
            else None
        )
        payload = current.to_dict() if current is not None else {}
        if self.mode_manager is not None:
            payload["wake_word_available"] = bool(
                getattr(
                    self.mode_manager,
                    "wake_word_available",
                    False,
                )
            )
            wake_runtime = getattr(self.mode_manager, "wake_runtime", None)
            detector = getattr(wake_runtime, "detector", None)
            config = getattr(detector, "config", None)
            payload["wake_word"] = str(
                getattr(config, "wake_word", "нова")
            )
        return payload


    async def run(
        self,
        shutdown_event: asyncio.Event,
    ) -> None:
        # The desktop shell must receive a handshake before optional snapshots
        # touch process enumeration, memory storage, models or integrations.
        self._publish_runtime()

        while not shutdown_event.is_set():
            try:
                await self.publish_snapshots()

                for command in (
                    self.desktop.get_commands()
                ):
                    await self.handle_command(
                        command
                    )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Ошибка DesktopBridge."
                )

            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=0.5,
                )
            except asyncio.TimeoutError:
                pass

    async def publish_snapshots(self) -> None:
        process_result = await asyncio.to_thread(
            self.process_manager.list_processes
        )

        process_data = (
            process_result.data.get(
                "processes",
                [],
            )
            if process_result.success
            else []
        )
        if self.preferences is not None:
            self.desktop.publish(
                "preferences",
                self._preferences_payload(),
            )


        memory_data = await asyncio.to_thread(
            self.memory_store.search,
            "",
            limit=200,
        )

        permission_data = (
            self.permission_manager.pending_requests()
        )

        model_data = self.llm.provider_health()

        self._publish_runtime()

        self.desktop.publish(
            "processes",
            {
                "items": process_data,
            },
        )

        self.desktop.publish(
            "memories",
            {
                "items": memory_data,
            },
        )

        self.desktop.publish(
            "permissions",
            {
                "items": permission_data,
            },
        )

        self.desktop.publish(
            "models",
            model_data,
        )
        self.desktop.publish(
            "integrations",
            {
                "items": self._integration_snapshot(),
            },
        )

        # Публикуем события жизненного цикла задач
        if self.plan_service is not None:
            for plan_id, plan in self.plan_service._plans.items():
                if plan_id not in self._reported_plan_ids:
                    self._reported_plan_ids.add(plan_id)
                    self.desktop.publish(
                        "task_started",
                        {
                            "task_id": plan_id,
                            "title": plan.goal,
                            "plan": [
                                {"text": s.description, "status": "pending"}
                                for s in plan.steps
                            ],
                        },
                    )
                else:
                    statuses = tuple(
                        (
                            s.status.value
                            if hasattr(s.status, "value")
                            else str(s.status)
                        )
                        for s in plan.steps
                    )
                    if self._plan_fingerprints.get(plan_id) != statuses:
                        self._plan_fingerprints[plan_id] = statuses
                        self.desktop.publish(
                            "task_progress",
                            {
                                "task_id": plan_id,
                                "plan": [
                                    {
                                        "text": s.description,
                                        "status": status,
                                    }
                                    for s, status in zip(
                                        plan.steps, statuses
                                    )
                                ],
                                "description": plan.goal,
                            },
                        )

        if self.background_plan_manager is not None:
            for bg_id, bg_plan in self.background_plan_manager._plans.items():
                if bg_id not in self._reported_bg_ids:
                    self._reported_bg_ids.add(bg_id)
                    self.desktop.publish(
                        "task_started",
                        {
                            "task_id": bg_id,
                            "title": bg_plan.goal,
                            "plan": [
                                {"text": s.get("description", ""), "status": "pending"}
                                for s in bg_plan.steps
                            ],
                        },
                    )
                else:
                    status = (
                        bg_plan.status.value
                        if hasattr(bg_plan.status, "value")
                        else str(bg_plan.status)
                    )
                    if self._bg_fingerprints.get(bg_id) != status:
                        self._bg_fingerprints[bg_id] = status
                        self.desktop.publish(
                            "task_progress",
                            {
                                "task_id": bg_id,
                                "plan": [],
                                "description": (
                                    f"{bg_plan.goal} · {status}"
                                ),
                                "status": status,
                            },
                        )

        # Публикуем события завершения/отмены задач
        completed_ids = set()
        if self.plan_service is not None:
            completed_ids = self.plan_service._get_completed_plan_ids()
        for completed_id in completed_ids:
            if completed_id not in self._reported_completed_ids:
                self._reported_completed_ids.add(completed_id)
                self.desktop.publish(
                    "task_completed",
                    {
                        "task_id": completed_id,
                    },
                )
        if self.background_plan_manager is not None:
            for bg_id, bg_plan in self.background_plan_manager._plans.items():
                status = (
                    bg_plan.status.value
                    if hasattr(bg_plan.status, "value")
                    else str(bg_plan.status)
                )
                if (
                    status in {"completed", "failed", "cancelled"}
                    and bg_id not in self._reported_completed_ids
                ):
                    self._reported_completed_ids.add(bg_id)
                    event_type = {
                        "completed": "task_completed",
                        "failed": "task_failed",
                        "cancelled": "task_cancelled",
                    }[status]
                    self.desktop.publish(
                        event_type,
                        {
                            "task_id": bg_id,
                            "error": str(bg_plan.error or ""),
                        },
                    )

    def _publish_runtime(self) -> None:
        self.desktop.publish(
            "runtime",
            {
                "state": self.runtime.state.value,
                "active": self.runtime.is_active,
                "shutting_down": self.runtime.is_shutting_down,
            },
        )

    def _integration_snapshot(
        self,
    ) -> list[dict[str, Any]]:
        """Возвращает безопасный MCP snapshot без env и секретов."""
        gateway = self.mcp_gateway
        if gateway is None:
            return []

        servers = getattr(gateway, "_servers", {})
        available = set(
            gateway.get_available_tools()
            if hasattr(gateway, "get_available_tools")
            else []
        )
        items: list[dict[str, Any]] = []
        for name, config in servers.items():
            prefix = f"mcp_{name}_"
            count = sum(
                1
                for tool_name in available
                if str(tool_name).startswith(prefix)
            )
            items.append(
                {
                    "name": str(name),
                    "enabled": bool(
                        getattr(config, "enabled", True)
                    ),
                    "transport": str(
                        getattr(config, "transport", "stdio")
                    ),
                    "tools_count": count,
                    "url": (
                        str(getattr(config, "url", ""))
                        if getattr(config, "url", None)
                        else ""
                    ),
                }
            )
        return items

    async def handle_command(
        self,
        command: dict[str, Any],
    ) -> None:
        logger.info(
            "Получена команда Desktop UI: action=%s command_id=%s",
            command.get("action"),
            command.get("command_id"),
        )

        valid, error = validate_command(
            command
        )
        command_id = str(
            command.get(
                "command_id",
                "unknown",
            )
        )

        if not valid:
            self._publish_command_result(
                command_id,
                success=False,
                message=error or "Некорректная команда.",
            )
            return

        action = command["action"]
        payload = command.get(
            "payload",
            {},
        )
        if action == "retry_last":
            if self._last_submission is None:
                self._publish_command_result(
                    command_id,
                    success=False,
                    message="Нет предыдущего запроса для повтора.",
                )
                return
            action = "submit_user_request"
            payload = dict(self._last_submission)
        if action == "set_input_mode":
            if self.mode_manager is None:
                self._publish_command_result(
                    command_id,
                    success=False,
                    message=(
                        "Менеджер режимов "
                        "не подключён."
                    ),
                )
                return
            mode_name = str(
                payload.get(
                    "input_mode",
                    "",
                )
            )
            try:
                snapshot = (
                    await self.mode_manager
                    .set_mode_from_string(
                        mode_name
                    )
                )
            except ValueError as exc:
                self._publish_command_result(
                    command_id,
                    success=False,
                    message=str(exc),
                )
                return
            self.desktop.publish(
                "preferences",
                self._preferences_payload(snapshot),
            )
            self._publish_command_result(
                command_id,
                success=True,
                message=(
                    f"Режим переключён: "
                    f"{snapshot.input_mode.value}."
                ),
            )
            return

        if action == "set_preference":
            if self.preferences is None:
                self._publish_command_result(
                    command_id,
                    success=False,
                    message="Менеджер настроек не подключён.",
                )
                return
            key = str(payload.get("key", ""))
            value = payload.get("value")
            try:
                if key == "assistant_profile":
                    snapshot = self.preferences.set_assistant_profile(
                        AssistantProfile(str(value))
                    )
                elif key == "model_mode":
                    snapshot = self.preferences.set_model_mode(
                        ModelSelectionMode(str(value)),
                        selected_model=(
                            str(payload.get("selected_model"))
                            if payload.get("selected_model")
                            else None
                        ),
                    )
                elif key == "tts_enabled":
                    snapshot = self.preferences.set_tts_enabled(bool(value))
                elif key == "cloud_enabled":
                    snapshot = self.preferences.set_cloud_enabled(bool(value))
                elif key == "history_enabled":
                    snapshot = self.preferences.set_history_enabled(bool(value))
                elif key == "proactive_vision_enabled":
                    snapshot = (
                        self.preferences
                        .set_proactive_vision_enabled(
                            bool(value)
                        )
                    )
                else:
                    raise ValueError(
                        f"Неизвестная настройка: {key}"
                    )
            except (TypeError, ValueError) as exc:
                self._publish_command_result(
                    command_id,
                    success=False,
                    message=str(exc),
                )
                return
            self.desktop.publish(
                "preferences",
                self._preferences_payload(snapshot),
            )
            self._publish_command_result(
                command_id,
                success=True,
                message=f"Настройка {key} обновлена.",
            )
            return

        try:
            if action == "refresh":
                await self.publish_snapshots()

                self._publish_command_result(
                    command_id,
                    success=True,
                    message="Данные обновлены.",
                )
                return

            if action == "stop_process":
                process_id = str(
                    payload.get("process_id", "")
                )

                result = await asyncio.to_thread(
                    self.process_manager.stop_process,
                    process_id,
                    force=bool(
                        payload.get(
                            "force",
                            False,
                        )
                    ),
                )

                self._publish_tool_result(
                    command_id,
                    result,
                )
                return

            if action == "delete_memory":
                key = str(
                    payload.get("key", "")
                )

                success = await asyncio.to_thread(
                    self.memory_store.delete,
                    key,
                )

                self._publish_command_result(
                    command_id,
                    success=bool(success),
                    message=(
                        f"Факт '{key}' удалён."
                        if success
                        else
                        f"Не удалось удалить '{key}'."
                    ),
                )
                return

            if action == "clear_memories":
                success = await asyncio.to_thread(
                    self.memory_store.clear_all
                )

                self._publish_command_result(
                    command_id,
                    success=bool(success),
                    message=(
                        "Память очищена."
                        if success
                        else
                        "Не удалось очистить память."
                    ),
                )
                return

            if action == "confirm_permission":
                operation_id = str(
                    payload.get(
                        "operation_id",
                        "",
                    )
                )

                success = (
                    self.permission_manager.confirm(
                        operation_id
                    )
                )

                self._publish_command_result(
                    command_id,
                    success=success,
                    message=(
                        "Операция разрешена."
                        if success
                        else
                        "Запрос разрешения не найден."
                    ),
                )
                return

            if action == "deny_permission":
                operation_id = str(
                    payload.get(
                        "operation_id",
                        "",
                    )
                )

                success = (
                    self.permission_manager.deny(
                        operation_id
                    )
                )

                self._publish_command_result(
                    command_id,
                    success=success,
                    message=(
                        "Операция запрещена."
                        if success
                        else
                        "Запрос разрешения не найден."
                    ),
                )
                return
            if action == "submit_user_request":
                if (
                    self.input_coordinator
                    is None
                ):
                    self._publish_command_result(
                        command_id,
                        success=False,
                        message=(
                            "InputCoordinator "
                            "не подключён."
                        ),
                    )
                    return

                text = str(
                    payload.get(
                        "text",
                        "",
                    )
                ).strip()

                if not text:
                    self._publish_command_result(
                        command_id,
                        success=False,
                        message=(
                            "Текст запроса пуст."
                        ),
                    )
                    return

                profile_raw = str(
                    payload.get(
                        "profile",
                        AssistantProfile.ASSISTANT.value,
                    )
                )

                model_mode_raw = str(
                    payload.get(
                        "model_mode",
                        ModelSelectionMode.AUTO.value,
                    )
                )

                try:
                    profile = AssistantProfile(
                        profile_raw
                    )
                except ValueError:
                    profile = (
                        AssistantProfile.ASSISTANT
                    )

                try:
                    model_mode = (
                        ModelSelectionMode(
                            model_mode_raw
                        )
                    )
                except ValueError:
                    model_mode = (
                        ModelSelectionMode.AUTO
                    )

                attachments: list[Attachment] = []
                proactive_context_path: str | None = None
                raw_attachments = payload.get(
                    "attachments",
                    [],
                )
                if isinstance(raw_attachments, list):
                    image_suffixes = {
                        ".png", ".jpg", ".jpeg",
                        ".webp", ".bmp", ".gif",
                    }
                    for raw_item in raw_attachments[:20]:
                        path_value = (
                            raw_item.get("path")
                            if isinstance(raw_item, dict)
                            else raw_item
                        )
                        if not path_value:
                            continue
                        path = Path(str(path_value)).expanduser()
                        if not path.exists():
                            continue
                        attachment_type = (
                            AttachmentType.IMAGE
                            if path.suffix.lower() in image_suffixes
                            else AttachmentType.FILE
                        )
                        attachments.append(
                            Attachment(
                                attachment_type=attachment_type,
                                path=str(path),
                                display_name=path.name,
                            )
                        )

                proactive_source_key = str(
                    payload.get(
                        "proactive_context_key",
                        "",
                    )
                )
                if (
                    proactive_source_key.startswith(
                        "visual:"
                    )
                    and self.proactive_context_store
                    is not None
                ):
                    context_path = (
                        self.proactive_context_store
                        .materialize_once(
                            proactive_source_key
                        )
                    )
                    if context_path:
                        proactive_context_path = (
                            context_path
                        )
                        attachments.append(
                            Attachment(
                                attachment_type=(
                                    AttachmentType.SCREENSHOT
                                ),
                                path=context_path,
                                display_name=(
                                    "Контекст активного окна"
                                ),
                                metadata={
                                    "proactive_context": True,
                                    "delete_after_read": True,
                                },
                            )
                        )

                request = (
                    await self.input_coordinator
                    .submit_text(
                        text,
                        source=(
                            RequestSource.DESKTOP_CHAT
                        ),
                        profile=profile,
                        model_mode=model_mode,
                        selected_model=(
                            payload.get(
                                "selected_model"
                            )
                        ),
                        attachments=attachments,
                        metadata=(
                            {
                                "proactive_suggestion_accepted": True,
                                "proactive_event_id": str(
                                    payload.get(
                                        "proactive_event_id"
                                    )
                                ),
                            }
                            if str(
                                payload.get(
                                    "proactive_event_id",
                                    "",
                                )
                            ).startswith("proactive_")
                            else None
                        ),
                    )
                )
                if request is not None:
                    self._last_submission = dict(payload)
                elif proactive_context_path:
                    Path(
                        proactive_context_path
                    ).unlink(missing_ok=True)

                self._publish_command_result(
                    command_id,
                    success=(
                        request is not None
                    ),
                    message=(
                        "Запрос отправлен."
                        if request is not None
                        else
                        "Не удалось отправить запрос."
                    ),
                )
                return

            if action == "cancel_current_request":
                if (
                    self.cancel_current_request
                    is None
                ):
                    self._publish_command_result(
                        command_id,
                        success=False,
                        message=(
                            "Отмена текущего запроса "
                            "не подключена."
                        ),
                    )
                    return

                cancelled = (
                    await self.cancel_current_request()
                )

                self._publish_command_result(
                    command_id,
                    success=cancelled,
                    message=(
                        "Текущий запрос отменён."
                        if cancelled
                        else
                        "Активного запроса нет."
                    ),
                )
                return

            if action == "new_task":
                if hasattr(self.llm, "reset_context"):
                    self.llm.reset_context()
                self._last_submission = None
                self._publish_command_result(
                    command_id,
                    success=True,
                    message="Новая задача создана.",
                )
                return

            if action == "toggle_voice_mode":
                if self.mode_manager is not None:
                    active, snapshot = (
                        await self.mode_manager
                        .toggle_manual_voice()
                    )
                    self.desktop.publish(
                        "preferences",
                        self._preferences_payload(snapshot),
                    )
                    self._publish_command_result(
                        command_id,
                        success=True,
                        message=(
                            "Nova слушает микрофон."
                            if active
                            else
                            "Голосовой ввод остановлен."
                        ),
                    )
                else:
                    self._publish_command_result(
                        command_id,
                        success=False,
                        message="Менеджер режимов не подключён.",
                    )
                return

            if action == "pause_task":
                cancelled = False
                if self.cancel_current_request is not None:
                    cancelled = await self.cancel_current_request()
                self._publish_command_result(
                    command_id,
                    success=cancelled,
                    message=(
                        "Текущее выполнение остановлено."
                        if cancelled
                        else "Активного выполнения нет."
                    ),
                )
                return

            if action == "cancel_task":
                task_id = str(payload.get("task_id", ""))
                if (
                    task_id.startswith("background_")
                    and self.background_plan_manager is not None
                ):
                    result = await self.background_plan_manager.cancel_plan(
                        task_id
                    )
                    self._publish_tool_result(command_id, result)
                elif task_id and self.plan_service is not None:
                    result = self.plan_service.cancel_plan(task_id)
                    self._publish_tool_result(command_id, result)
                elif self.cancel_current_request is not None:
                    cancelled = await self.cancel_current_request()
                    self._publish_command_result(
                        command_id,
                        success=cancelled,
                        message=(
                            "Задача отменена."
                            if cancelled
                            else "Активной задачи нет."
                        ),
                    )
                else:
                    self._publish_command_result(
                        command_id,
                        success=False,
                        message="Отмена не подключена.",
                    )
                return

            if action == "approve_task":
                pending = self.permission_manager.pending_requests()
                if pending:
                    self.permission_manager.confirm(
                        pending[0].get("operation_id", "")
                    )
                    self._publish_command_result(
                        command_id,
                        success=True,
                        message="Разрешение подтверждено.",
                    )
                else:
                    self._publish_command_result(
                        command_id,
                        success=False,
                        message="Нет ожидающих разрешений.",
                    )
                return

            if action in (
                "open_settings",
                "switch_model",
                "open_mcp_manager",
                "open_diagnostics",
            ):
                self._publish_command_result(
                    command_id,
                    success=True,
                    message=f"Команда {action} принята.",
                )
                return

            if action == "open_artifact":
                raw_path = str(payload.get("path", "")).strip()
                path = Path(raw_path)
                if not raw_path or not path.exists():
                    self._publish_command_result(
                        command_id,
                        success=False,
                        message="Артефакт не найден.",
                    )
                    return
                os.startfile(str(path))
                self._publish_command_result(
                    command_id,
                    success=True,
                    message=f"Открыт артефакт: {path.name}",
                )
                return

            self._publish_command_result(
                command_id,
                success=False,
                message=(
                    f"Неизвестная команда UI: "
                    f"{action}"
                ),
            )

        except Exception as exc:
            logger.exception(
                "Ошибка команды UI %s.",
                action,
            )

            self._publish_command_result(
                command_id,
                success=False,
                message=str(exc),
            )

    def _publish_tool_result(
        self,
        command_id: str,
        result,
    ) -> None:
        self.desktop.publish(
            "command_result",
            {
                "command_id": command_id,
                **result.to_dict(),
            },
        )

    def _publish_command_result(
        self,
        command_id: str,
        *,
        success: bool,
        message: str,
    ) -> None:
        self.desktop.publish(
            "command_result",
            {
                "command_id": command_id,
                "success": success,
                "message": message,
            },
        )
