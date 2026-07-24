# modules/tools/coding_workspace.py
"""Coding workspace with patch/test/rollback functionality.

Изолированная среда для кодинга:
- Создание патчей
- Запуск тестов
- Автоматический rollback при падении тестов
- Backup файлов перед изменением
"""
from __future__ import annotations

import difflib
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modules.domain.results import ToolResult, VerificationResult

logger = logging.getLogger("CodingWorkspace")


@dataclass
class Patch:
    """Представление патча."""
    file_path: Path
    original_content: str
    new_content: str
    diff: str

    def apply(self) -> bool:
        """Применяет патч к файлу."""
        try:
            self.file_path.write_text(self.new_content, encoding="utf-8")
            return True
        except Exception as e:
            logger.exception(f"Failed to apply patch to {self.file_path}")
            return False

    def revert(self) -> bool:
        """Откатывает патч, возвращая оригинальное содержимое."""
        try:
            self.file_path.write_text(self.original_content, encoding="utf-8")
            return True
        except Exception as e:
            logger.exception(f"Failed to revert patch for {self.file_path}")
            return False


class CodingWorkspace:
    """
    Изолированная среда для кодинга с поддержкой patch/test/rollback.
    
    Позволяет безопасно вносить изменения в код:
    - Создаёт backup файлов
    - Генерирует патчи
    - Запускает тесты
    - Автоматически откатывает при падении
    """

    def __init__(
        self,
        project_path: Path | str,
        *,
        auto_rollback: bool = True,
    ) -> None:
        self.project_path = Path(project_path).resolve()
        self.auto_rollback = auto_rollback
        self._backups: dict[str, str] = {}
        self._patches: list[Patch] = []

    def create_patch(
        self,
        file_path: Path | str,
        new_content: str,
    ) -> Patch:
        """
        Создаёт патч для файла.
        
        Args:
            file_path: Путь к файлу
            new_content: Новое содержимое файла
            
        Returns:
            Объект Patch
        """
        file_path = Path(file_path)
        
        if not file_path.is_absolute():
            file_path = self.project_path / file_path
        
        original_content = ""
        if file_path.exists():
            original_content = file_path.read_text(encoding="utf-8")
        
        diff = "\n".join(
            difflib.unified_diff(
                original_content.splitlines(),
                new_content.splitlines(),
                fromfile=str(file_path),
                tofile=str(file_path),
                lineterm="",
            )
        )
        
        patch = Patch(
            file_path=file_path,
            original_content=original_content,
            new_content=new_content,
            diff=diff,
        )
        
        self._patches.append(patch)
        return patch

    def backup_file(
        self,
        file_path: Path | str,
    ) -> str | None:
        """
        Создаёт backup файла.
        
        Args:
            file_path: Путь к файлу
            
        Returns:
            Ключ backup или None
        """
        file_path = Path(file_path)
        
        if not file_path.is_absolute():
            file_path = self.project_path / file_path
        
        if not file_path.exists():
            return None
        
        content = file_path.read_text(encoding="utf-8")
        backup_key = f"{file_path}_{len(self._backups)}"
        self._backups[backup_key] = content
        
        return backup_key

    def restore_backup(
        self,
        backup_key: str,
    ) -> bool:
        """
        Восстанавливает файл из backup.
        
        Args:
            backup_key: Ключ backup
            
        Returns:
            True если восстановление удалось
        """
        if backup_key not in self._backups:
            return False
        
        # Extract file path from backup key
        file_path_str = backup_key.rsplit("_", 1)[0]
        file_path = Path(file_path_str)
        
        try:
            file_path.write_text(self._backups[backup_key], encoding="utf-8")
            return True
        except Exception:
            return False

    def run_tests(
        self,
        test_path: Path | str | None = None,
        *,
        timeout_seconds: int = 120,
    ) -> ToolResult:
        """
        Запускает тесты в проекте.
        
        Args:
            test_path: Путь к тесту (если None - запустить все)
            timeout_seconds: Таймаут выполнения
            
        Returns:
            Результат выполнения тестов
        """
        test_path = Path(test_path) if test_path else None
        
        cmd = ["python", "-m", "pytest"]
        if test_path:
            cmd.append(str(test_path))
        cmd.append("-q")
        
        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            
            passed = "passed" in result.stdout
            failed = "failed" in result.stdout
            
            return ToolResult.ok(
                "Тесты выполнены.",
                data={
                    "returncode": result.returncode,
                    "stdout": result.stdout[:5000],
                    "stderr": result.stderr[:2000],
                    "passed": passed,
                    "failed": failed,
                },
                verification=VerificationResult(
                    verified=(result.returncode == 0),
                    method="pytest_exit_code",
                    confidence=1.0,
                ),
            )
        
        except subprocess.TimeoutExpired:
            return ToolResult.failure(
                "TEST_TIMEOUT",
                f"Тесты превысили таймаут {timeout_seconds}s",
            )
        
        except Exception as e:
            return ToolResult.failure(
                "TEST_RUN_FAILED",
                f"Не удалось запустить тесты: {e}",
            )

    def apply_patches(
        self,
    ) -> ToolResult:
        """
        Применяет все созданные патчи.
        
        Returns:
            Результат применения патчей
        """
        applied = []
        failed = []
        
        for patch in self._patches:
            if patch.apply():
                applied.append(str(patch.file_path))
            else:
                failed.append(str(patch.file_path))
        
        if failed:
            return ToolResult.failure(
                "PATCH_APPLY_FAILED",
                f"Не удалось применить патчи: {failed}",
            )
        
        return ToolResult.ok(
            f"Применено {len(applied)} патчей.",
            data={"applied_files": applied},
        )

    def rollback_all(
        self,
    ) -> ToolResult:
        """
        Откатывает все применённые патчи.
        
        Returns:
            Результат отката
        """
        reverted = []
        failed = []
        
        for patch in self._patches:
            if patch.revert():
                reverted.append(str(patch.file_path))
            else:
                failed.append(str(patch.file_path))
        
        return ToolResult.ok(
            f"Откатано {len(reverted)} патчей.",
            data={"reverted_files": reverted, "failed": failed},
        )

    def safe_apply_and_test(
        self,
        test_path: Path | str | None = None,
        *,
        timeout_seconds: int = 120,
    ) -> ToolResult:
        """
        Безопасно применяет патчи и запускает тесты.
        
        При падении тестов автоматически откатывает изменения.
        
        Args:
            test_path: Путь к тесту
            timeout_seconds: Таймаут тестов
            
        Returns:
            Результат операции
        """
        # Apply patches
        apply_result = self.apply_patches()
        if not apply_result.success:
            return apply_result
        
        # Run tests
        test_result = self.run_tests(test_path, timeout_seconds=timeout_seconds)
        
        # Auto-rollback on failure
        if not test_result.success and self.auto_rollback:
            rollback_result = self.rollback_all()
            test_result.data["auto_rollback"] = rollback_result.data
        
        return test_result

    def get_diff_summary(
        self,
    ) -> str:
        """
        Возвращает сводку всех патчей.
        
        Returns:
            Текстовое описание изменений
        """
        if not self._patches:
            return "Нет созданных патчей."
        
        lines = [f"Всего патчей: {len(self._patches)}\n"]
        
        for i, patch in enumerate(self._patches, 1):
            lines.append(f"Патч {i}: {patch.file_path}")
            lines.append(f"Изменено строк: {len(patch.diff.splitlines())}")
            lines.append("---")
        
        return "\n".join(lines)


def create_coding_workspace(
    project_path: Path | str,
    *,
    auto_rollback: bool = True,
) -> CodingWorkspace:
    """
    Создаёт coding workspace.
    
    Args:
        project_path: Путь к проекту
        auto_rollback: Автоматический откат при падении тестов
        
    Returns:
        Экземпляр CodingWorkspace
    """
    return CodingWorkspace(project_path, auto_rollback=auto_rollback)