"""Side-effect-free acceptance harness for Nova's orchestration stack.

Run from the repository root:
    python -m tests.orchestrator_acceptance

The harness uses the production tool schemas, selector, registry, policy
evaluation, runner, validation and live events. Tool handlers are replaced
with deterministic recorders, so no application, file, process or network
is touched.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from modules.domain.results import ToolResult
from modules.tools.base import ToolContext
from modules.tools.permissions import PermissionManager
from modules.tools.policy import (
    PolicyContext,
    PolicyDecision,
    evaluate_policy,
)
from modules.tools.registry import ALL_TOOLS
from modules.tools.runtime import ToolRegistry, ToolRunner
from modules.tools.selection import select_tools_for_request


@dataclass(frozen=True, slots=True)
class ReplayCall:
    tool_name: str
    arguments: dict[str, Any]
    expected_policy: PolicyDecision


@dataclass(frozen=True, slots=True)
class AcceptanceScenario:
    name: str
    request: str
    expected_tools: frozenset[str]
    calls: tuple[ReplayCall, ...]
    has_image: bool = False


@dataclass(slots=True)
class ScenarioResult:
    name: str
    passed: bool
    selected_tools: list[str] = field(default_factory=list)
    executed_tools: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ReplayPermissionManager(PermissionManager):
    """Evaluates real policy, then approves safe fake execution."""

    def __init__(self) -> None:
        super().__init__()
        self.decisions: list[tuple[str, PolicyDecision]] = []

    def check(
        self,
        policy_context: PolicyContext,
    ) -> tuple[bool, str | None]:
        decision = evaluate_policy(policy_context)
        self.decisions.append((policy_context.tool_name, decision))
        if decision == PolicyDecision.DENY:
            return False, (
                f"Replay correctly denied '{policy_context.tool_name}'."
            )
        return True, None


class OrchestratorAcceptanceHarness:
    def __init__(self) -> None:
        self.invocations: list[tuple[str, dict[str, Any]]] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.permissions = ReplayPermissionManager()

        schema_names = {
            schema["function"]["name"]
            for schema in ALL_TOOLS
        }
        handlers = {
            name: self._make_handler(name)
            for name in schema_names
        }
        self.registry = ToolRegistry.from_legacy(
            ALL_TOOLS,
            handlers,
        )
        self.runner = ToolRunner(
            self.registry,
            permission_manager=self.permissions,
            event_sink=lambda event_type, payload: self.events.append(
                (event_type, payload)
            ),
        )

    def _make_handler(self, tool_name: str):
        def handler(**arguments: Any) -> ToolResult:
            self.invocations.append((tool_name, dict(arguments)))
            return ToolResult.ok(
                f"Replay completed: {tool_name}",
                data={"replay": True},
            )

        return handler

    @staticmethod
    def _tool_call(call_index: int, replay: ReplayCall) -> dict[str, Any]:
        return {
            "id": f"acceptance_call_{call_index}",
            "type": "function",
            "function": {
                "name": replay.tool_name,
                "arguments": json.dumps(
                    replay.arguments,
                    ensure_ascii=False,
                ),
            },
        }

    async def run(
        self,
        scenario: AcceptanceScenario,
    ) -> ScenarioResult:
        result = ScenarioResult(name=scenario.name, passed=True)
        descriptions = {
            definition.name: definition.description
            for definition in self.registry.definitions()
        }
        selected = select_tools_for_request(
            scenario.request,
            self.registry.names,
            has_image=scenario.has_image,
            tool_descriptions=descriptions,
        )
        result.selected_tools = sorted(selected)

        missing = scenario.expected_tools - selected
        if missing:
            result.errors.append(
                "Selector missed: " + ", ".join(sorted(missing))
            )

        for call_index, replay in enumerate(scenario.calls):
            if replay.tool_name not in selected:
                result.errors.append(
                    f"Replay tool was not selected: {replay.tool_name}"
                )
                continue

            event_start = len(self.events)
            decision_start = len(self.permissions.decisions)
            execution = await self.runner.execute(
                self._tool_call(call_index, replay),
                context=ToolContext.create(
                    session_id="acceptance-session",
                    turn_id=f"acceptance-{scenario.name}",
                    source="acceptance-replay",
                    metadata={"side_effect_free": True},
                ),
            )
            if not execution.success:
                result.errors.append(
                    f"{replay.tool_name} failed: {execution.code}"
                )
                continue

            result.executed_tools.append(replay.tool_name)
            decisions = self.permissions.decisions[decision_start:]
            actual_decision = (
                decisions[-1][1] if decisions else None
            )
            if actual_decision != replay.expected_policy:
                result.errors.append(
                    f"{replay.tool_name} policy: "
                    f"expected {replay.expected_policy.value}, "
                    f"got {getattr(actual_decision, 'value', None)}"
                )

            events = self.events[event_start:]
            event_names = [name for name, _payload in events]
            if event_names != ["tool_started", "tool_completed"]:
                result.errors.append(
                    f"{replay.tool_name} events: {event_names}"
                )
            elif (
                events[0][1]["operation_id"]
                != events[1][1]["operation_id"]
            ):
                result.errors.append(
                    f"{replay.tool_name} operation_id changed"
                )

        result.passed = not result.errors
        return result


GOLDEN_SCENARIOS = (
    AcceptanceScenario(
        name="batch-app-launch",
        request="Запусти пять приложений на моём компьютере",
        expected_tools=frozenset({"open_application_batch"}),
        calls=(
            ReplayCall(
                "open_application_batch",
                {"count": 5},
                PolicyDecision.ALLOW,
            ),
        ),
    ),
    AcceptanceScenario(
        name="background-resume",
        request="Продолжи failed фоновый план с последнего checkpoint",
        expected_tools=frozenset({"retry_background_plan"}),
        calls=(
            ReplayCall(
                "retry_background_plan",
                {"background_id": "background_demo"},
                PolicyDecision.REQUIRE_CONFIRMATION,
            ),
        ),
    ),
    AcceptanceScenario(
        name="website-watch",
        request=(
            "Следи за сайтом https://example.com/releases "
            "и сообщи, когда он изменится"
        ),
        expected_tools=frozenset({"watch_website"}),
        calls=(
            ReplayCall(
                "watch_website",
                {
                    "url": "https://example.com/releases",
                    "label": "Releases",
                },
                PolicyDecision.ALLOW_WITH_WARNING,
            ),
        ),
    ),
    AcceptanceScenario(
        name="terminal-tests",
        request="Запусти pytest в терминале",
        expected_tools=frozenset({"run_terminal_command"}),
        calls=(
            ReplayCall(
                "run_terminal_command",
                {"command": "python -m pytest -q"},
                PolicyDecision.REQUIRE_CONFIRMATION,
            ),
        ),
    ),
    AcceptanceScenario(
        name="backup-watch",
        request=(
            "Следи за резервной копией проекта и предупреди, "
            "если она старше 24 часов"
        ),
        expected_tools=frozenset({"watch_backup"}),
        calls=(
            ReplayCall(
                "watch_backup",
                {
                    "path": "D:\\Backups\\project",
                    "max_age_hours": 24,
                    "label": "Project backup",
                },
                PolicyDecision.ALLOW_WITH_WARNING,
            ),
        ),
    ),
    AcceptanceScenario(
        name="package-update-watch",
        request="Следи за обновлением Python-пакета requests",
        expected_tools=frozenset({"watch_package_update"}),
        calls=(
            ReplayCall(
                "watch_package_update",
                {"package_name": "requests"},
                PolicyDecision.ALLOW_WITH_WARNING,
            ),
        ),
    ),
)


async def run_golden_suite() -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for scenario in GOLDEN_SCENARIOS:
        harness = OrchestratorAcceptanceHarness()
        results.append(await harness.run(scenario))
    return results


async def _main() -> int:
    results = await run_golden_suite()
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(
            f"[{status}] {result.name}: "
            f"selected={','.join(result.selected_tools)} "
            f"executed={','.join(result.executed_tools)}"
        )
        for error in result.errors:
            print(f"  - {error}")

    passed = sum(result.passed for result in results)
    print(f"\nOrchestrator acceptance: {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
