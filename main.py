# main.py
from __future__ import annotations
from pathlib import Path

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
from modules.storage.artifacts import (
    ArtifactStore,
)
from modules.storage.database import Database
from modules.storage.conversations import (
    ConversationStore,
)
from modules.storage.memories import MemoryStore
from modules.windows.git_tools import (
    git_status,
    git_diff,
    git_log,
    git_commit,
    git_branch,
)
from modules.agent.plan_service import (
    PlanService,
)
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
from modules.brain.bypass import (
    check_fast_commands,
    check_instant_app_close,
    check_instant_app_launch,
)

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
logger = logging.getLogger("Nova")


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
            "Nova уже запущена в другом процессе."
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
    app_launcher: WindowsAppIndexer,
    windows_context: WindowsContext,
    preferences: PreferencesManager,
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

        user_request = await asyncio.to_thread(
            listener.listen,
            lambda: (
                not runtime.is_active
                or runtime.is_shutting_down
            ),
        )

        if runtime.is_shutting_down:
            break

        if not runtime.is_active or not user_request:
            continue

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

        is_launch, launch_response = await asyncio.to_thread(
            check_instant_app_launch,
            user_request,
            app_launcher,
        )
        if is_launch:
            # Извлекаем имя приложения из исходной команды.
            lowered_request = user_request.lower().strip()

            for launch_verb in (
                "открой",
                "включи",
                "запусти",
                "запуск",
            ):
                if lowered_request.startswith(
                    launch_verb + " "
                ):
                    application_name = user_request[
                        len(launch_verb):
                    ].strip(" .,!?:;")

                    windows_context.set_application(
                        application_name
                    )
                    break
                
            await speech.say(launch_response)
            continue
        

        is_close, close_response = await asyncio.to_thread(
            check_instant_app_close,
            user_request,
        )
        if is_close:
            await speech.say(close_response)
            continue

        is_fast, fast_response = await asyncio.to_thread(
            check_fast_commands,
            user_request,
        )
        if is_fast:
            await speech.say(fast_response)
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
    speech = SpeechService(runtime)
    browser_manager = BrowserManager(
    headless=False
)

    memory = LocalMemory()
    scheduler = TaskScheduler()
    app_launcher = await asyncio.to_thread(
        WindowsAppIndexer
    )
    listener = VoiceListener()
    llm = NovaLLM()

    handlers = build_handlers(
        memory,
        scheduler,
        app_launcher,
        process_manager,
        memory_store,
        artifact_store,
        browser_manager,
    )

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
        if (
            NOVA_PROACTIVE_ENABLED
            and "workflow_suggested"
            not in NOVA_PROACTIVE_DISABLED_KINDS
            and event_type == "tool_completed"
        ):
            proactive_engine.record_tool_completion(payload)

    runner.set_event_sink(handle_tool_event)

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
                    desktop_service.publish(
                        "proactive_suggestion",
                        suggestion.to_dict(),
                    )
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

    agent = AgentService(
        llm,
        registry,
        runner,
    )

    # =========================================================
    # NOVA 2.0 INPUT HUB И НАСТРОЙКИ
    # =========================================================

    preferences = PreferencesManager()
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

    async def proactive_vision_worker() -> None:
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
                    insight = (
                        await proactive_vision_observer
                        .inspect()
                    )
                    if insight is not None:
                        for suggestion in (
                            proactive_engine
                            .observe_visual_insight(
                                insight,
                                ignore_quiet_hours=True,
                            )
                        ):
                            desktop_service.publish(
                                "proactive_suggestion",
                                suggestion.to_dict(),
                            )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Сбой opt-in режима «Nova рядом»."
                    )
                delay = max(
                    30.0,
                    NOVA_PROACTIVE_VISION_CHECK_SECONDS,
                )

            try:
                await asyncio.wait_for(
                    runtime.shutdown_event.wait(),
                    timeout=delay,
                )
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

    async def handle_request_response(
        request: UserRequest,
        response: AssistantResponse,
    ) -> None:
        print(
            f"\n[Nova]: "
            f"{response.display_text}\n"
        )

        # Передаём сообщение пользователя в Desktop UI.
        desktop_service.publish(
            "user_message",
            {
                "request_id": (
                    request.request_id
                ),
                "text": request.text,
            },
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

        preferences_snapshot = (
            preferences.snapshot()
        )

        # В режиме с отключённым TTS экранный ответ всё равно
        # публикуется, но голос не воспроизводится.
        if (
            preferences_snapshot.tts_enabled
            and response.speech_text.strip()
        ):
            await speech.say(
                response.speech_text,
                priority=5,
            )

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
    )

    request_service_task = asyncio.create_task(
        request_service.run(
            runtime.shutdown_event
        ),
        name="nova-request-service",
    )
    wake_detector = WakeWordDetector()

    wake_runtime = WakeWordRuntime(
        detector=wake_detector,
        listener=listener,
        coordinator=input_coordinator,
        preferences=preferences,
        runtime=runtime,
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
            app_launcher,
            windows_context,
            preferences,
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
                    "Скажите Нова или нажмите "
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
        desktop_bridge_task.cancel()
        wake_runtime_task.cancel()
        proactive_task.cancel()
        workspace_context_task.cancel()
        proactive_vision_task.cancel()
        await asyncio.gather(
            reminder_task,
            voice_task,
            request_service_task,
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
    registry = ToolRegistry.from_legacy(
        [ts for ts in ALL_TOOLS if ts["function"]["name"] not in {
            "execute_plan", "get_plan_status", "cancel_plan",
            "start_background_plan", "get_background_plan_status",
            "list_background_plans", "retry_background_plan",
            "cancel_background_plan",
        }],
        build_handlers(
            LocalMemory(),
            TaskScheduler(),
            await asyncio.to_thread(WindowsAppIndexer),
            process_manager,
            memory_store,
            artifact_store,
            BrowserManager(headless=True),
        ),
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
    
    parser = argparse.ArgumentParser(description="Nova Reasoning Loop Test")
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
            print("\nNova остановлена пользователем.")


if __name__ == "__main__":
    run_reasoning_test()
