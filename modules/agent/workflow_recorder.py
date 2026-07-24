# modules/agent/workflow_recorder.py
"""Workflow Recorder - запись и воспроизведение последовательностей действий.

Позволяет:
- Записывать выполненные инструменты как workflow
- Сохранять workflow в файл
- Воспроизводить workflow позже
- Редактировать workflow перед воспроизведением
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.domain.results import ToolResult


logger = logging.getLogger("WorkflowRecorder")


WORKFLOWS_DIR = Path("data/workflows")


@dataclass(slots=True)
class WorkflowStep:
    """Отдельный шаг workflow."""
    tool_name: str
    arguments: dict[str, Any]
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "description": self.description,
        }


@dataclass
class Workflow:
    """Записанный workflow."""
    id: str
    name: str
    steps: list[WorkflowStep] = field(default_factory=list)
    created_at: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "steps": [step.to_dict() for step in self.steps],
            "created_at": self.created_at,
            "tags": self.tags,
        }


class WorkflowRecorder:
    """
    Записывает и воспроизводит workflows.
    
    Workflows - это сохраняемые последовательности действий,
    которые можно воспроизводить позже.
    """
    
    def __init__(self) -> None:
        self.workflows_dir = WORKFLOWS_DIR
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        self._active_workflow: Workflow | None = None
        self._recorded_steps: list[dict[str, Any]] = []

    def start_recording(self, name: str, tags: list[str] | None = None) -> str:
        """
        Начинает запись workflow.
        
        Args:
            name: Имя workflow
            tags: Теги для категоризации
            
        Returns:
            ID workflow
        """
        self._active_workflow = Workflow(
            id=f"wf_{uuid.uuid4().hex[:8]}",
            name=name,
            tags=tags or [],
        )
        self._recorded_steps = []
        
        logger.info("Workflow recording started: %s", name)
        return self._active_workflow.id

    def record_step(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        description: str = "",
    ) -> None:
        """
        Записывает шаг в активный workflow.
        
        Вызывается после успешного выполнения инструмента.
        """
        if self._active_workflow is None:
            return
            
        step = WorkflowStep(
            tool_name=tool_name,
            arguments=arguments,
            description=description,
        )
        self._active_workflow.steps.append(step)
        self._recorded_steps.append({
            "tool_name": tool_name,
            "arguments": arguments,
        })
        
        logger.debug("Step recorded: %s", tool_name)

    def stop_recording(self, save: bool = True) -> ToolResult:
        """
        Останавливает запись workflow.
        
        Args:
            save: Сохранять ли workflow в файл
            
        Returns:
            ToolResult с информацией о workflow
        """
        if self._active_workflow is None:
            return ToolResult.failure(
                "NO_ACTIVE_WORKFLOW",
                "Запись workflow не была начата.",
            )
        
        workflow = self._active_workflow
        
        if save and workflow.steps:
            self._save_workflow(workflow)
        
        self._active_workflow = None
        steps_count = len(workflow.steps)
        
        logger.info(
            "Workflow recording stopped: %s steps",
            steps_count,
        )
        
        return ToolResult.ok(
            f"Workflow '{workflow.name}' записан ({steps_count} шагов).",
            data={
                "workflow_id": workflow.id,
                "name": workflow.name,
                "steps_count": steps_count,
            },
        )

    def _save_workflow(self, workflow: Workflow) -> None:
        """Сохраняет workflow в JSON файл."""
        workflow_path = self.workflows_dir / f"{workflow.id}.json"
        
        try:
            workflow_path.write_text(
                json.dumps(workflow.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Workflow saved: %s", workflow_path)
        except Exception as exc:
            logger.error("Failed to save workflow: %s", exc)

    def list_workflows(self) -> list[dict[str, Any]]:
        """Список всех сохранённых workflows."""
        workflows = []
        
        for wf_file in self.workflows_dir.glob("*.json"):
            try:
                data = json.loads(
                    wf_file.read_text(encoding="utf-8")
                )
                workflows.append(data)
            except Exception:
                continue
        
        return sorted(
            workflows,
            key=lambda w: w.get("created_at", ""),
            reverse=True,
        )

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        """Загружает workflow по ID."""
        workflow_path = self.workflows_dir / f"{workflow_id}.json"
        
        if not workflow_path.exists():
            return None
        
        try:
            data = json.loads(
                workflow_path.read_text(encoding="utf-8")
            )
            return Workflow(
                id=data["id"],
                name=data["name"],
                steps=[
                    WorkflowStep(**step)
                    for step in data.get("steps", [])
                ],
                created_at=data.get("created_at", ""),
                tags=data.get("tags", []),
            )
        except Exception as exc:
            logger.error("Failed to load workflow %s: %s", workflow_id, exc)
            return None

    def delete_workflow(self, workflow_id: str) -> bool:
        """Удаляет workflow."""
        workflow_path = self.workflows_dir / f"{workflow_id}.json"
        
        if workflow_path.exists():
            workflow_path.unlink()
            return True
        return False

    def record_tool_call(
        self,
        result: ToolResult,
        arguments: dict[str, Any],
        description: str = "",
    ) -> None:
        """
        Удобный метод для интеграции с ToolRunner.
        
        Записывает успешный tool call в workflow.
        """
        if result.success:
            self.record_step(
                tool_name=result.data.get("tool_name", ""),
                arguments=arguments,
                description=description,
            )


# Глобальный экземпляр
_recorder: WorkflowRecorder | None = None


def get_workflow_recorder() -> WorkflowRecorder:
    """Возвращает глобальный WorkflowRecorder."""
    global _recorder
    if _recorder is None:
        _recorder = WorkflowRecorder()
    return _recorder


def create_workflow_tool() -> dict[str, Any]:
    """Создаёт tool definition для workflow recorder."""
    return {
        "type": "function",
        "function": {
            "name": "workflow_record",
            "description": (
                "Запускает/останавливает запись workflow или "
                "воспроизводит существующий."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "stop", "run", "list", "delete"],
                        "description": "Действие с workflow",
                    },
                    "name": {
                        "type": "string",
                        "description": "Имя workflow (для start)",
                    },
                    "workflow_id": {
                        "type": "string",
                        "description": "ID workflow (для run/delete)",
                    },
                },
                "required": ["action"],
            },
        },
    }