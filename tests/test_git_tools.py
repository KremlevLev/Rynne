# tests/test_git_tools.py
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from modules.windows.git_tools import (
    git_clone_repository,
    git_status,
    git_diff,
    git_log,
    git_commit,
    git_branch,
)
import modules.windows.git_tools as git_tools_module


def _init_git_repo(
    directory: Path,
) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=str(directory),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(directory),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(directory),
        capture_output=True,
    )


def test_git_status_clean() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory)
        _init_git_repo(repo)

        result = git_status(str(repo))

        assert result.success
        assert "чист" in result.message.lower()


def test_git_status_with_changes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory)
        _init_git_repo(repo)

        (repo / "test.txt").write_text("content")

        result = git_status(str(repo))

        assert result.success
        assert result.data["unstaged"]


def test_git_commit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory)
        _init_git_repo(repo)

        (repo / "test.txt").write_text("content")

        result = git_commit(
            str(repo),
            "Initial commit",
        )

        assert result.success
        assert "Initial commit" in result.message


def test_git_log() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory)
        _init_git_repo(repo)

        (repo / "test.txt").write_text("content")
        git_commit(str(repo), "First commit")

        (repo / "test.txt").write_text("modified")
        git_commit(str(repo), "Second commit")

        result = git_log(str(repo))

        assert result.success
        assert len(result.data["commits"]) == 2


def test_git_branch() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory)
        _init_git_repo(repo)

        # Создаём первый коммит, чтобы появилась ветка.
        (repo / "initial.txt").write_text("initial")
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(repo),
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=str(repo),
            capture_output=True,
        )

        result = git_branch(str(repo))

        assert result.success
        assert result.data["branches"]


def test_git_clone_repository_uses_direct_git_and_verifies(monkeypatch, tmp_path: Path) -> None:
    destination = tmp_path / "nanoGPT"
    captured: dict[str, object] = {}

    def fake_run(command, cwd=None, *, timeout_seconds=30.0):
        captured.update(command=command, cwd=cwd, timeout=timeout_seconds)
        (destination / ".git").mkdir(parents=True)
        return "cloned", "", 0

    monkeypatch.setattr(git_tools_module, "_run_git_command", fake_run)
    result = git_clone_repository(
        "https://github.com/karpathy/nanoGPT.git",
        str(destination),
    )

    assert result.success
    assert result.verification.verified
    assert captured["command"] == [
        "clone", "--depth", "1",
        "https://github.com/karpathy/nanoGPT.git", str(destination),
    ]
    assert captured["timeout"] == 150.0


def test_git_clone_repository_rejects_non_repository_url(tmp_path: Path) -> None:
    result = git_clone_repository("https://example.com/file.zip", str(tmp_path / "repo"))
    assert not result.success
    assert result.code == "INVALID_REPOSITORY_URL"
