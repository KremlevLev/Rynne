# tests/test_smoke.py
"""
Универсальные тесты для Nova.
Проверяют:
- импорты всех модулей;
- конфигурацию;
- базовую работу агента;
- ответ модели.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


def test_core_config_imports() -> None:
    """Проверяет, что core.config импортируется без ошибок."""
    import core.config

    assert hasattr(core.config, "GROQ_API_KEYS")
    assert hasattr(core.config, "OPENROUTER_API_KEYS")
    assert hasattr(core.config, "SYSTEM_PROMPT")


def test_domain_modules_import() -> None:
    """Проверяет импорт всех модулей domain."""
    from modules.domain.results import (
        AssistantResponse,
        ToolResult,
        VerificationResult,
    )

    assert ToolResult is not None
    assert AssistantResponse is not None
    assert VerificationResult is not None


def test_tools_base_import() -> None:
    """Проверяет импорт базовых классов инструментов."""
    from modules.tools.base import (
        RiskLevel,
        ToolCategory,
        ToolContext,
        ToolDefinition,
    )

    assert RiskLevel is not None
    assert ToolCategory is not None
    assert ToolContext is not None
    assert ToolDefinition is not None


def test_tools_runtime_import() -> None:
    """Проверяет импорт runtime инструментов."""
    from modules.tools.runtime import (
        ToolRegistry,
        ToolRunner,
    )

    assert ToolRegistry is not None
    assert ToolRunner is not None


def test_policy_import() -> None:
    """Проверяет импорт Policy Engine."""
    from modules.tools.policy import (
        PolicyDecision,
        PolicyContext,
        evaluate_policy,
    )

    assert PolicyDecision is not None
    assert PolicyContext is not None
    assert evaluate_policy is not None


def test_permissions_import() -> None:
    """Проверяет импорт Permission Manager."""
    from modules.tools.permissions import (
        PermissionManager,
    )

    assert PermissionManager is not None


def test_budgets_import() -> None:
    """Проверяет импорт Budget Manager."""
    from modules.tools.budgets import (
        AgentBudget,
        BudgetManager,
        BudgetState,
    )

    assert AgentBudget is not None
    assert BudgetManager is not None
    assert BudgetState is not None


def test_reporting_import() -> None:
    """Проверяет импорт reporting."""
    from modules.application.reporting import (
        build_assistant_response_from_tools,
        build_tool_execution_summary,
    )

    assert build_assistant_response_from_tools is not None
    assert build_tool_execution_summary is not None


def test_speech_service_import() -> None:
    """Проверяет импорт SpeechService."""
    from modules.application.speech import (
        SpeechService,
        prepare_text_for_speech,
        split_speech_chunks,
    )

    assert SpeechService is not None
    assert prepare_text_for_speech is not None
    assert split_speech_chunks is not None


def test_stt_import() -> None:
    """Проверяет импорт STT."""
    from modules.audio.stt import VoiceListener

    assert VoiceListener is not None


def test_tts_import() -> None:
    """Проверяет импорт TTS."""
    from modules.audio.tts import (
        speak,
        stop_speaking,
    )

    assert speak is not None
    assert stop_speaking is not None


def test_memory_import() -> None:
    """Проверяет импорт памяти."""
    from modules.brain.memory import LocalMemory

    assert LocalMemory is not None


def test_bypass_import() -> None:
    """Проверяет импорт bypass."""
    from modules.brain.bypass import (
        check_fast_commands,
        check_instant_app_launch,
        determine_model_by_complexity,
    )

    assert check_fast_commands is not None
    assert check_instant_app_launch is not None
    assert determine_model_by_complexity is not None


def test_model_gateway_import() -> None:
    """Проверяет импорт ModelGateway."""
    from modules.brain.model_gateway import (
        ModelGateway,
        ModelResponse,
    )

    assert ModelGateway is not None
    assert ModelResponse is not None


def test_model_router_import() -> None:
    """Проверяет импорт роутера моделей."""
    from modules.brain.model_router import (
        ModelCandidate,
        TaskComplexity,
        build_model_route,
        classify_complexity,
    )

    assert ModelCandidate is not None
    assert TaskComplexity is not None
    assert build_model_route is not None
    assert classify_complexity is not None


def test_tool_calls_import() -> None:
    """Проверяет импорт парсера tool calls."""
    from modules.brain.tool_calls import (
        deduplicate_tool_calls,
        extract_xml_tool_calls,
    )

    assert deduplicate_tool_calls is not None
    assert extract_xml_tool_calls is not None


def test_app_indexer_import() -> None:
    """Проверяет импорт индексатора приложений."""
    from modules.tools.app_indexer import (
        WindowsAppIndexer,
    )

    assert WindowsAppIndexer is not None


def test_selection_import() -> None:
    """Проверяет импорт selection."""
    from modules.tools.selection import (
        select_tool_names,
    )

    assert select_tool_names is not None


def test_skills_import() -> None:
    """Проверяет импорт навыков."""
    from modules.tools.skills import (
        WindowsSkills,
    )

    assert WindowsSkills is not None


def test_tasks_import() -> None:
    """Проверяет импорт планировщика задач."""
    from modules.tools.tasks import (
        TaskScheduler,
    )

    assert TaskScheduler is not None


def test_process_manager_import() -> None:
    """Проверяет импорт Process Manager."""
    from modules.windows.process_manager import (
        ProcessManager,
    )

    assert ProcessManager is not None


def test_filesystem_import() -> None:
    """Проверяет импорт файловой системы."""
    from modules.windows.filesystem import (
        read_text_file,
        write_text_file,
        apply_text_patch,
        search_files,
        rollback_file,
    )

    assert read_text_file is not None
    assert write_text_file is not None
    assert apply_text_patch is not None
    assert search_files is not None
    assert rollback_file is not None


def test_git_tools_import() -> None:
    """Проверяет импорт Git-инструментов."""
    from modules.windows.git_tools import (
        git_status,
        git_diff,
        git_log,
        git_commit,
        git_branch,
    )

    assert git_status is not None
    assert git_diff is not None
    assert git_log is not None
    assert git_commit is not None
    assert git_branch is not None


def test_project_inspector_import() -> None:
    """Проверяет импорт инспектора проектов."""
    from modules.windows.project_inspector import (
        inspect_project,
    )

    assert inspect_project is not None


def test_database_import() -> None:
    """Проверяет импорт SQLite."""
    from modules.storage.database import Database

    assert Database is not None


def test_conversations_import() -> None:
    """Проверяет импорт ConversationStore."""
    from modules.storage.conversations import (
        ConversationStore,
    )

    assert ConversationStore is not None


def test_memories_import() -> None:
    """Проверяет импорт MemoryStore."""
    from modules.storage.memories import MemoryStore

    assert MemoryStore is not None


def test_overlay_import() -> None:
    """Проверяет импорт overlay."""
    from modules.ui.overlay import (
        should_start_legacy_overlay,
        start_overlay,
        update_status,
    )

    assert start_overlay is not None
    assert update_status is not None
    assert should_start_legacy_overlay("pyside") is True
    assert should_start_legacy_overlay("stdio") is False


def test_desktop_core_uses_separate_instance_lock() -> None:
    from main import instance_lock_port

    assert instance_lock_port("pyside") == 29485
    assert instance_lock_port("stdio") == 0


def test_windows_context_import() -> None:
    """Проверяет импорт WindowsContext."""
    from modules.domain.windows_context import (
        WindowsContext,
    )

    assert WindowsContext is not None


def test_state_import() -> None:
    """Проверяет импорт RuntimeState."""
    from modules.domain.state import (
        AssistantState,
        RuntimeState,
    )

    assert AssistantState is not None
    assert RuntimeState is not None


def test_all_modules_compile() -> None:
    """Проверяет, что все модули компилируются без ошибок."""
    modules = [
        "core.config",
        "modules.domain.results",
        "modules.domain.state",
        "modules.domain.windows_context",
        "modules.tools.base",
        "modules.tools.runtime",
        "modules.tools.policy",
        "modules.tools.permissions",
        "modules.tools.budgets",
        "modules.tools.selection",
        "modules.tools.skills",
        "modules.tools.tasks",
        "modules.tools.app_indexer",
        "modules.application.speech",
        "modules.application.reporting",
        "modules.brain.bypass",
        "modules.brain.memory",
        "modules.brain.tool_calls",
        "modules.brain.model_router",
        "modules.brain.model_gateway",
        "modules.audio.stt",
        "modules.audio.tts",
        "modules.windows.process_manager",
        "modules.windows.filesystem",
        "modules.windows.git_tools",
        "modules.windows.project_inspector",
        "modules.storage.database",
        "modules.storage.conversations",
        "modules.storage.memories",
        "modules.ui.overlay",
    ]

    for module_name in modules:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            raise AssertionError(
                f"Модуль {module_name} не импортируется: {exc}"
            )

def test_input_hub_import() -> None:
    from modules.input_hub import (
        InputCoordinator,
        UserRequest,
    )

    assert InputCoordinator is not None
    assert UserRequest is not None


def test_routing_import() -> None:
    from modules.routing import (
        DeterministicIntentRouter,
        ExecutionDecision,
        ExecutionStrategy,
    )

    assert DeterministicIntentRouter is not None
    assert ExecutionDecision is not None
    assert ExecutionStrategy is not None
def test_request_runtime_import() -> None:
    from modules.application.preferences import (
        PreferencesManager,
    )
    from modules.application.request_dispatcher import (
        RequestDispatcher,
    )
    from modules.application.request_service import (
        RequestService,
    )
    from modules.routing.direct_executor import (
        DirectRequestExecutor,
    )

    assert PreferencesManager is not None
    assert RequestDispatcher is not None
    assert RequestService is not None
    assert DirectRequestExecutor is not None
def test_wake_word_import() -> None:
    from modules.input_hub.wake_runtime import (
        WakeWordRuntime,
    )
    from modules.input_hub.wake_word import (
        WakeWordDetector,
        strip_wake_prefix,
    )

    assert WakeWordRuntime is not None
    assert WakeWordDetector is not None
    assert strip_wake_prefix is not None


def test_mcp_gateway_import() -> None:
    """Проверяет импорт MCP Gateway."""
    from modules.agent.mcp_gateway import (
        MCPGateway,
        MCPServerConfig,
    )
    from modules.agent.mcp_integration import (
        bootstrap_mcp_from_defaults,
    )

    assert MCPGateway is not None
    assert MCPServerConfig is not None
    assert bootstrap_mcp_from_defaults is not None


def test_recovery_mcp_import() -> None:
    """Проверяет импорт MCP recovery компонентов."""
    from modules.agent.recovery import (
        SelfDiagnostics,
        GracefulDegradation,
        set_mcp_recovery_tools,
        get_mcp_recovery_tools,
    )

    assert SelfDiagnostics is not None
    assert GracefulDegradation is not None
    assert set_mcp_recovery_tools is not None
    assert get_mcp_recovery_tools is not None
