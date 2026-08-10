# modules/routing/direct_executor.py
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from modules.application.preferences import (
    PreferencesManager,
)
from modules.application.reporting import (
    build_assistant_response_from_tools,
)
from modules.domain.results import (
    AssistantResponse,
)
from modules.application.interaction_modes import (
    InteractionModeManager,
)
from modules.input_hub.models import (
    AssistantProfile,
    InputMode,
    ModelSelectionMode,
    UserRequest,
)
from modules.routing.decision import (
    ExecutionDecision,
    IntentKind,
)
from modules.tools.base import ToolContext
from modules.tools.runtime import ToolRunner


logger = logging.getLogger("DirectExecutor")


class DirectRequestExecutor:
    """
    Исполняет детерминированные решения без обращения к LLM.

    Поддерживаются:
    - время;
    - громкость;
    - запуск приложения;
    - закрытие приложения;
    - выбор режима;
    - выбор модели.
    """

    def __init__(
        self,
        *,
        runner: ToolRunner,
        preferences: PreferencesManager,
        mode_manager: (
            InteractionModeManager | None
        ) = None,
        session_id: str = "nova-session",
    ) -> None:
        self.runner = runner
        self.preferences = preferences
        self.mode_manager = mode_manager
        self.session_id = session_id


    async def execute(
        self,
        request: UserRequest,
        decision: ExecutionDecision,
    ) -> AssistantResponse:
        if (
            decision.intent
            == IntentKind.MODEL_SELECTION
        ):
            return self._apply_model_selection(
                request.text
            )

        if (
            decision.intent
            == IntentKind.MODE_SELECTION
        ):
            return await self._apply_mode_selection(
                request.text
            )


        tool_name = self._resolve_tool_name(
            decision
        )

        if tool_name is None:
            return AssistantResponse(
                display_text=(
                    "Для прямого маршрута не найден "
                    "подходящий инструмент."
                ),
                speech_text=(
                    "Сэр, для этой команды не найден "
                    "прямой обработчик."
                ),
                success=False,
                error_code=(
                    "DIRECT_TOOL_NOT_RESOLVED"
                ),
                data={
                    "execution_decision": (
                        decision.to_dict()
                    ),
                },
            )

        arguments_result = (
            self._build_tool_arguments(
                request,
                decision,
            )
        )

        if isinstance(
            arguments_result,
            AssistantResponse,
        ):
            return arguments_result

        tool_call = {
            "id": (
                f"direct_{uuid.uuid4().hex}"
            ),
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(
                    arguments_result,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        }

        context = ToolContext.create(
            session_id=(
                request.session_id
                or self.session_id
            ),
            turn_id=request.request_id,
            source=request.source.value,
            expected_window=(
                request.active_window_title
            ),
            working_directory=request.metadata.get("workspace_path"),
            metadata={
                "strategy": (
                    decision.strategy.value
                ),
                "intent": (
                    decision.intent.value
                ),
                "request_id": (
                    request.request_id
                ),
                "direct_execution": True,
                "telegram_remote": bool(request.metadata.get("telegram_remote")),
                "telegram_remote_chat_id": request.metadata.get("telegram_remote_chat_id"),
                "telegram_remote_user_id": request.metadata.get("telegram_remote_user_id"),
                "proactive_suggestion_accepted": (
                    bool(
                        request.metadata.get(
                            "proactive_suggestion_accepted"
                        )
                    )
                ),
            },
        )

        logger.info(
            (
                "DIRECT execution: request_id=%s "
                "intent=%s tool=%s arguments=%s"
            ),
            request.request_id,
            decision.intent.value,
            tool_name,
            arguments_result,
        )

        result = await self.runner.execute(
            tool_call,
            context=context,
        )

        record = {
            "tool_call_id": tool_call["id"],
            "name": tool_name,
            "arguments": arguments_result,
            "result": result.to_dict(),
        }

        response = (
            build_assistant_response_from_tools(
                [record]
            )
        )

        response.data[
            "execution_decision"
        ] = decision.to_dict()
        response.data["direct_execution"] = True
        response.data["model_calls"] = 0

        return response

    @staticmethod
    def _resolve_tool_name(
        decision: ExecutionDecision,
    ) -> str | None:
        if decision.selected_skill:
            return decision.selected_skill

        if len(decision.required_tools) == 1:
            return next(
                iter(decision.required_tools)
            )

        mapping = {
            IntentKind.SYSTEM_TIME: (
                "get_current_time"
            ),
            IntentKind.SYSTEM_VOLUME: (
                "change_volume"
            ),
            IntentKind.APPLICATION_OPEN: (
                "open_application"
            ),
            IntentKind.APPLICATION_BATCH: (
                "open_application_batch"
            ),
            IntentKind.APPLICATION_CLOSE: (
                "close_application"
            ),
        }

        return mapping.get(decision.intent)

    def _build_tool_arguments(
        self,
        request: UserRequest,
        decision: ExecutionDecision,
    ) -> dict[str, Any] | AssistantResponse:
        if (
            decision.intent
            == IntentKind.SYSTEM_TIME
        ):
            return {}

        if (
            decision.intent
            == IntentKind.APPLICATION_OPEN
        ):
            app_name = str(
                decision.arguments.get(
                    "app_name",
                    "",
                )
            ).strip()

            if not app_name:
                return self._clarification(
                    "Какое приложение открыть?"
                )

            return {
                "app_name": app_name,
            }

        if (
            decision.intent
            == IntentKind.APPLICATION_BATCH
        ):
            count = decision.arguments.get("count")
            if not isinstance(count, int) or not 2 <= count <= 10:
                return self._clarification(
                    "Сколько приложений открыть — от 2 до 10?"
                )
            return {"count": count}

        if (
            decision.intent
            == IntentKind.APPLICATION_CLOSE
        ):
            app_name = str(
                decision.arguments.get(
                    "app_name",
                    "",
                )
            ).strip()

            if not app_name:
                return self._clarification(
                    "Какое приложение закрыть?"
                )

            return {
                "app_name": app_name,
            }

        if (
            decision.intent == IntentKind.WEB
            and decision.selected_skill == "open_url_in_browser"
        ):
            app_name = str(decision.arguments.get("app_name", "")).strip()
            url = str(decision.arguments.get("url", "")).strip()
            if not app_name or not url:
                return self._clarification("В каком браузере и какой адрес открыть?")
            return {"app_name": app_name, "url": url}

        if (
            decision.intent == IntentKind.WEB
            and decision.selected_skill == "open_telegram_chat"
        ):
            contact = str(decision.arguments.get("contact", "")).strip()
            if not contact:
                return self._clarification("Какой чат открыть?")
            return {"contact": contact}

        if (
            decision.intent
            == IntentKind.SYSTEM_VOLUME
        ):
            action = self._parse_volume_action(
                request.text
            )

            if action is None:
                return self._clarification(
                    (
                        "Как изменить громкость: "
                        "громче, тише, выключить звук "
                        "или установить конкретный уровень?"
                    )
                )

            return {
                "action": action,
            }

        return dict(decision.arguments)

    @staticmethod
    def _parse_volume_action(
        text: str,
    ) -> str | None:
        lowered = text.lower().replace(
            "ё",
            "е",
        )

        percentage_match = re.search(
            r"\b(\d{1,3})\s*%?\b",
            lowered,
        )

        if percentage_match and any(
            marker in lowered
            for marker in (
                "громкость",
                "звук",
                "поставь",
                "установи",
            )
        ):
            value = max(
                0,
                min(
                    100,
                    int(
                        percentage_match.group(1)
                    ),
                ),
            )

            return str(value)

        if any(
            marker in lowered
            for marker in (
                "выключи звук",
                "включи звук",
                "мьют",
                "mute",
                "без звука",
            )
        ):
            return "mute"

        if any(
            marker in lowered
            for marker in (
                "громче",
                "увеличь",
                "прибавь",
            )
        ):
            return "up"

        if any(
            marker in lowered
            for marker in (
                "тише",
                "уменьши",
                "убавь",
            )
        ):
            return "down"

        return None

    def _apply_model_selection(
        self,
        text: str,
    ) -> AssistantResponse:
        lowered = text.lower().replace(
            "ё",
            "е",
        )

        try:
            if any(
                marker in lowered
                for marker in (
                    "автоматическ",
                    "режим авто",
                    "верни авто",
                )
            ):
                snapshot = (
                    self.preferences
                    .set_model_mode(
                        ModelSelectionMode.AUTO
                    )
                )
                message = (
                    "Автоматический выбор модели включён."
                )

            elif any(
                marker in lowered
                for marker in (
                    "быструю модель",
                    "быстрая модель",
                    "режим fast",
                )
            ):
                snapshot = (
                    self.preferences
                    .set_model_mode(
                        ModelSelectionMode.FAST
                    )
                )
                message = (
                    "Включён режим быстрых моделей."
                )

            elif any(
                marker in lowered
                for marker in (
                    "умную модель",
                    "умная модель",
                    "режим smart",
                )
            ):
                snapshot = (
                    self.preferences
                    .set_model_mode(
                        ModelSelectionMode.SMART
                    )
                )
                message = (
                    "Включён режим умных моделей."
                )

            elif any(
                marker in lowered
                for marker in (
                    "для кода",
                    "кодовую модель",
                    "режим coding",
                )
            ):
                snapshot = (
                    self.preferences
                    .set_model_mode(
                        ModelSelectionMode.CODING
                    )
                )
                message = (
                    "Включён режим моделей для кода."
                )

            elif any(
                marker in lowered
                for marker in (
                    "только бесплат",
                    "бесплатные модели",
                )
            ):
                snapshot = (
                    self.preferences
                    .set_model_mode(
                        ModelSelectionMode.FREE_ONLY
                    )
                )
                message = (
                    "Будут использоваться только "
                    "бесплатные модели."
                )

            elif any(
                marker in lowered
                for marker in (
                    "локальную модель",
                    "локальный режим модели",
                    "только локальн",
                )
            ):
                snapshot = (
                    self.preferences
                    .set_model_mode(
                        ModelSelectionMode.LOCAL_ONLY
                    )
                )
                message = (
                    "Включён локальный режим моделей."
                )

            else:
                model_match = re.search(
                    (
                        r"(?:используй|выбери|"
                        r"переключись на)\s+модель\s+(.+)"
                    ),
                    text,
                    flags=re.IGNORECASE,
                )

                if not model_match:
                    return self._clarification(
                        (
                            "Какой режим модели включить: "
                            "авто, быстрый, умный, код, "
                            "бесплатный или локальный?"
                        )
                    )

                selected_model = (
                    model_match.group(1)
                    .strip(" .,!?:;")
                )

                snapshot = (
                    self.preferences
                    .set_model_mode(
                        ModelSelectionMode.PINNED,
                        selected_model=(
                            selected_model
                        ),
                    )
                )

                message = (
                    f"Модель '{selected_model}' "
                    "закреплена для текущей сессии."
                )

        except ValueError as exc:
            return AssistantResponse(
                display_text=str(exc),
                speech_text=str(exc),
                success=False,
                error_code=(
                    "MODEL_SELECTION_FAILED"
                ),
            )

        return AssistantResponse(
            display_text=message,
            speech_text=message,
            success=True,
            data={
                "preferences": (
                    snapshot.to_dict()
                ),
                "direct_execution": True,
                "model_calls": 0,
            },
        )

    async def _apply_mode_selection(
        self,
        text: str,
    ) -> AssistantResponse:
        lowered = text.lower().replace(
            "ё",
            "е",
        )

        if "приват" in lowered:
            mode = InputMode.PRIVACY
            message = (
                "Приватный режим включён. "
                "Облачные модели и сохранение "
                "истории отключены."
            )

        elif any(
            marker in lowered
            for marker in (
                "текстовый режим",
                "без микрофона",
            )
        ):
            mode = InputMode.TEXT_ONLY
            message = "Текстовый режим включён."

        elif any(
            marker in lowered
            for marker in (
                "непрерывный режим",
                "постоянно слушай",
            )
        ):
            mode = InputMode.CONTINUOUS
            message = (
                "Непрерывный голосовой режим включён."
            )

        elif any(
            marker in lowered
            for marker in (
                "режим пробуждения",
                "по слову нова",
                "wake word",
            )
        ):
            mode = InputMode.WAKE_WORD
            message = (
                "Режим активации по слову Нова включён."
            )

        elif any(
            marker in lowered
            for marker in (
                "push to talk",
                "нажми и говори",
                "режим кнопки",
            )
        ):
            mode = InputMode.PUSH_TO_TALK
            message = (
                "Режим нажми и говори включён."
            )

        elif any(
            marker in lowered
            for marker in (
                "спящий режим",
                "режим сна",
                "засыпай",
            )
        ):
            mode = InputMode.SLEEP
            message = "Режим сна включён."

        else:
            profile = self._parse_profile(
                lowered
            )

            if profile is not None:
                snapshot = (
                    self.preferences
                    .set_assistant_profile(
                        profile
                    )
                )

                message = (
                    f"Профиль '{profile.value}' "
                    "включён."
                )

                return AssistantResponse(
                    display_text=message,
                    speech_text=message,
                    success=True,
                    data={
                        "preferences": (
                            snapshot.to_dict()
                        ),
                        "direct_execution": True,
                        "model_calls": 0,
                    },
                )

            return self._clarification(
                (
                    "Какой режим включить: приватный, "
                    "текстовый, непрерывный, пробуждение, "
                    "нажми и говори или сон?"
                )
            )

        if self.mode_manager is not None:
            snapshot = (
                await self.mode_manager.set_mode(
                    mode
                )
            )
        else:
            snapshot = (
                self.preferences.set_input_mode(
                    mode
                )
            )


        return AssistantResponse(
            display_text=message,
            speech_text=message,
            success=True,
            data={
                "preferences": snapshot.to_dict(),
                "direct_execution": True,
                "model_calls": 0,
            },
        )

    @staticmethod
    def _parse_profile(
        lowered: str,
    ) -> AssistantProfile | None:
        if any(
            marker in lowered
            for marker in (
                "режим инженера",
                "инженерный профиль",
            )
        ):
            return AssistantProfile.ENGINEER

        if any(
            marker in lowered
            for marker in (
                "безопасный режим",
                "безопасный профиль",
            )
        ):
            return AssistantProfile.SAFE

        if any(
            marker in lowered
            for marker in (
                "режим помощника",
                "обычный режим",
                "профиль помощника",
            )
        ):
            return AssistantProfile.ASSISTANT

        if any(
            marker in lowered
            for marker in (
                "автономный режим",
                "автономный профиль",
                "автономная задача",
            )
        ):
            return (
                AssistantProfile.AUTONOMOUS_TASK
            )

        if any(
            marker in lowered
            for marker in (
                "локальный приватный режим",
                "приватный локальный режим",
                "только локально",
            )
        ):
            return (
                AssistantProfile.PRIVATE_LOCAL
            )

        return None

    @staticmethod
    def _clarification(
        question: str,
    ) -> AssistantResponse:
        return AssistantResponse(
            display_text=question,
            speech_text=question,
            success=False,
            error_code=(
                "CLARIFICATION_REQUIRED"
            ),
            data={
                "direct_execution": True,
                "model_calls": 0,
            },
        )
