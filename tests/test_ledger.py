# tests/test_ledger.py
"""Tests for Execution Ledger."""
from __future__ import annotations

import json

from modules.domain.ledger import (
    ExecutionLedger,
    SideEffectRecord,
    get_ledger,
    reset_ledger,
)


def test_side_effect_record_creation() -> None:
    """Test SideEffectRecord can be created."""
    record = SideEffectRecord(
        id="test_1",
        tool_name="test_tool",
        arguments={"arg1": "value1"},
        result={"success": True},
        timestamp="2024-01-01T00:00:00",
        session_id="session_1",
        turn_id="turn_1",
    )
    
    assert record.id == "test_1"
    assert record.tool_name == "test_tool"
    assert record.arguments == {"arg1": "value1"}


def test_side_effect_record_to_dict() -> None:
    """Test SideEffectRecord serialization."""
    record = SideEffectRecord(
        id="test_1",
        tool_name="test_tool",
        arguments={"arg1": "value1"},
        result={"success": True},
        timestamp="2024-01-01T00:00:00",
        session_id="session_1",
        turn_id="turn_1",
    )
    
    d = record.to_dict()
    
    assert d["id"] == "test_1"
    assert d["tool_name"] == "test_tool"
    assert d["arguments"] == {"arg1": "value1"}
    assert d["result"] == {"success": True}


def test_ledger_record() -> None:
    """Test recording side effects."""
    ledger = ExecutionLedger()
    
    record = ledger.record(
        tool_name="test_tool",
        arguments={"arg1": "value1"},
        result={"success": True},
        session_id="session_1",
        turn_id="turn_1",
    )
    
    assert len(ledger) == 1
    assert record.tool_name == "test_tool"


def test_ledger_get_rollbackable() -> None:
    """Test getting rollbackable records."""
    ledger = ExecutionLedger()
    
    # Without rollback info
    ledger.record(
        tool_name="tool1",
        arguments={},
        result={},
        session_id="s1",
        turn_id="t1",
    )
    
    # With rollback info
    ledger.record(
        tool_name="tool2",
        arguments={},
        result={},
        session_id="s1",
        turn_id="t1",
        rollback_info={"file": "test.txt"},
    )
    
    rollbackable = ledger.get_rollbackable_records()
    
    assert len(rollbackable) == 1
    assert rollbackable[0].tool_name == "tool2"


def test_ledger_get_by_tool() -> None:
    """Test filtering by tool name."""
    ledger = ExecutionLedger()
    
    ledger.record(
        tool_name="tool_a",
        arguments={},
        result={},
        session_id="s1",
        turn_id="t1",
    )
    
    ledger.record(
        tool_name="tool_b",
        arguments={},
        result={},
        session_id="s1",
        turn_id="t1",
    )
    
    records_a = ledger.get_by_tool("tool_a")
    records_b = ledger.get_by_tool("tool_b")
    
    assert len(records_a) == 1
    assert len(records_b) == 1


def test_ledger_to_json() -> None:
    """Test JSON serialization."""
    ledger = ExecutionLedger()
    
    ledger.record(
        tool_name="test_tool",
        arguments={"key": "value"},
        result={"success": True},
        session_id="s1",
        turn_id="t1",
    )
    
    json_str = ledger.to_json()
    
    # Should be valid JSON
    data = json.loads(json_str)
    assert len(data) == 1
    assert data[0]["tool_name"] == "test_tool"


def test_ledger_clear() -> None:
    """Test clearing ledger."""
    ledger = ExecutionLedger()
    
    ledger.record(
        tool_name="test_tool",
        arguments={},
        result={},
        session_id="s1",
        turn_id="t1",
    )
    
    assert len(ledger) == 1
    
    ledger.clear()
    
    assert len(ledger) == 0


def test_get_ledger() -> None:
    """Test global ledger singleton."""
    reset_ledger()
    
    ledger1 = get_ledger()
    ledger2 = get_ledger()
    
    assert ledger1 is ledger2
    
    reset_ledger()


def test_ledger_with_rollback_info() -> None:
    """Test record with rollback info."""
    ledger = ExecutionLedger()
    
    record = ledger.record(
        tool_name="write_file",
        arguments={"path": "test.txt", "content": "hello"},
        result={"success": True},
        session_id="s1",
        turn_id="t1",
        rollback_info={
            "type": "file_write",
            "original_content": None,
            "path": "test.txt",
        },
    )
    
    assert record.rollback_info is not None
    assert record.rollback_info["type"] == "file_write"


def test_ledger_session_filter() -> None:
    """Test filtering by session."""
    ledger = ExecutionLedger()
    
    ledger.record(
        tool_name="tool1",
        arguments={},
        result={},
        session_id="session_a",
        turn_id="t1",
    )
    
    ledger.record(
        tool_name="tool2",
        arguments={},
        result={},
        session_id="session_b",
        turn_id="t1",
    )
    
    records_a = ledger.get_rollbackable_records(session_id="session_a")
    records_b = ledger.get_rollbackable_records(session_id="session_b")
    
    assert len(records_a) == 0
    assert len(records_b) == 0


def test_ledger_record_with_verification() -> None:
    """Test recording side effects with verification data."""
    ledger = ExecutionLedger()
    
    record = ledger.record(
        tool_name="write_file",
        arguments={"path": "test.txt"},
        result={"success": True, "message": "Written"},
        session_id="s1",
        turn_id="t1",
        verification={
            "verified": True,
            "method": "file_check",
            "confidence": 0.95,
            "details": "File exists and matches content",
        },
    )
    
    assert record.verification is not None
    assert record.verification["verified"] is True
    assert record.verification["method"] == "file_check"
    assert record.verification["confidence"] == 0.95


def test_ledger_record_with_artifacts() -> None:
    """Test recording side effects with artifacts."""
    ledger = ExecutionLedger()
    
    record = ledger.record(
        tool_name="browser_screenshot",
        arguments={"url": "https://example.com"},
        result={"success": True},
        session_id="s1",
        turn_id="t1",
        artifacts=["artifact_abc123", "artifact_def456"],
    )
    
    assert record.artifacts == ["artifact_abc123", "artifact_def456"]


def test_ledger_record_all_parameters() -> None:
    """Test recording with all optional parameters."""
    ledger = ExecutionLedger()
    
    record = ledger.record(
        tool_name="execute_python_code",
        arguments={"code": "print('hello')"},
        result={"success": True, "message": "Done"},
        session_id="session_test",
        turn_id="turn_test",
        rollback_info={"type": "execution", "snapshot": "backup"},
        verification={
            "verified": True,
            "method": "output_check",
            "confidence": 1.0,
        },
        artifacts=["artifact_xyz"],
    )
    
    assert record.tool_name == "execute_python_code"
    assert record.rollback_info["type"] == "execution"
    assert record.verification is not None
    assert record.artifacts == ["artifact_xyz"]
    # Check full serialization includes all fields
    d = record.to_dict()
    assert "verification" in d
    assert "artifacts" in d


def test_side_effect_record_to_dict_includes_verification_and_artifacts() -> None:
    """Test that to_dict includes verification and artifacts."""
    record = SideEffectRecord(
        id="test_1",
        tool_name="test_tool",
        arguments={"arg1": "value1"},
        result={"success": True},
        timestamp="2024-01-01T00:00:00",
        session_id="session_1",
        turn_id="turn_1",
        rollback_info={"type": "test"},
        verification={"verified": True, "method": "check"},
        artifacts=["art1", "art2"],
    )
    
    d = record.to_dict()
    
    assert d["verification"] == {"verified": True, "method": "check"}
    assert d["artifacts"] == ["art1", "art2"]
