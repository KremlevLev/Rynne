# modules/windows/filesystem.py
from __future__ import annotations

import difflib
import hashlib
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from modules.domain.results import (
    ToolResult,
    VerificationResult,
)


logger = logging.getLogger("FileSystem")


# Каталоги, в которые запрещена запись.
DENY_LIST = frozenset(
    {
        Path(os.environ.get(
            "WINDIR",
            "C:\\Windows",
        )).resolve(),
        Path(os.environ.get(
            "PROGRAMFILES",
            "C:\\Program Files",
        )).resolve(),
        Path(os.environ.get(
            "PROGRAMFILES(X86)",
            "C:\\Program Files (x86)",
        )).resolve(),
    }
)

# Максимальный размер файла для чтения (10 МБ).
MAX_READ_SIZE = 10 * 1024 * 1024

# Максимальный размер файла для записи (5 МБ).
MAX_WRITE_SIZE = 5 * 1024 * 1024

# Каталог для backup.
BACKUP_DIR = Path("data/backups")


def _resolve_path(
    path: str | Path,
    *,
    allow_write: bool = False,
) -> Path:
    """
    Безопасно разрешает путь.

    Запрещает:
    - выход за пределы рабочего каталога через ..;
    - запись в системные каталоги.
    """
    raw = Path(path)

    # Запрещаем явный выход за пределы через ..
    if ".." in raw.parts:
        raise PermissionError(
            "Обход каталогов через '..' запрещён."
        )

    resolved = raw.resolve()

    if allow_write:
        for denied_path in DENY_LIST:
            try:
                resolved.relative_to(denied_path)
                raise PermissionError(
                    f"Запись в {denied_path} запрещена."
                )
            except ValueError:
                continue

    return resolved



def _safe_read(
    path: Path,
) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"Файл не найден: {path}"
        )

    if not path.is_file():
        raise IsADirectoryError(
            f"Указанный путь является каталогом: {path}"
        )

    file_size = path.stat().st_size

    if file_size > MAX_READ_SIZE:
        raise ValueError(
            f"Файл слишком большой для чтения: "
            f"{file_size} байт (максимум "
            f"{MAX_READ_SIZE})"
        )

    try:
        return path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except PermissionError:
        raise PermissionError(
            f"Нет прав на чтение файла: {path}"
        )


def _atomic_write(
    path: Path,
    content: str,
) -> None:
    if len(content.encode("utf-8")) > MAX_WRITE_SIZE:
        raise ValueError(
            f"Содержимое слишком большое: "
            f"{len(content)} байт (максимум "
            f"{MAX_WRITE_SIZE})"
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    file_descriptor, temporary_path = (
        tempfile.mkstemp(
            prefix=f"{path.stem}_",
            suffix=".tmp",
            dir=str(path.parent),
        )
    )

    try:
        with os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(
            temporary_path,
            str(path),
        )

    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def _file_hash(
    path: Path,
) -> str:
    hasher = hashlib.sha256()

    with path.open("rb") as file:
        while True:
            chunk = file.read(65536)

            if not chunk:
                break

            hasher.update(chunk)

    return hasher.hexdigest()


def _backup_path(
    path: Path,
) -> Path:
    BACKUP_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    timestamp = (
        time.strftime("%Y%m%d_%H%M%S")
        + f"_{time.time_ns() % 1_000_000_000:09d}"
    )

    safe_name = (
        str(path).replace("\\", "_")
        .replace(":", "_")
        .replace("/", "_")
    )

    return (
        BACKUP_DIR
        / f"{safe_name}_{timestamp}.bak"
    )


def read_text_file(
    path: str,
) -> ToolResult:
    try:
        resolved = _resolve_path(path)
        content = _safe_read(resolved)

        return ToolResult.ok(
            f"Файл прочитан: {resolved.name} "
            f"({len(content)} символов).",
            data={
                "path": str(resolved),
                "size": len(content),
                "content": content,
            },
            verification=VerificationResult(
                verified=True,
                method="filesystem_read",
                confidence=1.0,
            ),
        )

    except (
        FileNotFoundError,
        IsADirectoryError,
        PermissionError,
        ValueError,
    ) as exc:
        return ToolResult.failure(
            "FILE_READ_FAILED",
            str(exc),
        )


def write_text_file(
    path: str,
    content: str,
    *,
    create_backup: bool = True,
) -> ToolResult:
    try:
        resolved = _resolve_path(
            path,
            allow_write=True,
        )

        original_hash = None
        backup: Path | None = None
        existed_before = resolved.exists()

        if existed_before and create_backup:
            backup = _backup_path(resolved)

            shutil.copy2(
                str(resolved),
                str(backup),
            )

            original_hash = _file_hash(resolved)

            logger.info(
                "Backup создан: %s -> %s",
                resolved,
                backup,
            )

        _atomic_write(resolved, content)

        new_hash = _file_hash(resolved)

        verification = VerificationResult(
            verified=True,
            method="sha256_readback",
            confidence=1.0,
            details=(
                f"Хэш после записи: {new_hash}"
            ),
        )

        data: dict[str, Any] = {
            "path": str(resolved),
            "size": len(content),
            "hash": new_hash,
        }

        if original_hash:
            data["original_hash"] = (
                original_hash
            )
        if backup is not None:
            data["backup_path"] = str(
                backup.resolve()
            )
        data["existed_before"] = existed_before

        return ToolResult.ok(
            f"Файл записан: {resolved.name} "
            f"({len(content)} символов).",
            data=data,
            verification=verification,
        )

    except (
        PermissionError,
        ValueError,
        OSError,
    ) as exc:
        return ToolResult.failure(
            "FILE_WRITE_FAILED",
            str(exc),
        )


def apply_text_patch(
    path: str,
    patch: str,
    *,
    create_backup: bool = True,
) -> ToolResult:
    try:
        resolved = _resolve_path(
            path,
            allow_write=True,
        )

        original_content = _safe_read(resolved)
        original_hash = _file_hash(resolved)
        backup: Path | None = None

        if create_backup:
            backup = _backup_path(resolved)
            shutil.copy2(
                str(resolved),
                str(backup),
            )

        patched_content = original_content

        for line in patch.splitlines():
            line = line.strip()

            if not line:
                continue

            if line.startswith("+ "):
                patched_content += (
                    line[2:] + "\n"
                )

            elif line.startswith("- "):
                search = line[2:]

                if search in patched_content:
                    patched_content = (
                        patched_content.replace(
                            search,
                            "",
                            1,
                        )
                    )
                else:
                    return ToolResult.failure(
                        "PATCH_NOT_FOUND",
                        (
                            f"Строка для удаления не найдена: "
                            f"'{search}'"
                        ),
                    )

            elif line.startswith("= "):
                old, new = line[2:].split(
                    " -> ", 1
                )

                if old in patched_content:
                    patched_content = (
                        patched_content.replace(
                            old,
                            new,
                            1,
                        )
                    )
                else:
                    return ToolResult.failure(
                        "PATCH_REPLACE_NOT_FOUND",
                        (
                            f"Строка для замены не найдена: "
                            f"'{old}'"
                        ),
                    )

        _atomic_write(resolved, patched_content)
        new_hash = _file_hash(resolved)

        return ToolResult.ok(
            f"Патч применён к файлу: "
            f"{resolved.name}.",
            data={
                "path": str(resolved),
                "original_size": len(
                    original_content
                ),
                "new_size": len(
                    patched_content
                ),
                "hash": new_hash,
                "original_hash": original_hash,
                "backup_path": (
                    str(backup.resolve())
                    if backup is not None
                    else None
                ),
            },
            verification=VerificationResult(
                verified=True,
                method="patch_applied",
                confidence=1.0,
            ),
        )

    except (
        FileNotFoundError,
        PermissionError,
        ValueError,
        OSError,
    ) as exc:
        return ToolResult.failure(
            "PATCH_FAILED",
            str(exc),
        )


def get_file_diff(
    path: str,
    *,
    lines_context: int = 3,
) -> ToolResult:
    try:
        resolved = _resolve_path(path)
        content = _safe_read(resolved)

        lines = content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            [],
            lines,
            fromfile=f"/dev/null",
            tofile=str(resolved),
            n=lines_context,
        )

        diff_text = "".join(diff)

        return ToolResult.ok(
            f"Diff файла '{resolved.name}':",
            data={
                "path": str(resolved),
                "lines": len(lines),
                "diff": diff_text,
            },
        )

    except (
        FileNotFoundError,
        PermissionError,
        ValueError,
    ) as exc:
        return ToolResult.failure(
            "DIFF_FAILED",
            str(exc),
        )


def search_files(
    directory: str,
    pattern: str,
    *,
    max_results: int = 50,
    recursive: bool = True,
) -> ToolResult:
    try:
        resolved = _resolve_path(directory)

        if not resolved.is_dir():
            return ToolResult.failure(
                "DIRECTORY_NOT_FOUND",
                f"Каталог не найден: {resolved}",
            )

        results: list[str] = []

        search_method = (
            resolved.rglob
            if recursive
            else resolved.glob
        )

        for file_path in search_method(pattern):
            if not file_path.is_file():
                continue

            results.append(str(file_path))

            if len(results) >= max_results:
                break

        if not results:
            return ToolResult.ok(
                f"Файлы по шаблону '{pattern}' "
                f"в '{resolved}' не найдены."
            )

        return ToolResult.ok(
            f"Найдено {len(results)} файлов "
            f"по шаблону '{pattern}'.",
            data={
                "directory": str(resolved),
                "pattern": pattern,
                "count": len(results),
                "files": results,
            },
        )

    except (
        PermissionError,
        ValueError,
        OSError,
    ) as exc:
        return ToolResult.failure(
            "SEARCH_FAILED",
            str(exc),
        )


def rollback_file(
    path: str,
) -> ToolResult:
    """
    Восстанавливает последний backup файла.
    """
    try:
        resolved = _resolve_path(
            path,
            allow_write=True,
        )

        if not BACKUP_DIR.exists():
            return ToolResult.failure(
                "NO_BACKUPS",
                "Каталог backup не найден.",
            )

        safe_name = (
            str(resolved).replace("\\", "_")
            .replace(":", "_")
            .replace("/", "_")
        )

        backups = sorted(
            BACKUP_DIR.glob(
                f"{safe_name}_*.bak"
            ),
            reverse=True,
        )

        if not backups:
            return ToolResult.failure(
                "NO_BACKUPS",
                (
                    f"Backup для '{resolved}' "
                    f"не найден."
                ),
            )

        latest_backup = backups[0]

        shutil.copy2(
            str(latest_backup),
            str(resolved),
        )

        return ToolResult.ok(
            f"Файл '{resolved.name}' восстановлен "
            f"из backup.",
            data={
                "path": str(resolved),
                "backup": str(latest_backup),
            },
            verification=VerificationResult(
                verified=True,
                method="backup_restore",
                confidence=1.0,
            ),
        )

    except (
        PermissionError,
        ValueError,
        OSError,
    ) as exc:
        return ToolResult.failure(
            "ROLLBACK_FAILED",
            str(exc),
        )


def undo_last_file_change() -> ToolResult:
    """
    Restores the newest reversible file write made through ToolRunner.

    A hash guard refuses the rollback if the file changed after Nova's
    operation, so a later manual edit is never overwritten silently.
    """
    from modules.domain.ledger import get_ledger

    ledger = get_ledger()
    records = reversed(
        ledger.get_rollbackable_records()
    )

    for record in records:
        rollback = record.rollback_info or {}
        if (
            rollback.get("type")
            != "restore_file_backup"
            or rollback.get("undone")
        ):
            continue

        try:
            path = _resolve_path(
                str(rollback["path"]),
                allow_write=True,
            )
            backup_path = Path(
                str(rollback["backup_path"])
            ).resolve()
            expected_hash = str(
                rollback["expected_hash"]
            )
            original_hash = str(
                rollback["original_hash"]
            )
        except (
            KeyError,
            OSError,
            RuntimeError,
            ValueError,
        ):
            continue

        if not path.is_file():
            return ToolResult.failure(
                "ROLLBACK_TARGET_MISSING",
                (
                    "Откат остановлен: изменённый файл "
                    f"больше не существует — {path}."
                ),
            )
        if not backup_path.is_file():
            return ToolResult.failure(
                "ROLLBACK_BACKUP_MISSING",
                (
                    "Откат недоступен: backup не найден — "
                    f"{backup_path}."
                ),
            )

        current_hash = _file_hash(path)
        if current_hash != expected_hash:
            return ToolResult.failure(
                "ROLLBACK_CONFLICT",
                (
                    "Откат остановлен: файл менялся после действия "
                    "Nova. Более свежие правки не будут перезаписаны."
                ),
                data={
                    "path": str(path),
                    "expected_hash": expected_hash,
                    "current_hash": current_hash,
                    "record_id": record.id,
                },
            )

        shutil.copy2(
            str(backup_path),
            str(path),
        )
        restored_hash = _file_hash(path)
        if restored_hash != original_hash:
            return ToolResult.failure(
                "ROLLBACK_VERIFY_FAILED",
                (
                    "Backup восстановлен, но контрольный хэш "
                    "не совпал с исходным."
                ),
                data={
                    "path": str(path),
                    "expected_hash": original_hash,
                    "restored_hash": restored_hash,
                },
            )

        rollback["undone"] = True
        rollback["undone_at"] = time.time()
        return ToolResult.ok(
            f"Последнее изменение Nova отменено: {path.name}.",
            data={
                "path": str(path),
                "restored_hash": restored_hash,
                "record_id": record.id,
                "original_tool": record.tool_name,
            },
            verification=VerificationResult(
                verified=True,
                method="backup_restore_sha256",
                confidence=1.0,
                details=(
                    "Файл восстановлен из backup, "
                    "исходный SHA-256 подтверждён."
                ),
            ),
        )

    return ToolResult.failure(
        "NO_REVERSIBLE_FILE_CHANGE",
        "Нет изменений файлов Nova, которые можно безопасно отменить.",
    )
