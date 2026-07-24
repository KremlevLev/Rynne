# tests/test_workflow_recorder.py
"""Tests for Workflow Recorder."""
from __future__ import annotations

import tempfile
from pathlib import Path

from modules.agent.workflow_recorder import (
    Workflow,
    WorkflowStep,
    WorkflowRecorder,
    get_workflow_recorder,
    create_workflow_tool,
)
from modules.domain.results import ToolResult


def test_workflow_step_creation() -> None:
    """Test WorkflowStep dataclass."""
    step = WorkflowStep(
        tool_name="read_text_file",
        arguments={"path": "test.txt"},
        description="Чтение тестового файла",
    )
    
    assert step.tool_name == "read_text_file"
    assert step.arguments == {"path": "test.txt"}
    assert step.description == "Чтение тестового файла"


def test_workflow_step_to_dict() -> None:
    """Test WorkflowStep serialization."""
    step = WorkflowStep(
        tool_name="write_text_file",
        arguments={"path": "test.txt", "content": "hello"},
    )
    
    d = step.to_dict()
    
    assert d["tool_name"] == "write_text_file"
    assert d["arguments"]["path"] == "test.txt"
    assert d["description"] == ""


def test_workflow_creation() -> None:
    """Test Workflow dataclass."""
    step = WorkflowStep(
        tool_name="test_tool",
        arguments={},
    )
    
    workflow = Workflow(
        id="wf_test123",
        name="Тестовый workflow",
        steps=[step],
    )
    
    assert workflow.id == "wf_test123"
    assert workflow.name == "Тестовый workflow"
    assert len(workflow.steps) == 1
    assert workflow.created_at  # Auto-set


def test_workflow_to_dict() -> None:
    """Test Workflow serialization."""
    step = WorkflowStep(
        tool_name="tool_a",
        arguments={"arg1": "val1"},
    )
    
    workflow = Workflow(
        id="wf_test",
        name="Test",
        steps=[step],
        tags=["test", "demo"],
    )
    
    d = workflow.to_dict()
    
    assert d["id"] == "wf_test"
    assert d["name"] == "Test"
    assert len(d["steps"]) == 1
    assert d["tags"] == ["test", "demo"]


def test_workflow_recorder_start_recording() -> None:
    """Test starting workflow recording."""
    recorder = WorkflowRecorder()
    
    workflow_id = recorder.start_recording(
        "Тест workflow",
        tags=["test"],
    )
    
    assert workflow_id.startswith("wf_")
    assert recorder._active_workflow is not None
    assert recorder._active_workflow.name == "Тест workflow"


def test_workflow_recorder_record_step() -> None:
    """Test recording steps in workflow."""
    recorder = WorkflowRecorder()
    recorder.start_recording("Test")
    
    recorder.record_step(
        "read_file",
        {"path": "test.txt"},
        "Чтение файла",
    )
    
    recorder.record_step(
        "write_file",
        {"path": "out.txt", "content": "data"},
    )
    
    assert len(recorder._active_workflow.steps) == 2
    assert recorder._active_workflow.steps[0].tool_name == "read_file"


def test_workflow_recorder_stop_recording() -> None:
    """Test stopping workflow recording."""
    recorder = WorkflowRecorder()
    recorder.start_recording("Test")
    
    recorder.record_step("tool_a", {})
    recorder.record_step("tool_b", {})
    
    result = recorder.stop_recording(save=False)
    
    assert result.success is True
    assert result.data["steps_count"] == 2
    assert recorder._active_workflow is None


def test_workflow_recorder_stop_without_start() -> None:
    """Test stopping recording without starting."""
    recorder = WorkflowRecorder()
    
    result = recorder.stop_recording()
    
    assert result.success is False
    assert result.code == "NO_ACTIVE_WORKFLOW"


def test_workflow_recorder_list_empty() -> None:
    """Test listing workflows when empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = WorkflowRecorder()
        recorder.workflows_dir = Path(tmpdir)
        
        workflows = recorder.list_workflows()
        
        assert workflows == []


def test_workflow_recorder_save_and_load() -> None:
    """Test saving and loading workflows."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = WorkflowRecorder()
        recorder.workflows_dir = Path(tmpdir)
        
        recorder.start_recording("Saved workflow")
        recorder.record_step("tool_x", {"arg": 1})
        
        result = recorder.stop_recording(save=True)
        
        assert result.success is True
        workflow_id = result.data["workflow_id"]
        
        # Now load it
        loaded = recorder.get_workflow(workflow_id)
        
        assert loaded is not None
        assert loaded.name == "Saved workflow"
        assert len(loaded.steps) == 1


def test_workflow_recorder_delete() -> None:
    """Test deleting a workflow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = WorkflowRecorder()
        recorder.workflows_dir = Path(tmpdir)
        
        recorder.start_recording("To delete")
        recorder.record_step("tool", {})
        result = recorder.stop_recording(save=True)
        workflow_id = result.data["workflow_id"]
        
        # Exists
        assert recorder.get_workflow(workflow_id) is not None
        
        # Delete
        deleted = recorder.delete_workflow(workflow_id)
        
        assert deleted is True
        assert recorder.get_workflow(workflow_id) is None


def test_workflow_recorder_record_tool_call() -> None:
    """Test recording tool call from ToolResult."""
    recorder = WorkflowRecorder()
    recorder.start_recording("Tool calls")
    
    # Successful result
    success_result = ToolResult.ok(
        "Success",
        data={"tool_name": "my_tool"},
    )
    recorder.record_tool_call(
        success_result,
        {"param": "value"},
        "Test call",
    )
    
    # Failed result (should not be recorded)
    fail_result = ToolResult.failure(
        "FAILED",
        "Error",
    )
    recorder.record_tool_call(
        fail_result,
        {},
    )
    
    assert len(recorder._active_workflow.steps) == 1


def test_get_workflow_recorder_singleton() -> None:
    """Test that get_workflow_recorder returns singleton."""
    r1 = get_workflow_recorder()
    r2 = get_workflow_recorder()
    
    assert r1 is r2


def test_create_workflow_tool_schema() -> None:
    """Test workflow tool schema generation."""
    schema = create_workflow_tool()
    
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "workflow_record"
    assert "action" in schema["function"]["parameters"]["required"]