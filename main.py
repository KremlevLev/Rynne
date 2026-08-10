# main.py
from __future__ import annotations
from pathlib import Path
import time
import threading

from modules.windows.process_manager import (
    ProcessManager
)
from modules.input_hub.wake_runtime import (
    WakeWordRuntime,
)
from modules.input_hub.wake_word import (
    WakeWordDetector,
)
from modules.application.preferences import (
    PreferencesManager,
)
from modules.application.interaction_modes import (
    InteractionModeManager,
)
from modules.application.request_dispatcher import (
    RequestDispatcher,
)
from modules.application.request_service import (
    RequestService,
)
from modules.domain.results import (
    AssistantResponse,
)
from modules.input_hub.coordinator import (
    InputCoordinator,
)
from modules.input_hub.models import (
    Attachment,
    AttachmentType,
    RequestSource,
    UserRequest,
)
from modules.routing.direct_executor import (
    DirectRequestExecutor,
)

from modules.input_hub.models import (
    InputMode,
)

from core.config import (
    NOVA_DESKTOP_UI,
    NOVA_DESKTOP_TRANSPORT,
    NOVA_PREMIUM_UI,
    NOVA_MAX_SUBAGENTS,
    NOVA_PROACTIVE_COOLDOWN_SECONDS,
    NOVA_PROACTIVE_BACKUP_CHECK_SECONDS,
    NOVA_PROACTIVE_PACKAGE_CHECK_SECONDS,
    NOVA_PROACTIVE_DISABLED_KINDS,
    NOVA_PROACTIVE_DISK_CHECK_SECONDS,
    NOVA_PROACTIVE_DISK_FREE_GB,
    NOVA_PROACTIVE_DISK_FREE_PERCENT,
    NOVA_PROACTIVE_SYSTEM_CHECK_SECONDS,
    NOVA_PROACTIVE_CPU_PERCENT,
    NOVA_PROACTIVE_MEMORY_PERCENT,
    NOVA_PROACTIVE_SYSTEM_CONSECUTIVE_SAMPLES,
    NOVA_PROACTIVE_VISION_CHECK_SECONDS,
    NOVA_PROACTIVE_VISION_MIN_CONFIDENCE,
    NOVA_PROACTIVE_ENABLED,
    NOVA_PROACTIVE_QUIET_END,
    NOVA_PROACTIVE_QUIET_START,
    NOVA_PROACTIVE_REPOSITORY_CHECK_SECONDS,
    NOVA_PROACTIVE_RESUME_PLAN_MINUTES,
    NOVA_PROACTIVE_STALE_PROCESS_HOURS,
    NOVA_PROACTIVE_UNCOMMITTED_MINUTES,
    NOVA_PROACTIVE_WORKFLOW_CHECK_SECONDS,
    NOVA_PROACTIVE_WORKFLOW_LOOKBACK_DAYS,
    NOVA_PROACTIVE_WORKFLOW_MIN_REPETITIONS,
    NOVA_PROACTIVE_WEBSITE_CHECK_SECONDS,
)

from modules.ui.desktop_service import (
    DesktopService,
)
from modules.ui.stdio_desktop_service import (
    StdioDesktopService,
)
from modules.ui.core_bridge import (
    CoreDesktopBridge,
)

from modules.tools.registry import (
    ALL_TOOLS,
    planning_tools,
    background_plan_tools,
    website_watch_tools,
    backup_watch_tools,
    package_update_tools,
)

from modules.agent.background_plans import (
    BackgroundPlanManager,
)
from modules.agent.proactive import (
    ProactiveSuggestionEngine,
)
from modules.agent.website_watches import WebsiteWatchManager
from modules.agent.backup_watches import BackupWatchManager
from modules.agent.package_updates import PackageUpdateManager
from modules.agent.system_health import (
    SystemHealthSampler,
)
from modules.agent.proactive_vision import (
    ProactiveVisionObserver,
)
from modules.tools.budgets import AgentBudget
from modules.agent.proactive_diagnostics import (
    ProactiveDiagnosticRunner,
)
from modules.agent.proactive_confirmation import (
    ProactiveConfirmationManager,
)
from modules.storage.artifacts import (
    ArtifactStore,
)
from modules.storage.database import Database
from modules.storage.conversations import (
    ConversationStore,
)
from modules.storage.memories import MemoryStore
from modules.windows.git_tools import (
    git_clone_repository,
    git_status,
    git_diff,
    git_log,
    git_commit,
    git_branch,
)
from modules.agent.plan_service import (
    PlanService,
)
from modules.agent.subagents import SubagentPool
from modules.browser.manager import (
    BrowserManager,
)
from modules.windows.project_inspector import (
    inspect_project,
)
from modules.windows.filesystem import (
    read_text_file,
    write_text_file,
    apply_text_patch,
    get_file_diff,
    search_files,
    rollback_file,
    undo_last_file_change,
)
import asyncio
import logging
import re
import socket
import sys
from typing import Any, Callable
from modules.domain.results import ToolResult
from modules.tools.skills import WindowsSkills
from modules.domain.windows_context import WindowsContext
from modules.domain.workspace_context import (
    WorkspaceContextResolver,
)

import keyboard
import winsound

from modules.application.agent import AgentService
from modules.application.speech import SpeechService
from modules.audio.stt import VoiceListener
from modules.brain.llm import NovaLLM
from modules.brain.memory import LocalMemory
from modules.domain.state import AssistantState, RuntimeState
from modules.tools.app_indexer import WindowsAppIndexer

from modules.tools.executor import (
    create_workspace_project,
    execute_python_code,
    mouse_click,
)
from modules.tools.os_utils import (
    change_volume,
    close_application,
    configure_assistant,
    control_smart_home,
    create_quick_note,
    execute_cmd_command,
    focus_window,
    get_clipboard_content,
    get_current_time,
    get_system_status,
    list_active_windows,
    manage_media,
    manage_windows,
    open_website,
    press_keyboard_combination,
    scrape_webpage,
    search_web_tavily,
    set_clipboard_content,
    set_timer,
    take_screenshot,
    type_text,
    run_terminal_command,
    get_active_window_title,
)
from modules.tools.runtime import ToolRegistry, ToolRunner
from modules.tools.tasks import (
    TaskScheduler,
    reminder_checker_worker,
)
from modules.ui.overlay import (
    should_start_legacy_overlay,
    start_overlay,
    stop_overlay,
    update_status,
)

process_manager = ProcessManager()
database = Database()
conversation_store = ConversationStore(
    database
)
memory_store = MemoryStore(database)
artifact_store = ArtifactStore()

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    ),
)
logger = logging.getLogger("Rynne")


def instance_lock_port(desktop_transport: str) -> int:
    # Tauri owns its Core lifecycle through the single-instance plugin. Using
    # an ephemeral port for its stdio sidecar avoids stale/elevated legacy
    # processes blocking a newly installed desktop update.
    return 0 if desktop_transport.strip().lower() == "stdio" else 29485


def acquire_instance_lock(port: int = 29485) -> socket.socket:
    instance_lock = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    )

    try:
        instance_lock.bind(("127.0.0.1", port))
    except OSError as exc:
        instance_lock.close()
        raise RuntimeError(
            "Rynne уже запущена в другом процессе."
        ) from exc

    return instance_lock


def should_pass_tools(request: str) -> bool:
    clean = request.lower().strip().rstrip(".!?")

    chat_phrases = {
        "привет",
        "пока",
        "как дела",
        "что делаешь",
        "спасибо",
        "круто",
        "отлично",
        "ясно",
        "понятно",
        "хаха",
    }

    return clean not in chat_phrases and len(clean.split()) > 1


def build_handlers(
    memory: LocalMemory,
    scheduler: TaskScheduler,
    app_launcher: WindowsAppIndexer,
    process_manager: ProcessManager,
    memory_store: MemoryStore,
    artifact_store: ArtifactStore,
    browser_manager: BrowserManager,
) -> dict[str, Callable[..., Any]]:
    
    windows_skills = WindowsSkills(
        app_launcher=app_launcher,
        list_windows=list_active_windows,
        focus_window=focus_window,
        press_hotkey=press_keyboard_combination,
        type_text=type_text,
        get_active_window_title=get_active_window_title,
    )
    def store_artifact_handler(
        content: str,
        artifact_type: str = "text",
    ) -> ToolResult:
        return artifact_store.store(
            content,
            artifact_type=artifact_type,
        )


    def read_artifact_handler(
        artifact_id: str,
    ) -> ToolResult:
        return artifact_store.read(artifact_id)


    def delete_artifact_handler(
        artifact_id: str,
    ) -> ToolResult:
        return artifact_store.delete(artifact_id)

    def save_memory_handler(
        key: str,
        value: str,
        category: str = "general",
    ) -> str:
        memory_store.save(
            key,
            value,
            category=category,
        )
        return f"Запомнила: {key} = {value}"


    def search_memory_handler(
        query: str,
    ) -> str:
        results = memory_store.search(query)

        if not results:
            return "Ничего не найдено."

        return "\n".join(
            f"- {r['key']}: {r['value']}"
            for r in results
        )


    def delete_memory_handler(
        key: str,
    ) -> str:
        memory_store.delete(key)
        return f"Удалила из памяти: {key}"


    def clear_all_memories_handler() -> str:
        memory_store.clear_all()
        return "Вся память очищена."


    def start_process_handler(
        command: list[str],
        label: str | None = None,
        cwd: str | None = None,
    ) -> ToolResult:
        return process_manager.start_process(
            command,
            label=label,
            cwd=cwd,
        )

    def get_process_status_handler(
        process_id: str,
    ) -> ToolResult:
        return process_manager.get_process_status(
            process_id
        )

    def read_process_output_handler(
        process_id: str,
        max_lines: int = 100,
        stream: str = "stdout",
    ) -> ToolResult:
        return process_manager.read_process_output(
            process_id,
            max_lines=max_lines,
            stream=stream,
        )

    def stop_process_handler(
        process_id: str,
        force: bool = False,
    ) -> ToolResult:
        return process_manager.stop_process(
            process_id,
            force=force,
        )

    def list_processes_handler() -> ToolResult:
        return process_manager.list_processes()

    def launch_application(app_name: str):
        return app_launcher.launch_by_name(app_name)

    def launch_application_batch(count: int) -> ToolResult:
        return app_launcher.launch_batch(count)

    def open_url_in_browser(app_name: str, url: str) -> ToolResult:
        return app_launcher.open_url_in_browser(app_name, url)

    def save_to_memory(text: str) -> str:
        return memory.add_document(text)

    def search_in_memory(query: str) -> str:
        results = memory.search(query)

        if not results:
            return "Ничего не найдено."

        return "\n".join(
            f"- {item['text']}"
            for item in results
        )

    return {
        "get_current_time": get_current_time,
        "open_application": launch_application,
        "open_application_batch": launch_application_batch,
        "open_url_in_browser": open_url_in_browser,
        "close_application": close_application,
        "type_text": type_text,
        "change_volume": change_volume,
        "open_website": open_website,
        "execute_cmd_command": execute_cmd_command,
        "get_system_status": get_system_status,
        "search_web_tavily": search_web_tavily,
        "manage_media": manage_media,
        "manage_windows": manage_windows,
        "create_quick_note": create_quick_note,
        "set_timer": set_timer,
        "control_smart_home": control_smart_home,
        "configure_assistant": configure_assistant,
        "save_to_memory": save_to_memory,
        "search_in_memory": search_in_memory,
        "set_reminder": scheduler.add_reminder,
        "get_active_reminders": scheduler.list_reminders,
        "execute_python_code": execute_python_code,
        "mouse_click": mouse_click,
        "press_keyboard_combination": (
            press_keyboard_combination
        ),
        "create_workspace_project": (
            create_workspace_project
        ),
        "write_in_application": (
            windows_skills.write_in_application),
        "open_telegram_chat": windows_skills.open_telegram_chat,
        "scrape_webpage": scrape_webpage,
        "get_clipboard_content": get_clipboard_content,
        "set_clipboard_content": set_clipboard_content,
        "run_terminal_command": run_terminal_command,
        "list_active_windows": list_active_windows,
        "focus_window": focus_window,
        "start_process": start_process_handler,
        "get_process_status": (
            get_process_status_handler
        ),
        "read_process_output": (
            read_process_output_handler
        ),
        "stop_process": stop_process_handler,
        "list_processes": (
            list_processes_handler
        ),
        "read_text_file": read_text_file,
        "write_text_file": write_text_file,
        "apply_text_patch": apply_text_patch,
        "get_file_diff": get_file_diff,
        "search_files": search_files,
        "rollback_file": rollback_file,
        "undo_last_file_change": (
            undo_last_file_change
        ),
        "git_clone_repository": git_clone_repository,
        "git_status": git_status,
        "git_diff": git_diff,
        "git_log": git_log,
        "git_commit": git_commit,
        "git_branch": git_branch,
        "inspect_project": inspect_project,
        "save_memory": save_memory_handler,
        "search_memory": search_memory_handler,
        "delete_memory": delete_memory_handler,
        "clear_all_memories": (
            clear_all_memories_handler
        ),
                "store_artifact": store_artifact_handler,
        "read_artifact": read_artifact_handler,
        "delete_artifact": delete_artifact_handler,
        "browser_start": (
            browser_manager.start
        ),
        "browser_open_url": (
            browser_manager.open_url
        ),
        "browser_get_page_text": (
            browser_manager.get_page_text
        ),
        "browser_click": (
            browser_manager.click
        ),
        "browser_fill": (
            browser_manager.fill
        ),
        "browser_screenshot": (
            browser_manager.screenshot
        ),
        "browser_status": (
            browser_manager.status
        ),
        "browser_close": (
            browser_manager.close
        ),

    }



def has_vision_trigger(text: str) -> bool:
    lowered = text.lower()
    triggers = {
        "на экране",
        "экран",
        "посмотри",
        "что это",
        "видишь",
        "исправь",
        "что тут",
        "изображено",
    }
    return any(trigger in lowered for trigger in triggers)


def should_capture_active_window(text: str) -> bool:
    lowered = text.lower()
    triggers = {
        "окно",
        "активное",
        "программу",
        "программа",
        "вкладка",
        "вкладку",
    }
    return any(trigger in lowered for trigger in triggers)


async def run_voice_loop(
    runtime: RuntimeState,
    speech: SpeechService,
    input_coordinator: InputCoordinator,
    listener: VoiceListener,
    windows_context: WindowsContext,
    preferences: PreferencesManager,
    event_handler=None,
) -> None:
    while not runtime.is_shutting_down:
        current_mode = (
            preferences.snapshot().input_mode
        )

        if (
            current_mode
            != InputMode.CONTINUOUS
            or not runtime.is_active
        ):
            await asyncio.sleep(0.2)
            continue
        if not runtime.is_active:
            await runtime.wait_until_active()

            if runtime.is_shutting_down:
                break

        await runtime.set_state(AssistantState.LISTENING)

        if event_handler is not None:
            event_handler(
                "voice_status",
                {
                    "status": "listening",
                    "message": "Слушаю микрофон…",
                },
            )

        user_request = await asyncio.to_thread(
            listener.listen,
            lambda: (
                not runtime.is_active
                or runtime.is_shutting_down
            ),
        )

        if runtime.is_shutting_down:
            break

        if not runtime.is_active:
            continue

        if not user_request:
            voice_error = str(
                getattr(listener, "last_error", "") or ""
            ).strip()
            if voice_error and event_handler is not None:
                event_handler(
                    "voice_status",
                    {
                        "status": "error",
                        "message": voice_error,
                    },
                )
                await asyncio.sleep(2.0)
            continue

        if event_handler is not None:
            event_handler(
                "voice_status",
                {
                    "status": "recognized",
                    "message": f"Распознано: {user_request}",
                },
            )

        lowered = user_request.lower()

        if re.search(
            r"\b(?:отключайся|выключись)\b",
            lowered,
        ):
            await speech.say(
                "Отключаюсь. До встречи.",
                priority=0,
            )
            await runtime.request_shutdown()
            break

        if re.search(
            r"\b(?:усни|спи|засыпай)\b",
            lowered,
        ):
            await speech.say(
                "Ухожу в спящий режим.",
                priority=1,
            )
            await runtime.sleep()
            continue

        await runtime.set_state(AssistantState.THINKING)

        image_path = ""
        has_image = has_vision_trigger(user_request)

        if has_image:
            image_path = await asyncio.to_thread(
                take_screenshot,
                should_capture_active_window(user_request),
            )

            if image_path:
                has_image = True
            else:
                has_image = False
        resolved_request = (
            windows_context.resolve_reference(
                user_request
            )
        )

        request = UserRequest.from_voice(
            resolved_request,
            wake_word=False,
            session_id=None,
            metadata={
                "original_transcription": (
                    user_request
                ),
                "has_image": has_image,
            },
        )

        if has_image and image_path:
            from modules.input_hub.models import (
                Attachment,
                AttachmentType,
            )

            request.attachments.append(
                Attachment(
                    attachment_type=(
                        AttachmentType.SCREENSHOT
                    ),
                    path=image_path,
                    display_name=(
                        "Снимок экрана"
                    ),
                )
            )

        submitted = (
            await input_coordinator.submit(
                request
            )
        )

        if not submitted:
            await speech.say(
                (
                    "Сэр, не удалось добавить "
                    "запрос в очередь."
                ),
                priority=3,
            )

            if runtime.is_shutting_down:
                raise
            
            logger.info(
                "Озвучивание ответа прервано пользователем."
            )



async def async_main() -> None:
    instance_lock = acquire_instance_lock(
        instance_lock_port(NOVA_DESKTOP_TRANSPORT)
    )
    workspace_context = WorkspaceContextResolver()
    await asyncio.to_thread(
        workspace_context.observe_foreground
    )
    desktop_service = (
        StdioDesktopService()
        if NOVA_DESKTOP_TRANSPORT == "stdio"
        else DesktopService()
    )

    if NOVA_DESKTOP_UI:
        try:
            desktop_service.start(premium=NOVA_PREMIUM_UI)
        except Exception:
            logger.exception(
                "Не удалось запустить Desktop UI."
            )


    windows_context = WindowsContext()
    legacy_overlay_enabled = should_start_legacy_overlay(
        NOVA_DESKTOP_TRANSPORT
    )
    if legacy_overlay_enabled:
        start_overlay()
    runtime = RuntimeState(
        update_status
        if legacy_overlay_enabled
        else None
    )
    speech = SpeechService(
        runtime,
        event_handler=(
            desktop_service.publish
            if NOVA_DESKTOP_UI
            else None
        ),
        # Prepare Silero in a background thread before the first response.
        # The UI/Core event loop remains responsive and voice_status exposes
        # loading/ready/error instead of making the first reply silently wait.
        warm_up_on_start=True,
    )
    await speech.start()
    preferences = PreferencesManager()
    browser_manager = BrowserManager(
    headless=False
)

    memory = LocalMemory()
    scheduler = TaskScheduler()
    app_launcher = await asyncio.to_thread(
        WindowsAppIndexer
    )
    def publish_voice_activity(source: str):
        def publish(phase: str, level: float) -> None:
            if NOVA_DESKTOP_UI:
                desktop_service.publish(
                    "voice_activity",
                    {
                        "source": source,
                        "phase": phase,
                        "level": round(level, 3),
                    },
                )
        return publish

    listener = VoiceListener(
        activity_callback=publish_voice_activity("stt"),
    )
    llm = NovaLLM()
    subagent_pool = SubagentPool(
        llm,
        event_handler=(desktop_service.publish if NOVA_DESKTOP_UI else None),
        max_agents=NOVA_MAX_SUBAGENTS,
    )

    handlers = build_handlers(
        memory,
        scheduler,
        app_launcher,
        process_manager,
        memory_store,
        artifact_store,
        browser_manager,
    )
    # Dynamic tools must be bound before the strict legacy registry validates
    # that every published schema has an executable handler.
    handlers["delegate_subagents"] = subagent_pool.delegate_subagents

    # ---------------------------------------------------------
    # СОЗДАНИЕ TOOL REGISTRY И ОТЛОЖЕННАЯ РЕГИСТРАЦИЯ ПЛАНОВ
    # ---------------------------------------------------------

    # Инструменты планирования нельзя зарегистрировать сразу:
    # PlanService зависит от уже созданных registry и runner.
    deferred_tool_schemas = (
        planning_tools
        + background_plan_tools
        + website_watch_tools
        + backup_watch_tools
        + package_update_tools
    )

    deferred_tool_names = {
        tool_schema["function"]["name"]
        for tool_schema in deferred_tool_schemas
    }

    # Первоначально создаём registry без инструментов планирования.
    base_tool_schemas = [
        tool_schema
        for tool_schema in ALL_TOOLS
        if (
            tool_schema["function"]["name"]
            not in deferred_tool_names
        )
    ]
    # =========================================================
    # TOOL PLATFORM
    # =========================================================

    registry = ToolRegistry.from_legacy(
        base_tool_schemas,
        handlers,
    )

    runner = ToolRunner(
        registry,
        event_sink=(
            desktop_service.publish
            if NOVA_DESKTOP_UI
            else None
        ),
    )

    # =========================================================
    # PLAN SERVICES
    #
    # Они создаются после registry и runner, потому что сами
    # используют ToolRunner для выполнения шагов.
    # =========================================================

    plan_service = PlanService(
        registry=registry,
        runner=runner,
    )

    background_plan_manager = (
        BackgroundPlanManager(
            plan_service,
            database,
        )
    )

    proactive_engine = ProactiveSuggestionEngine(
        database,
        cooldown_seconds=NOVA_PROACTIVE_COOLDOWN_SECONDS,
        quiet_hours=(
            NOVA_PROACTIVE_QUIET_START,
            NOVA_PROACTIVE_QUIET_END,
        ),
        disabled_kinds=NOVA_PROACTIVE_DISABLED_KINDS,
    )
    proactive_confirmation = ProactiveConfirmationManager()
    website_watch_manager = WebsiteWatchManager(database)
    backup_watch_manager = BackupWatchManager(database)
    package_update_manager = PackageUpdateManager(database)
    system_health_sampler = SystemHealthSampler()

    def handle_tool_event(
        event_type: str,
        payload: dict,
    ) -> None:
        if NOVA_DESKTOP_UI:
            desktop_service.publish(event_type, payload)
        remote_chat_id = payload.get("telegram_remote_chat_id")
        if event_type == "approval_requested" and remote_chat_id is None:
            current_request = request_service.current_request
            if current_request is not None:
                remote_chat_id = current_request.metadata.get("telegram_remote_chat_id")
        if event_type == "approval_requested" and remote_chat_id is not None:
            try:
                approval_payload = dict(payload)
                approval_payload["telegram_remote_chat_id"] = int(remote_chat_id)
                asyncio.get_running_loop().create_task(
                    send_telegram_remote_approval(approval_payload),
                    name="nova-telegram-approval-request",
                )
            except RuntimeError:
                logger.warning("Could not schedule Telegram approval outside the event loop.")
        if (
            NOVA_PROACTIVE_ENABLED
            and "workflow_suggested"
            not in NOVA_PROACTIVE_DISABLED_KINDS
            and event_type == "tool_completed"
        ):
            proactive_engine.record_tool_completion(payload)

    runner.set_event_sink(handle_tool_event)

    async def publish_proactive_suggestion(suggestion) -> None:
        pending = proactive_confirmation.arm(suggestion)
        desktop_service.publish(
            "proactive_suggestion",
            suggestion.to_dict(),
        )
        if not preferences.snapshot().tts_enabled:
            return
        concise_message = str(suggestion.message).split("\n\n", 1)[0]
        concise_message = concise_message[:220].rstrip()
        voice_text = f"{suggestion.title}. {concise_message}"
        if pending is not None:
            voice_text += (
                " Скажите «Рин, давай» для подтверждения "
                "или «Рин, не сейчас» для отмены."
            )
        await speech.say(
            voice_text,
            priority=4,
            wait=False,
        )

    async def proactive_worker() -> None:
        next_disk_check = 0.0
        next_system_check = 0.0
        next_repository_check = 0.0
        next_workflow_check = 0.0
        next_website_check = 0.0
        next_backup_check = 0.0
        next_package_check = 0.0
        while not runtime.shutdown_event.is_set():
            if NOVA_PROACTIVE_ENABLED:
                suggestions = list(
                    proactive_engine.observe_background_plans(
                        background_plan_manager._plans.values()
                    )
                )
                suggestions.extend(
                    proactive_engine.observe_incomplete_plans(
                        background_plan_manager._plans.values(),
                        suggest_after_seconds=(
                            NOVA_PROACTIVE_RESUME_PLAN_MINUTES
                            * 60
                        ),
                    )
                )
                process_result = await asyncio.to_thread(
                    process_manager.list_processes
                )
                process_items = (
                    process_result.data.get("processes", [])
                    if process_result.success
                    else []
                )
                suggestions.extend(
                    proactive_engine.observe_processes(
                        process_items
                    )
                )
                suggestions.extend(
                    proactive_engine.observe_stale_processes(
                        process_items,
                        stale_after_seconds=(
                            NOVA_PROACTIVE_STALE_PROCESS_HOURS
                            * 60
                            * 60
                        ),
                    )
                )
                loop_now = asyncio.get_running_loop().time()
                if loop_now >= next_system_check:
                    health_snapshot = await asyncio.to_thread(
                        system_health_sampler.sample
                    )
                    suggestions.extend(
                        proactive_engine.observe_system_health(
                            health_snapshot.to_dict(),
                            cpu_percent_threshold=(
                                NOVA_PROACTIVE_CPU_PERCENT
                            ),
                            memory_percent_threshold=(
                                NOVA_PROACTIVE_MEMORY_PERCENT
                            ),
                            consecutive_samples=(
                                NOVA_PROACTIVE_SYSTEM_CONSECUTIVE_SAMPLES
                            ),
                            max_sample_gap_seconds=max(
                                5.0,
                                NOVA_PROACTIVE_SYSTEM_CHECK_SECONDS
                                * 2.5,
                            ),
                        )
                    )
                    next_system_check = (
                        loop_now
                        + max(
                            5.0,
                            NOVA_PROACTIVE_SYSTEM_CHECK_SECONDS,
                        )
                    )
                if loop_now >= next_disk_check:
                    suggestions.extend(
                        proactive_engine.observe_disk_space(
                            Path.cwd(),
                            free_percent_threshold=(
                                NOVA_PROACTIVE_DISK_FREE_PERCENT
                            ),
                            free_bytes_threshold=int(
                                NOVA_PROACTIVE_DISK_FREE_GB
                                * 1024**3
                            ),
                        )
                    )
                    next_disk_check = (
                        loop_now
                        + max(
                            5.0,
                            NOVA_PROACTIVE_DISK_CHECK_SECONDS,
                        )
                    )
                if loop_now >= next_repository_check:
                    repository_result = await asyncio.to_thread(
                        git_status,
                        str(Path.cwd()),
                    )
                    if repository_result.success:
                        suggestions.extend(
                            proactive_engine.observe_repository(
                                Path.cwd(),
                                str(
                                    repository_result.data.get(
                                        "raw",
                                        "",
                                    )
                                ),
                                uncommitted_after_seconds=(
                                    NOVA_PROACTIVE_UNCOMMITTED_MINUTES
                                    * 60
                                ),
                            )
                        )
                    next_repository_check = (
                        loop_now
                        + max(
                            5.0,
                            NOVA_PROACTIVE_REPOSITORY_CHECK_SECONDS,
                        )
                    )
                if loop_now >= next_workflow_check:
                    suggestions.extend(
                        proactive_engine.observe_repeated_actions(
                            min_repetitions=(
                                NOVA_PROACTIVE_WORKFLOW_MIN_REPETITIONS
                            ),
                            lookback_seconds=(
                                NOVA_PROACTIVE_WORKFLOW_LOOKBACK_DAYS
                                * 24
                                * 60
                                * 60
                            ),
                        )
                    )
                    next_workflow_check = (
                        loop_now
                        + max(
                            5.0,
                            NOVA_PROACTIVE_WORKFLOW_CHECK_SECONDS,
                        )
                    )
                if loop_now >= next_website_check:
                    changes = await website_watch_manager.poll()
                    website_suggestions = (
                        proactive_engine.observe_website_changes(
                            changes
                        )
                    )
                    for suggestion in website_suggestions:
                        matching_change = next(
                            (
                                change
                                for change in changes
                                if suggestion.source_key
                                == (
                                    "website:"
                                    f"{change['watch_id']}:revision:"
                                    f"{change['revision']}"
                                )
                            ),
                            None,
                        )
                        if matching_change is not None:
                            website_watch_manager.mark_notified(
                                str(matching_change["watch_id"]),
                                int(matching_change["revision"]),
                            )
                    suggestions.extend(website_suggestions)
                    next_website_check = (
                        loop_now
                        + max(
                            30.0,
                            NOVA_PROACTIVE_WEBSITE_CHECK_SECONDS,
                        )
                    )
                if loop_now >= next_backup_check:
                    backup_statuses = await backup_watch_manager.poll()
                    suggestions.extend(
                        proactive_engine.observe_backup_statuses(
                            backup_statuses
                        )
                    )
                    next_backup_check = (
                        loop_now
                        + max(
                            30.0,
                            NOVA_PROACTIVE_BACKUP_CHECK_SECONDS,
                        )
                    )
                if loop_now >= next_package_check:
                    package_statuses = await package_update_manager.poll()
                    suggestions.extend(
                        proactive_engine.observe_package_updates(
                            package_statuses
                        )
                    )
                    next_package_check = (
                        loop_now
                        + max(
                            300.0,
                            NOVA_PROACTIVE_PACKAGE_CHECK_SECONDS,
                        )
                    )
                for suggestion in suggestions:
                    await publish_proactive_suggestion(suggestion)
            try:
                await asyncio.wait_for(
                    runtime.shutdown_event.wait(),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                pass

    proactive_task = asyncio.create_task(
        proactive_worker(),
        name="nova-proactive-worker",
    )

    planning_handlers = {
        "execute_plan": (
            plan_service.execute_plan
        ),
        "get_plan_status": (
            plan_service.get_plan_status
        ),
        "cancel_plan": (
            plan_service.cancel_plan
        ),
    }

    background_plan_handlers = {
        "start_background_plan": (
            background_plan_manager.start_plan
        ),
        "get_background_plan_status": (
            background_plan_manager.get_status
        ),
        "list_background_plans": (
            background_plan_manager.list_plans
        ),
        "retry_background_plan": (
            background_plan_manager.retry_plan
        ),
        "cancel_background_plan": (
            background_plan_manager.cancel_plan
        ),
    }
    website_watch_handlers = {
        "watch_website": website_watch_manager.add_watch,
        "list_website_watches": (
            website_watch_manager.list_watches
        ),
        "remove_website_watch": (
            website_watch_manager.remove_watch
        ),
    }
    backup_watch_handlers = {
        "watch_backup": backup_watch_manager.add_watch,
        "list_backup_watches": (
            backup_watch_manager.list_watches
        ),
        "remove_backup_watch": (
            backup_watch_manager.remove_watch
        ),
    }
    package_update_handlers = {
        "watch_package_update": package_update_manager.add_watch,
        "list_package_update_watches": (
            package_update_manager.list_watches
        ),
        "remove_package_update_watch": (
            package_update_manager.remove_watch
        ),
    }

    # Deferred tools нельзя регистрировать до создания
    # PlanService и BackgroundPlanManager.
    for tool_schema in planning_tools:
        tool_name = (
            tool_schema["function"]["name"]
        )

        registry.register(
            schema=tool_schema,
            handler=planning_handlers[
                tool_name
            ],
        )

    execute_plan_definition = registry.get("execute_plan")
    if execute_plan_definition is not None:
        # Nested steps inherit the remote workspace and approval destination.
        execute_plan_definition.inject_context = True

    for tool_schema in background_plan_tools:
        tool_name = (
            tool_schema["function"]["name"]
        )

        registry.register(
            schema=tool_schema,
            handler=background_plan_handlers[
                tool_name
            ],
        )

    for tool_schema in website_watch_tools:
        tool_name = tool_schema["function"]["name"]
        registry.register(
            schema=tool_schema,
            handler=website_watch_handlers[tool_name],
        )

    for tool_schema in backup_watch_tools:
        tool_name = tool_schema["function"]["name"]
        registry.register(
            schema=tool_schema,
            handler=backup_watch_handlers[tool_name],
        )

    for tool_schema in package_update_tools:
        tool_name = tool_schema["function"]["name"]
        registry.register(
            schema=tool_schema,
            handler=package_update_handlers[tool_name],
        )

    missing_deferred_tools = (
        deferred_tool_names
        - registry.names
    )

    if missing_deferred_tools:
        raise RuntimeError(
            (
                "Не зарегистрированы отложенные "
                "инструменты: "
                + ", ".join(
                    sorted(
                        missing_deferred_tools
                    )
                )
            )
        )

    logger.info(
        "Tool registry собран. Инструментов: %s",
        len(registry.names),
    )

    # =========================================================
    # MCP INTEGRATION (OPTIONAL)
    # =========================================================
    # MCP tools are dynamically added if servers are available.
    # This is non-blocking - if MCP fails, the agent continues without it.
    
    mcp_gateway = None
    try:
        from modules.agent.mcp_integration import bootstrap_mcp_with_auto_discovery
        
        mcp_gateway = await bootstrap_mcp_with_auto_discovery(registry)
        
        # Update recovery system with MCP tools
        from modules.agent.recovery import set_mcp_recovery_tools
        set_mcp_recovery_tools(mcp_gateway.get_available_tools())
        
        logger.info(
            "MCP tools integrated. Available tools: %s",
            len(mcp_gateway.get_available_tools()),
        )
    except Exception as mcp_exc:
        logger.warning(
            "MCP integration failed (continuing without MCP): %s",
            mcp_exc,
        )

    # =========================================================
    # AGENT SERVICE
    # =========================================================

    from modules.agent.execution_memory import ExecutionMemory
    from modules.agent.skill_library import SkillLibrary

    agent = AgentService(
        llm,
        registry,
        runner,
        execution_memory=ExecutionMemory(),
        skill_library=SkillLibrary(),
        isolated_history=True,
        subagent_pool=subagent_pool,
        progress_handler=(
            desktop_service.publish
            if NOVA_DESKTOP_UI
            else None
        ),
    )

    # =========================================================
    # NOVA 2.0 INPUT HUB И НАСТРОЙКИ
    # =========================================================

    mode_manager = InteractionModeManager(
        preferences=preferences,
        runtime=runtime,
        speech=speech,
    )

    input_coordinator = InputCoordinator()
    proactive_vision_observer = (
        ProactiveVisionObserver(
            llm,
            window_title_provider=(
                get_active_window_title
            ),
            min_confidence=(
                NOVA_PROACTIVE_VISION_MIN_CONFIDENCE
            ),
        )
    )
    def active_workspace_path() -> str | None:
        snapshot = workspace_context.observe_foreground()
        return str(snapshot.path) if snapshot is not None else None

    proactive_diagnostic_agent = AgentService(
        llm,
        registry,
        runner,
        execution_memory=ExecutionMemory(),
    )
    proactive_diagnostic_agent.default_budget = AgentBudget(
        max_logical_model_calls=4,
        max_tool_calls=3,
        max_wall_time_seconds=45.0,
    )
    proactive_diagnostic_runner = ProactiveDiagnosticRunner(
        proactive_diagnostic_agent,
        workspace_provider=active_workspace_path,
    )
    proactive_vision_check_requested = asyncio.Event()

    async def proactive_vision_worker() -> None:
        manual_check = False
        while not runtime.shutdown_event.is_set():
            preference_snapshot = (
                preferences.snapshot()
            )
            enabled = (
                NOVA_PROACTIVE_ENABLED
                and preference_snapshot
                .proactive_vision_enabled
                and preference_snapshot.cloud_enabled
                and runtime.state
                in {
                    AssistantState.SLEEPING,
                    AssistantState.LISTENING,
                }
                and proactive_engine.can_observe(
                    "proactive_visual_help",
                    ignore_quiet_hours=True,
                )
            )
            delay = 2.0
            if enabled:
                try:
                    if manual_check:
                        if NOVA_DESKTOP_UI:
                            desktop_service.publish(
                                "proactive_status",
                                {
                                    "phase": "scanning",
                                    "message": "Переключитесь на нужное окно — снимок через 3 секунды…",
                                    "manual": True,
                                },
                            )
                        await asyncio.sleep(3.0)
                    if NOVA_DESKTOP_UI:
                        desktop_service.publish(
                            "proactive_status",
                            {
                                "phase": "scanning",
                                "message": "Проверяю активное окно…",
                            },
                        )
                    insight = (
                        await proactive_vision_observer
                        .inspect(force=manual_check)
                    )
                    suggestion_count = 0
                    if insight is not None:
                        if NOVA_DESKTOP_UI:
                            desktop_service.publish(
                                "proactive_status",
                                {
                                    "phase": "investigating",
                                    "message": (
                                        "Нашла повод помочь — собираю "
                                        "безопасные факты под капотом…"
                                    ),
                                    "manual": manual_check,
                                },
                            )
                        insight = await proactive_diagnostic_runner.investigate(
                            insight
                        )
                        for suggestion in (
                            proactive_engine
                            .observe_visual_insight(
                                insight,
                                ignore_quiet_hours=True,
                                force=manual_check,
                            )
                        ):
                            await publish_proactive_suggestion(suggestion)
                            suggestion_count += 1
                    if NOVA_DESKTOP_UI:
                        outcome = dict(
                            proactive_vision_observer.last_outcome
                        )
                        status_message = (
                            "Нашла повод помочь"
                            if suggestion_count
                            else str(
                                outcome.get("message")
                                or "Проверено — явных проблем не найдено."
                            )
                        )
                        desktop_service.publish(
                            "proactive_status",
                            {
                                "phase": "checked",
                                "message": status_message,
                                "checked_at": time.time(),
                                "suggestions": suggestion_count,
                                "outcome": str(outcome.get("code") or "unknown"),
                                "manual": manual_check,
                            },
                        )
                        if manual_check and not suggestion_count:
                            desktop_service.publish(
                                "proactive_check_result",
                                {
                                    "message": status_message,
                                    "outcome": str(outcome.get("code") or "unknown"),
                                },
                            )
                            if preferences.snapshot().tts_enabled:
                                await speech.say(
                                    (
                                        "Проверка Rynne рядом завершена. "
                                        + status_message
                                    ),
                                    priority=4,
                                    wait=False,
                                )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception(
                        "Сбой opt-in режима «Rynne рядом»."
                    )
                    if NOVA_DESKTOP_UI:
                        desktop_service.publish(
                            "proactive_status",
                            {
                                "phase": "error",
                                "message": f"Проверка не удалась: {exc}",
                            },
                        )
                delay = max(
                    30.0,
                    NOVA_PROACTIVE_VISION_CHECK_SECONDS,
                )
                manual_check = False

            try:
                shutdown_waiter = asyncio.create_task(
                    runtime.shutdown_event.wait()
                )
                check_waiter = asyncio.create_task(
                    proactive_vision_check_requested.wait()
                )
                done, pending = await asyncio.wait(
                    {shutdown_waiter, check_waiter},
                    timeout=delay,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(
                        *pending,
                        return_exceptions=True,
                    )
                if check_waiter in done:
                    proactive_vision_check_requested.clear()
                    manual_check = True
            except asyncio.TimeoutError:
                pass

    direct_executor = DirectRequestExecutor(
        runner=runner,
        preferences=preferences,
        session_id=agent.session_id,
        mode_manager=mode_manager,
    )

    request_dispatcher = RequestDispatcher(
        agent=agent,
        direct_executor=direct_executor,
        intent_router=agent.intent_router,
    )

    # =========================================================
    # ОБРАБОТЧИК ГОТОВОГО ОТВЕТА
    #
    # Функция должна быть объявлена ДО создания RequestService.
    # =========================================================

    async def send_telegram_remote_reply(chat_id: int, text: str) -> bool:
        if mcp_gateway is None:
            return False
        tool_name = "mcp_telegram_business_send_control_reply"
        if tool_name not in mcp_gateway.get_available_tools():
            return False
        result = await mcp_gateway.call_tool(
            tool_name,
            {"chat_id": int(chat_id), "text": str(text)[:4096]},
        )
        if not result.success:
            logger.warning("Telegram Remote reply failed: %s", result.message)
        return result.success

    async def send_telegram_remote_approval(payload: dict) -> bool:
        if mcp_gateway is None:
            return False
        tool_name = "mcp_telegram_business_send_control_approval"
        if tool_name not in mcp_gateway.get_available_tools():
            return False
        result = await mcp_gateway.call_tool(
            tool_name,
            {
                "chat_id": int(payload["telegram_remote_chat_id"]),
                "operation_id": str(payload["operation_id"]),
                "text": str(payload.get("message") or "Подтвердите действие."),
            },
        )
        if not result.success:
            logger.warning("Telegram Remote approval request failed: %s", result.message)
        return result.success

    async def handle_request_response(
        request: UserRequest,
        response: AssistantResponse,
    ) -> None:
        print(
            f"\n[Rynne]: "
            f"{response.display_text}\n"
        )

        # Передаём точный ответ в Desktop UI.
        desktop_service.publish(
            "assistant_message",
            {
                "request_id": (
                    request.request_id
                ),
                "display_text": (
                    response.display_text
                ),
                "speech_text": (
                    response.speech_text
                ),
                "success": response.success,
                "error_code": (
                    response.error_code
                ),
                "data": response.data,
            },
        )

        remote_chat_id = request.metadata.get("telegram_remote_chat_id")
        if remote_chat_id is not None:
            try:
                await send_telegram_remote_reply(
                    int(remote_chat_id),
                    response.display_text,
                )
            except Exception:
                logger.exception("Could not return Rynne response through Telegram Remote.")

        preferences_snapshot = (
            preferences.snapshot()
        )

        # В режиме с отключённым TTS экранный ответ всё равно
        # публикуется, но голос не воспроизводится.
        if (
            remote_chat_id is None
            and preferences_snapshot.tts_enabled
            and response.speech_text.strip()
        ):
            await speech.say(
                response.speech_text,
                priority=5,
                wait=False,
            )

    async def intercept_proactive_voice(
        request: UserRequest,
    ) -> AssistantResponse | None:
        if not request.is_voice or proactive_confirmation.pending() is None:
            return None
        decision = proactive_confirmation.classify_voice(request.text)
        if decision is None:
            return None
        if decision == "dismissed":
            pending = proactive_confirmation.reject()
            if pending is not None:
                proactive_engine.record_feedback(
                    pending.event_id,
                    "dismissed",
                    source="voice",
                )
                desktop_service.publish(
                    "proactive_confirmation_resolved",
                    {
                        "event_id": pending.event_id,
                        "decision": "dismissed",
                    },
                )
            return AssistantResponse(
                display_text="Хорошо, не буду выполнять эту подсказку.",
                speech_text="Хорошо, не буду.",
                success=True,
            )

        pending = proactive_confirmation.confirm()
        if pending is None:
            return AssistantResponse(
                display_text="Время подтверждения истекло.",
                speech_text="Время подтверждения истекло.",
                success=False,
                error_code="PROACTIVE_CONFIRMATION_EXPIRED",
            )
        original_confirmation = request.text
        request.text = pending.request
        request.metadata.update({
            "proactive_suggestion_accepted": True,
            "proactive_event_id": pending.event_id,
            "voice_confirmation_text": original_confirmation,
        })
        if pending.context_key.startswith("visual:"):
            context_path = (
                proactive_vision_observer.context_store.materialize_once(
                    pending.context_key
                )
            )
            if context_path:
                request.attachments.append(Attachment(
                    attachment_type=AttachmentType.SCREENSHOT,
                    path=context_path,
                    display_name="Контекст активного окна",
                    metadata={
                        "proactive_context": True,
                        "delete_after_read": True,
                    },
                ))
        proactive_engine.record_feedback(
            pending.event_id,
            "accepted",
            source="voice",
        )
        desktop_service.publish(
            "proactive_confirmation_resolved",
            {
                "event_id": pending.event_id,
                "decision": "accepted",
            },
        )
        return None

    # =========================================================
    # REQUEST SERVICE
    # =========================================================

    request_service = RequestService(
        coordinator=input_coordinator,
        dispatcher=request_dispatcher,
        response_handler=(
            handle_request_response
        ),
        event_handler=(
            desktop_service.publish
            if NOVA_DESKTOP_UI
            else None
        ),
        request_enricher=(
            lambda request: asyncio.to_thread(
                workspace_context.enrich,
                request,
            )
        ),
        request_interceptor=intercept_proactive_voice,
    )

    request_service_task = asyncio.create_task(
        request_service.run(
            runtime.shutdown_event
        ),
        name="nova-request-service",
    )

    async def telegram_remote_worker() -> None:
        if mcp_gateway is None:
            return
        poll_tool = "mcp_telegram_business_poll_control_commands"
        if poll_tool not in mcp_gateway.get_available_tools():
            return
        approval_poll_tool = "mcp_telegram_business_poll_control_approvals"
        remote_desktop = Path.home() / "Desktop"
        if not remote_desktop.is_dir():
            remote_desktop = Path.home()
        while not runtime.shutdown_event.is_set():
            try:
                if approval_poll_tool in mcp_gateway.get_available_tools():
                    approval_result = await mcp_gateway.call_tool(
                        approval_poll_tool,
                        {"limit": 10},
                    )
                    approval_payload = approval_result.data.get("structured_content")
                    approvals = (
                        approval_payload.get("approvals")
                        if isinstance(approval_payload, dict)
                        else None
                    )
                    if approval_result.success and isinstance(approvals, list):
                        for approval in approvals:
                            if not isinstance(approval, dict):
                                continue
                            operation_id = str(approval.get("operation_id") or "")
                            if approval.get("decision") == "approve":
                                runner.permission_manager.confirm(operation_id)
                            else:
                                runner.permission_manager.deny(operation_id)
                result = await mcp_gateway.call_tool(poll_tool, {"limit": 10})
                payload = result.data.get("structured_content")
                commands = payload.get("commands") if isinstance(payload, dict) else None
                if result.success and isinstance(commands, list):
                    for command in commands:
                        if not isinstance(command, dict):
                            continue
                        text = str(command.get("text") or "").strip()
                        chat_id = command.get("chat_id")
                        user_id = command.get("user_id")
                        if not text or chat_id is None or user_id is None:
                            continue
                        command_name = text.casefold().split(maxsplit=1)[0]
                        if command_name == "/stop":
                            cancelled = await request_service.cancel_current()
                            await send_telegram_remote_reply(
                                int(chat_id),
                                "Текущая задача остановлена." if cancelled else "Сейчас нет активной задачи.",
                            )
                            continue
                        if command_name == "/status":
                            current = request_service.current_request
                            status_text = (
                                f"Выполняю: {current.text[:500]}"
                                if current is not None
                                else "Rynne свободна."
                            )
                            status_text += f"\nВ очереди: {input_coordinator.queued_requests}."
                            await send_telegram_remote_reply(int(chat_id), status_text)
                            continue
                        if command_name == "/mode":
                            labels = {
                                "full_access": "Полный доступ",
                                "risky_only": "Спрашивать только для рискованных действий",
                                "always_ask": "Спрашивать всегда",
                            }
                            mode = runner.permission_manager.mode.value
                            await send_telegram_remote_reply(
                                int(chat_id),
                                "Режим доступа: " + labels.get(mode, mode) + ".",
                            )
                            continue
                        request = await input_coordinator.submit_text(
                            text,
                            source=RequestSource.API,
                            session_id=f"telegram_remote:{chat_id}",
                            metadata={
                                "telegram_remote": True,
                                "telegram_remote_chat_id": int(chat_id),
                                "telegram_remote_user_id": int(user_id),
                                "telegram_remote_username": str(command.get("username") or ""),
                                "workspace_path": str(remote_desktop),
                                "workspace_name": "Desktop",
                                "workspace_locked": True,
                                "workspace_is_default": True,
                            },
                        )
                        if request is not None:
                            await send_telegram_remote_reply(
                                int(chat_id),
                                "Принято. Передаю задачу Rynne Core.",
                            )
                elif not result.success:
                    logger.warning("Telegram Remote polling failed: %s", result.message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram Remote worker failed.")
            try:
                await asyncio.wait_for(runtime.shutdown_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    telegram_remote_task = asyncio.create_task(
        telegram_remote_worker(),
        name="nova-telegram-remote",
    )
    wake_detector = WakeWordDetector(
        activity_callback=publish_voice_activity("wake_word"),
    )

    wake_runtime = WakeWordRuntime(
        detector=wake_detector,
        listener=listener,
        coordinator=input_coordinator,
        preferences=preferences,
        runtime=runtime,
        event_handler=(
            desktop_service.publish
            if NOVA_DESKTOP_UI
            else None
        ),
    )
    mode_manager.attach_wake_runtime(
        wake_runtime
    )

    wake_runtime_task = asyncio.create_task(
        wake_runtime.run(
            runtime.shutdown_event
        ),
        name="nova-wake-word-runtime",
    )

    # =========================================================
    # DESKTOP BRIDGE
    #
    # Создаётся только после InputCoordinator, PreferencesManager
    # и RequestService, потому что использует их методы.
    # =========================================================

    desktop_bridge = CoreDesktopBridge(
        desktop=desktop_service,
        process_manager=process_manager,
        memory_store=memory_store,
        permission_manager=(
            runner.permission_manager
        ),
        llm=llm,
        runtime=runtime,
        input_coordinator=(
            input_coordinator
        ),
        preferences=preferences,
        cancel_current_request=(
            request_service.cancel_current
        ),
        mode_manager=mode_manager,
        plan_service=plan_service,
        background_plan_manager=(
            background_plan_manager
        ),
        mcp_gateway=mcp_gateway,
        proactive_context_store=(
            proactive_vision_observer.context_store
        ),
        request_proactive_check=(
            proactive_vision_check_requested.set
        ),
        proactive_engine=proactive_engine,
        proactive_confirmation=proactive_confirmation,

    )

    desktop_bridge_task = asyncio.create_task(
        desktop_bridge.run(
            runtime.shutdown_event
        ),
        name="nova-desktop-bridge",
    )
    logger.info(
        (
            "Runtime services started: "
            "request_service=%s desktop_bridge=%s "
            "wake_runtime=%s"
        ),
        not request_service_task.done(),
        not desktop_bridge_task.done(),
        not wake_runtime_task.done(),
    )
    loop = asyncio.get_running_loop()
    hotkey_handles: list[Any] = []
    hotkey_toggle_lock = threading.Lock()
    last_hotkey_toggle = 0.0

    def schedule_toggle() -> None:
        async def toggle() -> None:
            active, mode_snapshot = (
                await mode_manager
                .toggle_manual_voice()
            )

            logger.info(
                (
                    "Ctrl+Shift+Space: active=%s "
                    "input_mode=%s"
                ),
                active,
                mode_snapshot.input_mode.value,
            )

            if active:
                await asyncio.to_thread(
                    winsound.Beep,
                    1200,
                    150,
                )
            else:
                await asyncio.to_thread(
                    winsound.Beep,
                    600,
                    150,
                )

        asyncio.create_task(toggle())

    def toggle_callback() -> None:
        nonlocal last_hotkey_toggle
        # Suppress keyboard auto-repeat: queued double toggles used to switch
        # manual STT on and immediately hand the microphone back to Vosk.
        now = time.monotonic()
        with hotkey_toggle_lock:
            if now - last_hotkey_toggle < 0.65:
                return
            last_hotkey_toggle = now
        loop.call_soon_threadsafe(schedule_toggle)

    def interrupt_callback() -> None:
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(
                speech.interrupt()
            )
        )

    hotkey_handles.append(
        keyboard.add_hotkey(
            "ctrl+shift+space",
            toggle_callback,
        )
    )
    logger.info(
        "Горячая клавиша Ctrl+Shift+Space зарегистрирована."
    )
    hotkey_handles.append(
        keyboard.add_hotkey(
            "esc",
            interrupt_callback,
        )
    )
    hotkey_handles.append(
        keyboard.add_hotkey(
            "ctrl+shift+q",
            interrupt_callback,
        )
    )
    logger.info(
        "Все глобальные горячие клавиши зарегистрированы."
    )
    await speech.start()
    await runtime.set_state(AssistantState.SLEEPING)

    reminder_task = asyncio.create_task(
        reminder_checker_worker(
            scheduler,
            lambda text: speech.say(
                text,
                priority=2,
                wait=True,
            ),
            runtime.shutdown_event,
        ),
        name="nova-reminder-worker",
    )

    voice_task = asyncio.create_task(
        run_voice_loop(
            runtime,
            speech,
            input_coordinator,
            listener,
            windows_context,
            preferences,
            desktop_service.publish,
        ),
        name="nova-voice-loop",
    )
    workspace_context_task = asyncio.create_task(
        workspace_context.monitor(
            runtime.shutdown_event
        ),
        name="nova-workspace-context",
    )
    proactive_vision_task = asyncio.create_task(
        proactive_vision_worker(),
        name="nova-proactive-vision",
    )


    try:
        if NOVA_DESKTOP_TRANSPORT != "stdio":
            await speech.say(
                (
                    "Скажите Рин или нажмите "
                    "контрол шифт спейс."
                ),
                priority=0,
            )

        await runtime.shutdown_event.wait()

    finally:
        await runtime.request_shutdown()
        await input_coordinator.close()
        wake_runtime.close()
        reminder_task.cancel()
        voice_task.cancel()
        request_service_task.cancel()
        telegram_remote_task.cancel()
        desktop_bridge_task.cancel()
        wake_runtime_task.cancel()
        proactive_task.cancel()
        workspace_context_task.cancel()
        proactive_vision_task.cancel()
        await asyncio.gather(
            reminder_task,
            voice_task,
            request_service_task,
            telegram_remote_task,
            wake_runtime_task,
            desktop_bridge_task,
            proactive_task,
            workspace_context_task,
            proactive_vision_task,
            return_exceptions=True,
        )


        keyboard.unhook_all_hotkeys()
        await speech.close()
        await background_plan_manager.close()
        await browser_manager.close()
        if mcp_gateway is not None:
            await mcp_gateway.close()
        await llm.close()

        process_manager.cleanup_all()
        database.close()

        desktop_service.stop()
        if legacy_overlay_enabled:
            stop_overlay()
        instance_lock.close()




async def test_reasoning_loop(request: str) -> None:
    """Тестирует Reasoning Loop с заданным запросом."""
    from modules.agent.reasoning import ReasoningLoop, ReasoningState
    
    # Создаём компоненты
    llm = NovaLLM()
    debug_subagent_pool = SubagentPool(llm)
    debug_handlers = build_handlers(
        LocalMemory(),
        TaskScheduler(),
        await asyncio.to_thread(WindowsAppIndexer),
        process_manager,
        memory_store,
        artifact_store,
        BrowserManager(headless=True),
    )
    debug_handlers["delegate_subagents"] = (
        debug_subagent_pool.delegate_subagents
    )
    registry = ToolRegistry.from_legacy(
        [ts for ts in ALL_TOOLS if ts["function"]["name"] not in {
            "execute_plan", "get_plan_status", "cancel_plan",
            "start_background_plan", "get_background_plan_status",
            "list_background_plans", "retry_background_plan",
            "cancel_background_plan",
        }],
        debug_handlers,
    )
    runner = ToolRunner(registry)
    
    # Создаём reasoning loop
    loop = ReasoningLoop(
        llm=llm,
        registry=registry,
        runner=runner,
        intent_router=None,
    )
    
    state = ReasoningState(
        turn_id="test_turn",
        session_id="test_session",
        original_request=request,
        max_iterations=3,
    )
    
    print("=" * 60)
    print("REASONING LOOP TEST")
    print("=" * 60)
    print(f"Запрос: {request}")
    
    response = await loop.run(state)
    
    print(f"\nИтераций: {state.current_iteration}")
    print(f"Цель достигнута: {state.goal_achieved}")
    print(f"\nОтвет: {response.display_text}")


def run_reasoning_test() -> None:
    """Запускает тест Reasoning Loop из командной строки."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Rynne Reasoning Loop Test")
    parser.add_argument(
        "request",
        nargs="*",
        help="Запрос для тестирования",
    )
    parser.add_argument(
        "--reasoning",
        action="store_true",
        help="Запустить в режиме reasoning loop",
    )
    
    args = parser.parse_args()
    
    if args.reasoning and args.request:
        request_text = " ".join(args.request)
        asyncio.run(test_reasoning_loop(request_text))
    else:
        # Обычный запуск
        try:
            asyncio.run(async_main())
        except RuntimeError as exc:
            print(f"\n[Критическая ошибка]: {exc}")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nRynne остановлена пользователем.")


if __name__ == "__main__":
    run_reasoning_test()
