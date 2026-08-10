# modules/routing/intent.py
from __future__ import annotations

import re

from modules.input_hub.models import (
    UserRequest,
)
from modules.routing.decision import (
    ExecutionDecision,
    ExecutionStrategy,
    IntentKind,
)


KNOWN_APPLICATIONS = (
    "obsidian",
    "обсидиан",
    "блокнот",
    "notepad",
    "калькулятор",
    "calculator",
    "проводник",
    "explorer",
    "discord",
    "дискорд",
    "telegram",
    "телеграм",
    "chrome",
    "хром",
    "браузер",
    "visual studio code",
    "vs code",
    "вс код",
    "steam",
    "стим",
    "spotify",
    "спотифай",
)

CHAT_PHRASES = {
    "привет",
    "пока",
    "спасибо",
    "как дела",
    "что делаешь",
    "понятно",
    "ясно",
    "круто",
    "отлично",
    "хаха",
}

MODEL_SELECTION_MARKERS = (
    "переключись на модель",
    "используй модель",
    "быструю модель",
    "умную модель",
    "локальную модель",
    "только бесплатные модели",
    "автоматический выбор модели",
)

MODE_SELECTION_MARKERS = (
    "включи приватный режим",
    "выключи приватный режим",
    "текстовый режим",
    "голосовой режим",
    "непрерывный режим",
    "режим пробуждения",
    "режим инженера",
    "безопасный режим",
)

WRITE_MARKERS = (
    "напиши",
    "вставь",
    "введи",
    "напечатай",
    "создай заметку",
    "сделай заметку",
    "добавь текст",
)

TOPIC_MARKERS = (
    " о ",
    " про ",
    " с текстом ",
    " содержание ",
    " заголовок ",
    " стих ",
    " заметку ",
)

COMPLEX_MARKERS = (
    "сначала",
    "затем",
    "после этого",
    "после чего",
    "и посмотри",
    "и проверь",
    "и чекни",
    "а в нем",
    "а в нём",
    "если успешно",
    "проверь результат",
    "выполни план",
    "сделай по шагам",
)

DEVELOPMENT_MARKERS = (
    "проект",
    "код",
    "тест",
    "pytest",
    "git",
    "docker",
    "kubernetes",
    "репозитор",
    "сервер",
    "рефактор",
    "ошибк",
    "traceback",
)
INVALID_APPLICATION_TARGETS = {
    "сайт",
    "страницу",
    "страница",
    "тест",
    "тесты",
    "проект",
    "проекте",
    "код",
    "команду",
    "команда",
    "терминал",
    "сервер",
    "процесс",
    "все",
    "все приложения",
    "все программы",
    "ало",
    "алло",
    "его",
    "ее",
    "её",
    "это",
    "там",
    "туда",
}

WEB_MARKERS = (
    "сайт",
    "страниц",
    "интернет",
    "веб-страниц",
    "документац",
    "ссылка",
    "url",
    "найди в сети",
    "поищи в сети",
    "прочитай сайт",
    "прочитай страницу",
    "открой сайт",
    "перейди на сайт",
)

WEB_SERVICE_MARKERS = (
    "openrouter",
    "open router",
    "опенроутер",
    "опен роутер",
)

WEB_SERVICE_URLS = {
    "telegram": "https://web.telegram.org/a/",
    "телеграм": "https://web.telegram.org/a/",
    "телегу": "https://web.telegram.org/a/",
}

GENERAL_ACTION_MARKERS = (
    "открой",
    "открыть",
    "включи",
    "сделай",
    "создай",
    "запусти",
    "удали",
    "перемести",
    "переименуй",
    "исправь",
    "обнови",
    "установи",
    "сохрани",
    "скопируй",
    "скачай",
    "загрузи",
    "найди",
    "поищи",
    "прочитай",
    "посмотри",
    "чекни",
    "перейди",
    "проверь",
    "проанализируй",
    "отправь",
    "заполни",
    "собери",
    "выполни",
    "напиши",
    "написать",
    "ответь",
    "ответить",
    "отправь сообщение",
    "send a message",
    "reply",
    "respond",
)

TELEGRAM_MESSAGE_ACTIONS = (
    "напиши", "написать", "ответь", "ответить", "отправь", "отправить",
    "сообщение", "перешли", "переслать", "send", "reply", "respond", "forward",
)

TELEGRAM_MARKERS = (
    "telegram", "телеграм", "телеграме", "телегу",
)



def normalize_request_text(
    text: str,
) -> str:
    normalized = str(text).lower()
    normalized = normalized.replace("ё", "е")
    # Common Whisper/Vosk transliterations must not turn an obvious app
    # command into a generic chat request.
    normalized = re.sub(
        r"\b(?:absidian|obsidien|обсидиан|абсидиан)\b",
        "obsidian",
        normalized,
    )
    normalized = re.sub(
        r"\s+",
        " ",
        normalized,
    )
    return normalized.strip(" \t\r\n.!?")


def _contains_any(
    text: str,
    markers: tuple[str, ...],
) -> bool:
    return any(
        marker in text
        for marker in markers
    )


def _extract_application_name(
    text: str,
) -> str | None:
    for application in sorted(
        KNOWN_APPLICATIONS,
        key=len,
        reverse=True,
    ):
        if application in text:
            return application

    patterns = (
        r"(?:открой|запусти|включи)\s+"
        r"([a-zа-я0-9 _.-]{2,50})",
        r"(?:закрой|выключи|заверши)\s+"
        r"([a-zа-я0-9 _.-]{2,50})",
        r"(?:напиши|вставь|введи)\s+"
        r"(?:в|во)\s+([a-zа-я0-9 _.-]{2,50})",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        candidate = match.group(1)

        candidate = re.split(
            (
                r"\s+(?:и|а потом|затем|"
                r"после этого|напиши|сделай)"
            ),
            candidate,
            maxsplit=1,
        )[0]

        candidate = candidate.strip(
            " ,.!?:;"
        )

        if (
            candidate
            and candidate
            not in INVALID_APPLICATION_TARGETS
        ):
            return candidate


    return None


def _requests_all_applications(
    text: str,
) -> bool:
    return any(
        marker in text
        for marker in (
            "все приложения",
            "всё приложения",
            "все программы",
            "все что можешь",
            "все, которые можешь",
            "каждое приложение",
        )
    )


def _requested_application_count(
    text: str,
) -> int | None:
    """Extract a bounded count from "open 5-10 applications" requests."""
    if not re.search(
        r"\b(?:приложени\w*|программ\w*)\b",
        text,
    ):
        return None

    range_match = re.search(
        r"\b(\d{1,2})\s*(?:-|–|—|до)\s*(\d{1,2})"
        r"\s+(?:приложени\w*|программ\w*)\b",
        text,
    )
    if range_match:
        # Use the conservative lower bound instead of opening the maximum.
        return min(
            int(range_match.group(1)),
            int(range_match.group(2)),
        )

    count_match = re.search(
        r"\b(\d{1,2})\s+(?:приложени\w*|программ\w*)\b",
        text,
    )
    if count_match:
        return int(count_match.group(1))

    return None


def _has_content_or_topic(
    text: str,
) -> bool:
    return _contains_any(
        f" {text} ",
        TOPIC_MARKERS,
    )


def _is_atomic_application_command(
    text: str,
    *,
    verbs: tuple[str, ...],
    application_name: str | None,
) -> bool:
    """
    Instant/direct допустим только когда вся фраза — одно действие.

    Иначе «открой браузер, а там проверь активность» преждевременно
    завершалось сразу после запуска Chrome.
    """
    if not application_name:
        return False

    verb_pattern = "|".join(
        re.escape(verb)
        for verb in sorted(
            verbs,
            key=len,
            reverse=True,
        )
    )
    match = re.fullmatch(
        rf"(?:{verb_pattern})\s+"
        r"(?:(?:приложение|программу)\s+)?"
        r"(?P<target>[^,;]{1,80})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return False

    target = match.group("target").strip()
    if re.search(
        (
            r"\b(?:и|а)\s+(?:посмотри|проверь|чекни|найди|"
            r"поищи|прочитай|перейди|нажми|заполни|напиши|"
            r"отправь)\b|"
            r"\b(?:а\s+)?в\s+н[её]м\b|"
            r"\bтам\b"
        ),
        target,
        flags=re.IGNORECASE,
    ):
        return False

    if target == application_name:
        return True

    return (
        application_name in KNOWN_APPLICATIONS
        and re.search(
            rf"\b{re.escape(application_name)}\b",
            target,
            flags=re.IGNORECASE,
        )
        is not None
    )


class DeterministicIntentRouter:
    """
    Детерминированный skill-first роутер.

    Этот модуль не выполняет инструменты. Он только определяет
    наиболее эффективную стратегию выполнения.
    """

    def route(
        self,
        request: UserRequest | str,
        *,
        has_image: bool | None = None,
    ) -> ExecutionDecision:
        """
        Определяет наиболее эффективную стратегию выполнения.

        Приоритет правил важен:

        1. Пустой запрос и vision.
        2. Локальные настройки и опасные массовые команды.
        3. Системные direct-команды.
        4. Веб-задачи.
        5. Запись в известное приложение.
        6. Инженерные задачи.
        7. Открытие и закрытие приложений.
        8. Общие многошаговые задачи.
        9. Неизвестные действия.
        10. Чат.
        """
        if isinstance(request, UserRequest):
            raw_text = request.text
            request_has_image = request.has_image
        else:
            raw_text = str(request)
            request_has_image = False

        if has_image is None:
            has_image = request_has_image

        text = normalize_request_text(
            raw_text
        )

        # -----------------------------------------------------
        # 1. ПУСТОЙ ЗАПРОС И VISION
        # -----------------------------------------------------

        if not text and not has_image:
            return ExecutionDecision.clarify(
                "Что нужно сделать?",
                reason="Пустой запрос.",
            )

        if has_image:
            return ExecutionDecision(
                strategy=ExecutionStrategy.PLAN,
                intent=IntentKind.VISION,
                required_tools={
                    "get_active_window_ui_tree",
                    "find_ui_element",
                    "ocr_screen",
                    "find_text_on_screen",
                },
                needs_model=True,
                needs_tools=True,
                expected_model_calls=1,
                expected_tool_calls=1,
                confidence=0.95,
                reason=(
                    "Запрос содержит изображение."
                ),
            )

        # -----------------------------------------------------
        # 2. КОРОТКИЙ ЧАТ И ЛОКАЛЬНЫЕ НАСТРОЙКИ
        # -----------------------------------------------------

        if text in CHAT_PHRASES:
            return ExecutionDecision.chat(
                reason=(
                    "Распознана короткая чатовая фраза."
                )
            )

        if _contains_any(
            text,
            MODEL_SELECTION_MARKERS,
        ):
            return ExecutionDecision(
                strategy=ExecutionStrategy.DIRECT,
                intent=IntentKind.MODEL_SELECTION,
                needs_model=False,
                needs_tools=False,
                expected_model_calls=0,
                expected_tool_calls=0,
                confidence=0.98,
                reason=(
                    "Локальная команда выбора модели."
                ),
                metadata={
                    "raw_text": raw_text,
                },
            )

        if _contains_any(
            text,
            MODE_SELECTION_MARKERS,
        ):
            return ExecutionDecision(
                strategy=ExecutionStrategy.DIRECT,
                intent=IntentKind.MODE_SELECTION,
                needs_model=False,
                needs_tools=False,
                expected_model_calls=0,
                expected_tool_calls=0,
                confidence=0.98,
                reason=(
                    "Локальная команда выбора режима."
                ),
                metadata={
                    "raw_text": raw_text,
                },
            )

        # -----------------------------------------------------
        # 3. ОПАСНЫЕ ИЛИ НЕОПРЕДЕЛЁННЫЕ BATCH-КОМАНДЫ
        # -----------------------------------------------------

        if _requests_all_applications(text):
            return ExecutionDecision.clarify(
                (
                    "Запуск всех приложений может перегрузить "
                    "систему. Какие именно приложения открыть?"
                ),
                intent=IntentKind.APPLICATION_BATCH,
                reason=(
                    "Массовый запуск без ограниченного списка "
                    "небезопасен и неэффективен."
                ),
            )

        # Telegram messages are external actions, never ordinary chat.  The
        # model needs the read-only resolver as well as the guarded send tool:
        # a nickname such as "Влад" may map to a longer contact name or to
        # several chats and must not be guessed.
        if (
            _contains_any(text, TELEGRAM_MARKERS)
            and _contains_any(text, TELEGRAM_MESSAGE_ACTIONS)
        ):
            return ExecutionDecision(
                strategy=ExecutionStrategy.SKILL,
                intent=IntentKind.MESSAGING,
                required_tools={
                    "mcp_telegram_business_resolve_chat",
                    "mcp_telegram_business_list_chats",
                    "mcp_telegram_business_send_message",
                    "mcp_telegram_resolve_chat",
                    "mcp_telegram_list_chats",
                    "mcp_telegram_send_message",
                    "mcp_telegram_forward_message",
                },
                needs_model=True,
                needs_tools=True,
                expected_model_calls=1,
                expected_tool_calls=2,
                confidence=0.99,
                reason=(
                    "Telegram message requires recipient resolution and a "
                    "confirmed network-write tool call."
                ),
            )

        requested_app_count = _requested_application_count(text)
        if requested_app_count is not None:
            if not 2 <= requested_app_count <= 10:
                return ExecutionDecision.clarify(
                    (
                        "За один запрос можно открыть от 2 до 10 "
                        "приложений. Сколько открыть?"
                    ),
                    intent=IntentKind.APPLICATION_BATCH,
                    reason="Количество приложений вне безопасного лимита.",
                )

            return ExecutionDecision(
                strategy=ExecutionStrategy.DIRECT,
                intent=IntentKind.APPLICATION_BATCH,
                required_tools={"open_application_batch"},
                selected_skill="open_application_batch",
                arguments={"count": requested_app_count},
                needs_model=False,
                needs_tools=True,
                expected_model_calls=0,
                expected_tool_calls=1,
                confidence=0.98,
                reason=(
                    "Ограниченный массовый запуск выполняется "
                    "специализированным batch-tool."
                ),
            )

        # -----------------------------------------------------
        # 4. ПРЯМЫЕ СИСТЕМНЫЕ КОМАНДЫ
        # -----------------------------------------------------

        if any(
            marker in text
            for marker in (
                "сколько времени",
                "который час",
                "точное время",
            )
        ):
            return ExecutionDecision(
                strategy=ExecutionStrategy.DIRECT,
                intent=IntentKind.SYSTEM_TIME,
                required_tools={
                    "get_current_time",
                },
                needs_model=False,
                needs_tools=True,
                expected_model_calls=0,
                expected_tool_calls=1,
                confidence=1.0,
                reason="Прямая команда времени.",
            )

        if any(
            marker in text
            for marker in (
                "громкость",
                "сделай громче",
                "сделай тише",
                "выключи звук",
                "включи звук",
            )
        ):
            return ExecutionDecision(
                strategy=ExecutionStrategy.DIRECT,
                intent=IntentKind.SYSTEM_VOLUME,
                required_tools={
                    "change_volume",
                },
                needs_model=False,
                needs_tools=True,
                expected_model_calls=0,
                expected_tool_calls=1,
                confidence=1.0,
                reason="Прямая команда громкости.",
            )

        # -----------------------------------------------------
        # 5. ВЕБ-ЗАДАЧИ
        #
        # Проверяются до общего application regex, чтобы фраза
        # «открой сайт» не превращалась в запуск приложения
        # с именем «сайт».
        # -----------------------------------------------------

        requested_web_service = next(
            (
                (name, url)
                for name, url in WEB_SERVICE_URLS.items()
                if re.search(rf"\b{re.escape(name)}\b", text)
            ),
            None,
        )
        requested_user_browser = (
            "google chrome"
            if any(marker in text for marker in ("гугл хром", "google chrome", "хром", "в гугле", "в google"))
            else None
        )

        explicit_open = any(
            marker in text
            for marker in ("открой", "открыть", "включи", "запусти", "open ")
        )

        if requested_web_service and requested_user_browser and explicit_open:
            _, service_url = requested_web_service
            return ExecutionDecision(
                strategy=ExecutionStrategy.DIRECT,
                intent=IntentKind.WEB,
                required_tools={"open_url_in_browser"},
                selected_skill="open_url_in_browser",
                arguments={
                    "app_name": requested_user_browser,
                    "url": service_url,
                },
                needs_model=False,
                needs_tools=True,
                expected_model_calls=0,
                expected_tool_calls=1,
                confidence=0.99,
                reason="Известный веб-сервис открывается одним браузерным skill без GUI-ввода.",
                metadata={"safe_direct_tool": True},
            )

        telegram_chat_match = re.search(
            r"(?:открой|открыть|покажи|найди)(?:\s+мне)?\s+чат(?:\s+с)?\s+(.+)$",
            text,
        )
        if telegram_chat_match:
            contact = telegram_chat_match.group(1).strip(" .,!?\"")
            if contact:
                return ExecutionDecision(
                    strategy=ExecutionStrategy.DIRECT,
                    intent=IntentKind.WEB,
                    required_tools={"open_telegram_chat"},
                    selected_skill="open_telegram_chat",
                    arguments={"contact": contact},
                    needs_model=False,
                    needs_tools=True,
                    expected_model_calls=0,
                    expected_tool_calls=1,
                    confidence=0.96,
                    reason="Поиск чата выполняется одним skill в активном Telegram Web.",
                    metadata={"safe_direct_tool": True},
                )

        browser_is_part_of_larger_goal = (
            "браузер" in text
            and not _is_atomic_application_command(
                text,
                verbs=(
                    "открой",
                    "запусти",
                    "включи",
                ),
                application_name="браузер",
            )
        )

        if (
            _contains_any(
                text,
                WEB_MARKERS,
            )
            or _contains_any(
                text,
                WEB_SERVICE_MARKERS,
            )
            or browser_is_part_of_larger_goal
        ):
            return ExecutionDecision(
                strategy=ExecutionStrategy.SKILL,
                intent=IntentKind.WEB,
                required_tools={
                    "browser_open_url",
                    "browser_get_page_text",
                    "browser_click",
                    "browser_fill",
                    "browser_screenshot",
                },
                needs_model=True,
                needs_tools=True,
                expected_model_calls=1,
                expected_tool_calls=2,
                confidence=0.9,
                reason=(
                    "Распознана веб-задача."
                ),
            )

        # -----------------------------------------------------
        # 6. ПРИЛОЖЕНИЕ И ЗАПИСЬ ТЕКСТА
        # -----------------------------------------------------

        application_name = (
            _extract_application_name(text)
        )

        has_write_intent = _contains_any(
            text,
            WRITE_MARKERS,
        )

        if (
            application_name
            and has_write_intent
        ):
            if not _has_content_or_topic(text):
                return ExecutionDecision.clarify(
                    (
                        "Какой текст или тему нужно "
                        f"записать в {application_name}?"
                    ),
                    intent=(
                        IntentKind.APPLICATION_WRITE
                    ),
                    reason=(
                        "Указано приложение, но отсутствует "
                        "содержание или тема."
                    ),
                )

            return ExecutionDecision(
                strategy=ExecutionStrategy.SKILL,
                intent=IntentKind.APPLICATION_WRITE,
                required_tools={
                    "write_in_application",
                },
                selected_skill=(
                    "write_in_application"
                ),
                arguments={
                    "app_name": application_name,
                },
                needs_model=True,
                needs_tools=True,
                expected_model_calls=1,
                expected_tool_calls=1,
                confidence=0.95,
                reason=(
                    "Запись в приложение должна выполняться "
                    "одним высокоуровневым skill."
                ),
            )

        # -----------------------------------------------------
        # 7. ИНЖЕНЕРНЫЕ ЗАДАЧИ
        #
        # Проверяются до generic application open, чтобы
        # «запусти тесты» не считалось запуском программы
        # с названием «тесты».
        # -----------------------------------------------------

        if _contains_any(
            text,
            DEVELOPMENT_MARKERS,
        ):
            has_complex_structure = (
                _contains_any(
                    text,
                    COMPLEX_MARKERS,
                )
            )

            strategy = (
                ExecutionStrategy.PLAN
                if has_complex_structure
                else ExecutionStrategy.SKILL
            )

            required_tools = {
                "inspect_project",
                "git_status",
                "run_terminal_command",
                "start_process",
                "read_process_output",
                "apply_text_patch",
            }

            if strategy == ExecutionStrategy.PLAN:
                required_tools.add(
                    "execute_plan"
                )

            return ExecutionDecision(
                strategy=strategy,
                intent=IntentKind.DEVELOPMENT,
                required_tools=required_tools,
                needs_model=True,
                needs_tools=True,
                expected_model_calls=(
                    1
                    if strategy
                    == ExecutionStrategy.SKILL
                    else 2
                ),
                expected_tool_calls=(
                    1
                    if strategy
                    == ExecutionStrategy.SKILL
                    else 4
                ),
                confidence=0.9,
                reason=(
                    "Распознана инженерная задача."
                    if strategy
                    == ExecutionStrategy.SKILL
                    else
                    "Распознана многошаговая "
                    "инженерная задача."
                ),
            )

        # -----------------------------------------------------
        # 8. ОБЫЧНОЕ ОТКРЫТИЕ И ЗАКРЫТИЕ ПРИЛОЖЕНИЙ
        # -----------------------------------------------------

        if (
            application_name
            and _is_atomic_application_command(
                text,
                verbs=(
                    "открой",
                    "запусти",
                    "включи",
                ),
                application_name=application_name,
            )
        ):
            return ExecutionDecision(
                strategy=ExecutionStrategy.DIRECT,
                intent=IntentKind.APPLICATION_OPEN,
                required_tools={
                    "open_application",
                },
                selected_skill=(
                    "open_application"
                ),
                arguments={
                    "app_name": application_name,
                },
                needs_model=False,
                needs_tools=True,
                expected_model_calls=0,
                expected_tool_calls=1,
                confidence=0.95,
                reason="Прямой запуск приложения.",
            )

        if (
            application_name
            and _is_atomic_application_command(
                text,
                verbs=(
                    "закрой",
                    "выключи",
                    "заверши",
                ),
                application_name=application_name,
            )
        ):
            return ExecutionDecision(
                strategy=ExecutionStrategy.DIRECT,
                intent=IntentKind.APPLICATION_CLOSE,
                required_tools={
                    "close_application",
                },
                selected_skill=(
                    "close_application"
                ),
                arguments={
                    "app_name": application_name,
                },
                needs_model=False,
                needs_tools=True,
                expected_model_calls=0,
                expected_tool_calls=1,
                confidence=0.95,
                reason="Прямое закрытие приложения.",
            )

        # -----------------------------------------------------
        # 9. ОБЩИЕ МНОГОШАГОВЫЕ ЗАДАЧИ
        # -----------------------------------------------------

        if _contains_any(
            text,
            COMPLEX_MARKERS,
        ):
            return ExecutionDecision(
                strategy=ExecutionStrategy.PLAN,
                intent=IntentKind.UNKNOWN_ACTION,
                required_tools={
                    "execute_plan",
                },
                selected_skill="execute_plan",
                needs_model=True,
                needs_tools=True,
                expected_model_calls=1,
                expected_tool_calls=1,
                confidence=0.7,
                reason=(
                    "Обнаружены признаки "
                    "многошаговой задачи."
                ),
            )

        # -----------------------------------------------------
        # 10. НЕИЗВЕСТНОЕ ОДИНОЧНОЕ ДЕЙСТВИЕ
        # -----------------------------------------------------

        if _contains_any(
            text,
            GENERAL_ACTION_MARKERS,
        ):
            return ExecutionDecision(
                strategy=ExecutionStrategy.SKILL,
                intent=IntentKind.UNKNOWN_ACTION,
                needs_model=True,
                needs_tools=True,
                expected_model_calls=1,
                expected_tool_calls=1,
                confidence=0.55,
                reason=(
                    "Обнаружен запрос действия, но прямой "
                    "intent не определён."
                ),
            )

        # -----------------------------------------------------
        # 11. ОБЫЧНЫЙ ЧАТ
        # -----------------------------------------------------

        return ExecutionDecision.chat(
            reason=(
                "Запрос не требует системного действия."
            )
        )
