# tests/test_coding_workspace.py
"""Tests for coding workspace module."""
import tempfile
from pathlib import Path

from modules.tools.coding_workspace import (
    CodingWorkspace,
    Patch,
    create_coding_workspace,
)


class TestPatch:
    """Tests for Patch class."""

    def test_patch_apply_and_revert(self, tmp_path: Path):
        """Test patch apply and revert."""
        test_file = tmp_path / "test.py"
        test_file.write_text("original content", encoding="utf-8")
        
        patch = Patch(
            file_path=test_file,
            original_content="original content",
            new_content="new content",
            diff="--- a/test.py\n+++ b/test.py",
        )
        
        # Apply
        assert patch.apply() is True
        assert test_file.read_text(encoding="utf-8") == "new content"
        
        # Revert
        assert patch.revert() is True
        assert test_file.read_text(encoding="utf-8") == "original content"


class TestCodingWorkspace:
    """Tests for CodingWorkspace class."""

    def test_init(self, tmp_path: Path):
        """Test initialization."""
        workspace = CodingWorkspace(tmp_path)
        
        assert workspace.project_path == tmp_path.resolve()
        assert workspace.auto_rollback is True

    def test_create_patch(self, tmp_path: Path):
        """Test patch creation."""
        test_file = tmp_path / "test.py"
        test_file.write_text("original", encoding="utf-8")
        
        workspace = CodingWorkspace(tmp_path)
        patch = workspace.create_patch("test.py", "modified")
        
        assert patch.file_path == test_file
        assert patch.original_content == "original"
        assert patch.new_content == "modified"
        assert "---" in patch.diff

    def test_create_patch_new_file(self, tmp_path: Path):
        """Test patch creation for new file."""
        workspace = CodingWorkspace(tmp_path)
        patch = workspace.create_patch("new_file.py", "new content")
        
        assert patch.original_content == ""
        assert patch.new_content == "new content"

    def test_backup_file(self, tmp_path: Path):
        """Test file backup."""
        test_file = tmp_path / "test.py"
        test_file.write_text("content", encoding="utf-8")
        
        workspace = CodingWorkspace(tmp_path)
        backup_key = workspace.backup_file("test.py")
        
        assert backup_key is not None
        assert "test.py" in backup_key

    def test_backup_nonexistent_file(self, tmp_path: Path):
        """Test backup of nonexistent file."""
        workspace = CodingWorkspace(tmp_path)
        backup_key = workspace.backup_file("nonexistent.py")
        
        assert backup_key is None

    def test_apply_patches(self, tmp_path: Path):
        """Test applying patches."""
        test_file = tmp_path / "test.py"
        test_file.write_text("original", encoding="utf-8")
        
        workspace = CodingWorkspace(tmp_path)
        workspace.create_patch("test.py", "modified")
        
        result = workspace.apply_patches()
        
        assert result.success
        assert test_file.read_text(encoding="utf-8") == "modified"

    def test_rollback_all(self, tmp_path: Path):
        """Test rolling back all patches."""
        test_file = tmp_path / "test.py"
        test_file.write_text("original", encoding="utf-8")
        
        workspace = CodingWorkspace(tmp_path)
        workspace.create_patch("test.py", "modified")
        workspace.apply_patches()
        
        result = workspace.rollback_all()
        
        assert result.success
        assert test_file.read_text(encoding="utf-8") == "original"

    def test_get_diff_summary(self, tmp_path: Path):
        """Test diff summary."""
        test_file = tmp_path / "test.py"
        test_file.write_text("original", encoding="utf-8")
        
        workspace = CodingWorkspace(tmp_path)
        workspace.create_patch("test.py", "modified")
        
        summary = workspace.get_diff_summary()
        
        assert "Всего патчей: 1" in summary
        assert "test.py" in summary

    def test_get_diff_summary_empty(self, tmp_path: Path):
        """Test diff summary with no patches."""
        workspace = CodingWorkspace(tmp_path)
        
        summary = workspace.get_diff_summary()
        
        assert "Нет созданных патчей" in summary


class TestCreateCodingWorkspace:
    """Tests for create_coding_workspace factory function."""

    def test_create_coding_workspace(self, tmp_path: Path):
        """Test factory function."""
        workspace = create_coding_workspace(tmp_path)
        
        assert isinstance(workspace, CodingWorkspace)

    def test_create_coding_workspace_no_rollback(self, tmp_path: Path):
        """Test factory function with auto_rollback=False."""
        workspace = create_coding_workspace(
            tmp_path,
            auto_rollback=False,
        )
        
        assert workspace.auto_rollback is False