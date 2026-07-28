# modules/tools/runtime.py
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from typing import Any, Callable
from modules.tools.policy import (
    PolicyContext,
)
from modules.tools.permissions import (
    PermissionManager,
)

from core.config import TOOL_TIMEOUT_SECONDS
from modules.domain.results import (
    ToolResult,
    VerificationResult,
)
from modules.tools.base import (
    RiskLevel,
    ToolCategory,
    ToolContext,
    ToolDefinition,
)


logger = logging.getLogger("ToolRuntime")


ERROR_MARKERS = (
    "ошибка",
    "не удалось",
    "отказ",
    "отклонено",
    "access denied",
    "permission denied",
    "exception",
    "not found",
    "не найден",
    "заблокирован",
    "сбой",
    "аварийная остановка",
)


RISK_BY_TOOL: dict[str, RiskLevel] = {
    "get_current_time": RiskLevel.READ_ONLY,
    "get_system_status": RiskLevel.READ_ONLY,
    "search_in_memory": RiskLevel.READ_ONLY,
    "get_active_reminders": RiskLevel.READ_ONLY,
    "list_active_windows": RiskLevel.READ_ONLY,
    "search_web_tavily": RiskLevel.READ_ONLY,
    "scrape_webpage": RiskLevel.READ_ONLY,
    "get_clipboard_content": RiskLevel.READ_ONLY,

    "open_application": RiskLevel.LOW,
    "open_application_batch": RiskLevel.LOW,
    "change_volume": RiskLevel.LOW,
    "manage_media": RiskLevel.LOW,
    "focus_window": RiskLevel.LOW,

    "type_text": RiskLevel.WRITE,
    "write_in_application": RiskLevel.WRITE,
    "set_clipboard_content": RiskLevel.WRITE,
    "create_quick_note": RiskLevel.WRITE,
    "set_reminder": RiskLevel.WRITE,
    "save_to_memory": RiskLevel.WRITE,
    "create_workspace_project": RiskLevel.WRITE,

    "press_keyboard_combination": RiskLevel.EXECUTE,
    "mouse_click": RiskLevel.EXECUTE,
    "open_website": RiskLevel.EXECUTE,
    "run_terminal_command": RiskLevel.EXECUTE,
    "execute_python_code": RiskLevel.EXECUTE,

    "close_application": RiskLevel.DESTRUCTIVE,
    "manage_windows": RiskLevel.DESTRUCTIVE,
    "execute_cmd_command": RiskLevel.DESTRUCTIVE,
    "browser_start": RiskLevel.LOW,
    "browser_open_url": RiskLevel.LOW,
    "browser_get_page_text": RiskLevel.READ_ONLY,
    "browser_click": RiskLevel.WRITE,
    "browser_fill": RiskLevel.WRITE,
    "browser_screenshot": RiskLevel.READ_ONLY,
    "browser_status": RiskLevel.READ_ONLY,
    "browser_close": RiskLevel.LOW,

    "execute_plan": RiskLevel.EXECUTE,
    "get_plan_status": RiskLevel.READ_ONLY,
    "cancel_plan": RiskLevel.LOW,
    "start_background_plan": RiskLevel.EXECUTE,
    "get_background_plan_status": RiskLevel.READ_ONLY,
    "list_background_plans": RiskLevel.READ_ONLY,
    "retry_background_plan": RiskLevel.EXECUTE,
    "cancel_background_plan": RiskLevel.LOW,
    "watch_website": RiskLevel.WRITE,
    "list_website_watches": RiskLevel.READ_ONLY,
    "remove_website_watch": RiskLevel.LOW,
    "watch_backup": RiskLevel.WRITE,
    "list_backup_watches": RiskLevel.READ_ONLY,
    "remove_backup_watch": RiskLevel.LOW,
    "watch_package_update": RiskLevel.WRITE,
    "list_package_update_watches": RiskLevel.READ_ONLY,
    "remove_package_update_watch": RiskLevel.LOW,

}


CATEGORY_BY_TOOL: dict[str, ToolCategory] = {
    "get_current_time": ToolCategory.SYSTEM_READ,
    "get_system_status": ToolCategory.SYSTEM_READ,

    "open_application": ToolCategory.APPLICATION,
    "open_application_batch": ToolCategory.APPLICATION,
    "close_application": ToolCategory.APPLICATION,
    "focus_window": ToolCategory.GUI_WRITE,
    "list_active_windows": ToolCategory.GUI_READ,

    "type_text": ToolCategory.GUI_WRITE,
    "write_in_application": ToolCategory.GUI_WRITE,
    "mouse_click": ToolCategory.GUI_WRITE,
    "press_keyboard_combination": (
        ToolCategory.GUI_WRITE
    ),

    "get_clipboard_content": (
        ToolCategory.CLIPBOARD_READ
    ),
    "set_clipboard_content": (
        ToolCategory.CLIPBOARD_WRITE
    ),

    "search_web_tavily": ToolCategory.WEB_READ,
    "scrape_webpage": ToolCategory.WEB_READ,
    "open_website": ToolCategory.NETWORK_WRITE,

    "save_to_memory": ToolCategory.MEMORY,
    "search_in_memory": ToolCategory.MEMORY,

    "set_reminder": ToolCategory.REMINDER,
    "get_active_reminders": ToolCategory.REMINDER,
    "set_timer": ToolCategory.REMINDER,

    "run_terminal_command": ToolCategory.TERMINAL,
    "execute_cmd_command": ToolCategory.TERMINAL,
    "execute_python_code": ToolCategory.DEVELOPMENT,
    "create_workspace_project": (
        ToolCategory.DEVELOPMENT
    ),

    "browser_start": ToolCategory.WEB_READ,
    "browser_open_url": ToolCategory.WEB_READ,
    "browser_get_page_text": ToolCategory.WEB_READ,
    "browser_click": ToolCategory.NETWORK_WRITE,
    "browser_fill": ToolCategory.NETWORK_WRITE,
    "browser_screenshot": ToolCategory.WEB_READ,
    "browser_status": ToolCategory.WEB_READ,
    "browser_close": ToolCategory.WEB_READ,

    "execute_plan": ToolCategory.DEVELOPMENT,
    "get_plan_status": ToolCategory.DEVELOPMENT,
    "cancel_plan": ToolCategory.DEVELOPMENT,
    "start_background_plan": ToolCategory.DEVELOPMENT,
    "get_background_plan_status": ToolCategory.DEVELOPMENT,
    "list_background_plans": ToolCategory.DEVELOPMENT,
    "retry_background_plan": ToolCategory.DEVELOPMENT,
    "cancel_background_plan": ToolCategory.DEVELOPMENT,
    "watch_website": ToolCategory.WEB_READ,
    "list_website_watches": ToolCategory.WEB_READ,
    "remove_website_watch": ToolCategory.WEB_READ,
    "watch_backup": ToolCategory.SYSTEM_READ,
    "list_backup_watches": ToolCategory.SYSTEM_READ,
    "remove_backup_watch": ToolCategory.SYSTEM_READ,
    "watch_package_update": ToolCategory.WEB_READ,
    "list_package_update_watches": ToolCategory.WEB_READ,
    "remove_package_update_watch": ToolCategory.WEB_READ,

}


IDEMPOTENT_TOOLS = {
    "get_current_time",
    "get_system_status",
    "search_in_memory",
    "get_active_reminders",
    "list_active_windows",
    "get_clipboard_content",
    "search_web_tavily",
    "scrape_webpage",
    "browser_get_page_text",
    "browser_screenshot",
    "browser_status",
    "get_plan_status",
    "get_background_plan_status",
    "list_background_plans",
    "list_website_watches",
    "list_backup_watches",
    "list_package_update_watches",

}


def _looks_like_error(text: str) -> bool:
    normalized = text.lower()

    return any(
        marker in normalized
        for marker in ERROR_MARKERS
    )


def adapt_legacy_result(
    value: Any,
) -> ToolResult:
    if isinstance(value, ToolResult):
        return value

    if isinstance(value, tuple) and len(value) == 2:
        success, message = value

        if isinstance(success, bool):
            if success:
                return ToolResult.ok(
                    str(message),
                    verification=VerificationResult(
                        verified=None,
                        method="legacy_result",
                        confidence=0.5,
                        details=(
                            "Legacy handler сообщил об успехе."
                        ),
                    ),
                )

            return ToolResult.failure(
                "LEGACY_TOOL_FAILED",
                str(message),
            )

    if value is None:
        return ToolResult.ok(
            "Операция завершена без текстового результата.",
            verification=VerificationResult(
                verified=None,
                method="not_performed",
                confidence=0.0,
            ),
        )

    message = str(value)

    if _looks_like_error(message):
        return ToolResult.failure(
            "LEGACY_TOOL_ERROR",
            message,
        )

    return ToolResult.ok(
        message,
        verification=VerificationResult(
            verified=None,
            method="legacy_text_result",
            confidence=0.4,
            details=(
                "Результат адаптирован из строкового ответа."
            ),
        ),
    )


def strip_unknown_properties(
    value: Any,
    schema: dict[str, Any],
) -> Any:
    expected_type = schema.get("type")

    if (
        expected_type == "object"
        and isinstance(value, dict)
    ):
        properties = schema.get(
            "properties",
            {},
        )

        return {
            key: strip_unknown_properties(
                child_value,
                properties[key],
            )
            for key, child_value in value.items()
            if key in properties
        }

    if (
        expected_type == "array"
        and isinstance(value, list)
    ):
        item_schema = schema.get(
            "items",
            {},
        )

        return [
            strip_unknown_properties(
                item,
                item_schema,
            )
            for item in value
        ]

    return value


def validate_json_schema(
    value: Any,
    schema: dict[str, Any],
    path: str = "arguments",
) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")

    if expected_type == "object":
        if not isinstance(value, dict):
            return [
                f"{path} должен быть объектом."
            ]

        properties = schema.get(
            "properties",
            {},
        )
        required = schema.get(
            "required",
            [],
        )

        for required_name in required:
            if required_name not in value:
                errors.append(
                    (
                        "Отсутствует обязательный параметр "
                        f"'{required_name}'."
                    )
                )

        if schema.get(
            "additionalProperties"
        ) is False:
            for key in value:
                if key not in properties:
                    errors.append(
                        f"Неизвестный параметр '{key}'."
                    )

        for key, child_value in value.items():
            child_schema = properties.get(key)

            if child_schema:
                errors.extend(
                    validate_json_schema(
                        child_value,
                        child_schema,
                        f"{path}.{key}",
                    )
                )

    elif expected_type == "array":
        if not isinstance(value, list):
            return [
                f"{path} должен быть массивом."
            ]

        minimum_items = schema.get("minItems")
        maximum_items = schema.get("maxItems")

        if (
            minimum_items is not None
            and len(value) < minimum_items
        ):
            errors.append(
                (
                    f"{path} должен содержать не менее "
                    f"{minimum_items} элементов."
                )
            )

        if (
            maximum_items is not None
            and len(value) > maximum_items
        ):
            errors.append(
                (
                    f"{path} содержит больше "
                    f"{maximum_items} элементов."
                )
            )

        item_schema = schema.get("items")

        if item_schema:
            for index, item in enumerate(value):
                errors.extend(
                    validate_json_schema(
                        item,
                        item_schema,
                        f"{path}[{index}]",
                    )
                )

    elif expected_type == "string":
        if not isinstance(value, str):
            return [
                f"{path} должен быть строкой."
            ]

        minimum_length = schema.get(
            "minLength"
        )
        maximum_length = schema.get(
            "maxLength"
        )

        if (
            minimum_length is not None
            and len(value) < minimum_length
        ):
            errors.append(
                (
                    f"{path} должен содержать не менее "
                    f"{minimum_length} символов."
                )
            )

        if (
            maximum_length is not None
            and len(value) > maximum_length
        ):
            errors.append(
                (
                    f"{path} превышает лимит "
                    f"{maximum_length} символов."
                )
            )

    elif expected_type == "integer":
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
        ):
            return [
                f"{path} должен быть целым числом."
            ]

        minimum = schema.get("minimum")
        maximum = schema.get("maximum")

        if (
            minimum is not None
            and value < minimum
        ):
            errors.append(
                f"{path} должен быть не меньше {minimum}."
            )

        if (
            maximum is not None
            and value > maximum
        ):
            errors.append(
                f"{path} должен быть не больше {maximum}."
            )

    elif expected_type == "number":
        if (
            isinstance(value, bool)
            or not isinstance(
                value,
                (int, float),
            )
        ):
            return [
                f"{path} должен быть числом."
            ]

    elif expected_type == "boolean":
        if not isinstance(value, bool):
            return [
                (
                    f"{path} должен быть "
                    "логическим значением."
                )
            ]

    enum_values = schema.get("enum")

    if (
        enum_values is not None
        and value not in enum_values
    ):
        errors.append(
            (
                f"{path} должен иметь одно из "
                f"значений: {enum_values}."
            )
        )

    return errors


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[
            str,
            ToolDefinition,
        ] = {}

    def register_definition(
        self,
        definition: ToolDefinition,
    ) -> None:
        if definition.name in self._tools:
            raise ValueError(
                (
                    f"Инструмент '{definition.name}' "
                    "зарегистрирован повторно."
                )
            )

        self._tools[
            definition.name
        ] = definition

    def register(
        self,
        *,
        schema: dict[str, Any],
        handler: Callable[..., Any],
        risk: RiskLevel | None = None,
        category: ToolCategory | None = None,
        timeout_seconds: float = (
            TOOL_TIMEOUT_SECONDS
        ),
    ) -> None:
        definition = ToolDefinition.from_legacy(
            schema=schema,
            handler=handler,
            risk=(
                risk
                or RISK_BY_TOOL.get(
                    schema.get(
                        "function",
                        {},
                    ).get("name", ""),
                    RiskLevel.LOW,
                )
            ),
            category=(
                category
                or CATEGORY_BY_TOOL.get(
                    schema.get(
                        "function",
                        {},
                    ).get("name", ""),
                    ToolCategory.UNKNOWN,
                )
            ),
            timeout_seconds=timeout_seconds,
            idempotent=(
                schema.get(
                    "function",
                    {},
                ).get("name")
                in IDEMPOTENT_TOOLS
            ),
        )

        self.register_definition(definition)

    @classmethod
    def from_legacy(
        cls,
        schemas: list[dict[str, Any]],
        handlers: dict[
            str,
            Callable[..., Any],
        ],
    ) -> "ToolRegistry":
        registry = cls()

        schema_names = {
            item.get(
                "function",
                {},
            ).get("name")
            for item in schemas
        }

        schema_names.discard(None)

        handler_names = set(handlers)

        missing_handlers = (
            schema_names - handler_names
        )
        missing_schemas = (
            handler_names - schema_names
        )

        if missing_handlers:
            raise ValueError(
                (
                    "Для схем отсутствуют обработчики: "
                    + ", ".join(
                        sorted(missing_handlers)
                    )
                )
            )

        if missing_schemas:
            raise ValueError(
                (
                    "Для обработчиков отсутствуют схемы: "
                    + ", ".join(
                        sorted(missing_schemas)
                    )
                )
            )

        for schema in schemas:
            function_schema = schema.get(
                "function",
                {},
            )
            name = function_schema.get("name")

            if not isinstance(name, str):
                continue

            registry.register(
                schema=schema,
                handler=handlers[name],
            )

        return registry

    @property
    def names(self) -> set[str]:
        return set(self._tools)

    def definitions(
        self,
    ) -> list[ToolDefinition]:
        return list(self._tools.values())

    def schemas(
        self,
        names: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        if names is None:
            return [
                definition.to_openai_schema()
                for definition
                in self._tools.values()
            ]

        return [
            definition.to_openai_schema()
            for name, definition
            in self._tools.items()
            if name in names
        ]

    def get(
        self,
        name: str,
    ) -> ToolDefinition | None:
        return self._tools.get(name)


class ToolRunner:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        permission_manager: (
            PermissionManager | None
        ) = None,
        event_sink: Callable[
            [str, dict[str, Any]],
            Any,
        ] | None = None,
    ) -> None:
        self.registry = registry
        self.permission_manager = (
            permission_manager
            or PermissionManager()
        )
        self._event_sink = event_sink

    def set_event_sink(
        self,
        event_sink: Callable[
            [str, dict[str, Any]],
            Any,
        ] | None,
    ) -> None:
        """Подключает наблюдателя presentation layer без зависимости от UI."""
        self._event_sink = event_sink

    def _emit_event(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if self._event_sink is None:
            return
        try:
            self._event_sink(event_type, payload)
        except Exception:
            # Сбой UI/телеметрии не должен ломать выполнение инструмента.
            logger.exception(
                "Не удалось отправить событие ToolRunner: %s.",
                event_type,
            )

    @staticmethod
    def _parse_arguments(
        tool_call: dict[str, Any],
    ) -> tuple[
        str | None,
        dict[str, Any] | None,
        ToolResult | None,
    ]:
        function = tool_call.get("function")

        if not isinstance(function, dict):
            return (
                None,
                None,
                ToolResult.failure(
                    "INVALID_TOOL_CALL",
                    (
                        "Вызов инструмента не содержит "
                        "объекта function."
                    ),
                ),
            )

        name = function.get("name")

        if not isinstance(name, str) or not name:
            return (
                None,
                None,
                ToolResult.failure(
                    "INVALID_TOOL_NAME",
                    "Не указано имя инструмента.",
                ),
            )

        raw_arguments = (
            function.get("arguments")
            or "{}"
        )

        try:
            arguments = (
                raw_arguments
                if isinstance(
                    raw_arguments,
                    dict,
                )
                else json.loads(raw_arguments)
            )
        except (
            json.JSONDecodeError,
            TypeError,
        ) as exc:
            return (
                name,
                None,
                ToolResult.failure(
                    "INVALID_ARGUMENTS_JSON",
                    (
                        f"Повреждён JSON аргументов "
                        f"'{name}': {exc}"
                    ),
                ),
            )

        if not isinstance(arguments, dict):
            return (
                name,
                None,
                ToolResult.failure(
                    "INVALID_ARGUMENTS_TYPE",
                    (
                        "Аргументы инструмента должны "
                        "быть объектом."
                    ),
                ),
            )

        return name, arguments, None

    async def execute(
        self,
        tool_call: dict[str, Any],
        *,
        context: ToolContext | None = None,
    ) -> ToolResult:
        name, arguments, parse_error = (
            self._parse_arguments(tool_call)
        )

        if parse_error is not None:
            return parse_error

        assert name is not None
        assert arguments is not None

        definition = self.registry.get(name)

        if definition is None:
            return ToolResult.failure(
                "TOOL_NOT_FOUND",
                (
                    f"Инструмент '{name}' "
                    "не зарегистрирован."
                ),
            )

        actual_context = (
            context
            if context is not None
            else ToolContext.create()
        )

        actual_context.cancellation.raise_if_cancelled()
        policy_context = PolicyContext.from_tool_context(
            definition=definition,
            arguments=arguments,
            context=actual_context,
        )

        allowed, denial_reason = (
            self.permission_manager.check(
                policy_context
            )
        )

        if denial_reason is not None:
            return ToolResult.failure(
                "POLICY_DENIED",
                denial_reason,
                data={
                    "operation_id": (
                        actual_context.operation_id
                    ),
                },
            )

        if not allowed:
            granted = (
                await self.permission_manager.wait_for_confirmation(
                    policy_context
                )
            )

            if not granted:
                return ToolResult.failure(
                    "USER_DENIED",
                    (
                        f"Пользователь запретил выполнение "
                        f"'{definition.name}'."
                    ),
                    data={
                        "operation_id": (
                            actual_context.operation_id
                        ),
                    },
                )

        original_argument_names = set(arguments)

        arguments = strip_unknown_properties(
            arguments,
            definition.parameters,
        )

        removed_arguments = sorted(
            original_argument_names
            - set(arguments)
        )

        validation_errors = validate_json_schema(
            arguments,
            definition.parameters,
        )

        if validation_errors:
            return ToolResult.failure(
                "ARGUMENT_VALIDATION_FAILED",
                " ".join(validation_errors),
                data={
                    "errors": validation_errors,
                    "operation_id": (
                        actual_context.operation_id
                    ),
                },
            )

        started_at = time.perf_counter()

        logger.info(
            (
                "Инструмент запущен: name=%s "
                "operation_id=%s risk=%s category=%s"
            ),
            definition.name,
            actual_context.operation_id,
            definition.risk.value,
            definition.category.value,
        )
        self._emit_event(
            "tool_started",
            {
                "tool_name": definition.name,
                "operation_id": actual_context.operation_id,
                "turn_id": actual_context.turn_id,
                "session_id": actual_context.session_id,
                "description": (
                    definition.description
                    or definition.name
                ),
                "risk": definition.risk.value,
                "category": definition.category.value,
                "argument_names": sorted(arguments),
            },
        )

        try:
            call_arguments = dict(arguments)

            if definition.inject_context:
                call_arguments["context"] = (
                    actual_context
                )

            if inspect.iscoroutinefunction(
                definition.handler
            ):
                execution = definition.handler(
                    **call_arguments
                )
            else:
                execution = asyncio.to_thread(
                    definition.handler,
                    **call_arguments,
                )

            raw_result = await asyncio.wait_for(
                execution,
                timeout=(
                    definition.timeout_seconds
                ),
            )

            result = adapt_legacy_result(
                raw_result
            )

        except asyncio.TimeoutError:
            result = ToolResult.failure(
                "TOOL_TIMEOUT",
                (
                    f"Инструмент '{name}' превысил "
                    f"лимит "
                    f"{definition.timeout_seconds:.0f} "
                    "секунд."
                ),
                retryable=True,
            )

        except asyncio.CancelledError:
            actual_context.cancellation.cancel()

            result = ToolResult.failure(
                "TOOL_CANCELLED",
                (
                    f"Инструмент '{name}' был отменён."
                ),
                retryable=False,
            )

        except Exception as exc:
            logger.exception(
                (
                    "Ошибка выполнения инструмента %s, "
                    "operation_id=%s."
                ),
                name,
                actual_context.operation_id,
            )

            result = ToolResult.failure(
                "TOOL_EXECUTION_FAILED",
                (
                    f"Ошибка выполнения "
                    f"'{name}': {exc}"
                ),
            )

        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000
        )

        result.duration_ms = duration_ms

        result.data.setdefault(
            "operation_id",
            actual_context.operation_id,
        )
        result.data.setdefault(
            "session_id",
            actual_context.session_id,
        )
        result.data.setdefault(
            "turn_id",
            actual_context.turn_id,
        )
        result.data.setdefault(
            "risk",
            definition.risk.value,
        )
        result.data.setdefault(
            "category",
            definition.category.value,
        )
        result.data.setdefault(
            "idempotent",
            definition.idempotent,
        )

        if removed_arguments:
            result.add_warning(
                "UNKNOWN_ARGUMENTS_REMOVED",
                (
                    "Удалены неизвестные параметры: "
                    + ", ".join(removed_arguments)
                ),
            )

        logger.info(
            (
                "Инструмент завершён: name=%s "
                "operation_id=%s success=%s "
                "code=%s duration_ms=%s"
            ),
            definition.name,
            actual_context.operation_id,
            result.success,
            result.code,
            result.duration_ms,
        )

        self._emit_event(
            "tool_completed",
            {
                "tool_name": definition.name,
                "operation_id": actual_context.operation_id,
                "turn_id": actual_context.turn_id,
                "session_id": actual_context.session_id,
                "success": result.success,
                "code": result.code,
                "message": result.message,
                "duration_ms": result.duration_ms,
                "artifacts": result.artifacts,
                "retryable": result.retryable,
                "risk": definition.risk.value,
                "category": definition.category.value,
            },
        )

        # Record to ledger (all side effects, not just successful ones)
        from modules.domain.ledger import get_ledger
        
        # Include verification info if available
        verification_data = None
        if result.verification is not None:
            verification_data = {
                "verified": result.verification.verified,
                "method": result.verification.method,
                "confidence": result.verification.confidence,
                "details": result.verification.details,
            }
        
        # Include artifacts if available
        artifacts = [str(a) for a in result.artifacts] if result.artifacts else []
        
        get_ledger().record(
            tool_name=definition.name,
            arguments=arguments,
            result=result.to_dict(),
            session_id=actual_context.session_id,
            turn_id=actual_context.turn_id,
            rollback_info=definition.rollback_info,
            verification=verification_data,
            artifacts=artifacts,
        )
        
        return result
