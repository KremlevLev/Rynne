# modules/ui/core_bridge.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

from modules.tools.permissions import (
    PermissionManager,
)
from modules.ui.desktop_protocol import (
    validate_command,
)
from modules.ui.desktop_service import (
    DesktopService,
)
from modules.application.preferences import (
    PreferencesManager,
)
from modules.input_hub.coordinator import (
    InputCoordinator,
)
from modules.input_hub.models import (
    AssistantProfile,
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
        desktop: DesktopService,
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
        self._reported_plan_ids: set[str] = set()
        self._reported_bg_ids: set[str] = set()
        self._reported_completed_ids: set[str] = set()


    async def run(
        self,
        shutdown_event: asyncio.Event,
    ) -> None:
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
                self.preferences
                .snapshot()
                .to_dict(),
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

        self.desktop.publish(
            "runtime",
            {
                "state": self.runtime.state.value,
                "active": self.runtime.is_active,
                "shutting_down": (
                    self.runtime.is_shutting_down
                ),
            },
        )

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
                    # Публикуем прогресс активных задач
                    self.desktop.publish(
                        "task_progress",
                        {
                            "task_id": plan_id,
                            "plan": [
                                {
                                    "text": s.description,
                                    "status": s.status.value
                                    if hasattr(s.status, "value")
                                    else str(s.status),
                                }
                                for s in plan.steps
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
                snapshot.to_dict(),
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
                    )
                )

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
                self._publish_command_result(
                    command_id,
                    success=True,
                    message="Новая задача создана.",
                )
                return

            if action == "toggle_voice_mode":
                if self.mode_manager is not None:
                    await self.mode_manager.toggle_manual_voice()
                    self._publish_command_result(
                        command_id,
                        success=True,
                        message="Голосовой режим переключён.",
                    )
                else:
                    self._publish_command_result(
                        command_id,
                        success=False,
                        message="Менеджер режимов не подключён.",
                    )
                return

            if action == "pause_task":
                if self.cancel_current_request is not None:
                    await self.cancel_current_request()
                self._publish_command_result(
                    command_id,
                    success=True,
                    message="Задача приостановлена.",
                )
                return

            if action == "cancel_task":
                if self.cancel_current_request is not None:
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
