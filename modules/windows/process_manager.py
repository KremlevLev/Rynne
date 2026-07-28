# modules/windows/process_manager.py
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.domain.results import ToolResult


logger = logging.getLogger("ProcessManager")


MANAGED_PROCESSES_DIR = Path(
    "data/processes"
)


@dataclass(slots=True)
class ManagedProcess:
    process_id: str
    label: str
    command: list[str]

    pid: int | None = None
    status: str = "created"

    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None

    stdout_path: str | None = None
    stderr_path: str | None = None

    health_check_url: str | None = None
    health_check_port: int | None = None

    _process: subprocess.Popen | None = field(
        default=None,
        repr=False,
    )

    @property
    def is_running(self) -> bool:
        if self._process is not None:
            return self._process.poll() is None
        if self.pid is None or self.status != "running":
            return False
        try:
            os.kill(self.pid, 0)
            return True
        except PermissionError:
            # The PID exists, but the current process cannot signal it.
            return True
        except (ProcessLookupError, OSError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "process_id": self.process_id,
            "label": self.label,
            "command": self.command,
            "pid": self.pid,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "health_check_url": (
                self.health_check_url
            ),
            "health_check_port": (
                self.health_check_port
            ),
            "is_running": self.is_running,
        }


class ProcessManager:
    """
    Управляет долгоживущими процессами Nova.

    Каждый процесс:
    - запускается в отдельном subprocess;
    - stdout/stderr пишутся в ротационные файлы;
    - PID сохраняется для последующего контроля;
    - при остановке завершается всё дерево процессов.
    """

    def __init__(self) -> None:
        self._processes: dict[
            str,
            ManagedProcess,
        ] = {}
        self._lock = threading.RLock()
        self._restore_saved_processes()

    def _save_metadata(
        self,
        process: ManagedProcess,
    ) -> None:
        MANAGED_PROCESSES_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        metadata_path = (
            MANAGED_PROCESSES_DIR
            / f"{process.process_id}.json"
        )

        try:
            with metadata_path.open(
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    process.to_dict(),
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
        except OSError:
            logger.exception(
                "Не удалось сохранить метаданные процесса %s.",
                process.process_id,
            )

    def _refresh_process_state(
        self,
        process: ManagedProcess,
    ) -> None:
        if process.status != "running":
            return

        if process._process is not None:
            exit_code = process._process.poll()
            if exit_code is None:
                return
            process.exit_code = exit_code
        elif process.is_running:
            return

        process.status = "exited"
        process.finished_at = datetime.now(
            timezone.utc
        ).isoformat()
        self._save_metadata(process)
    def test_read_process_output() -> None:
        manager = ProcessManager()
    
        result = manager.start_process(
            [
                "python",
                "-c",
                "import time; time.sleep(0.2); "
                "print('output_line')",
            ],
            label="output_test",
        )
    
        assert result.success
    
        process_id = result.data["process_id"]
    
        time.sleep(1.0)
    
        output_result = manager.read_process_output(
            process_id,
            max_lines=10,
        )
    
        assert output_result.success
        assert "output_line" in output_result.data["output"]

    def _restore_saved_processes(self) -> None:
        if not MANAGED_PROCESSES_DIR.exists():
            return

        for metadata_path in (
            MANAGED_PROCESSES_DIR.glob("*.json")
        ):
            try:
                with metadata_path.open(
                    "r",
                    encoding="utf-8",
                ) as file:
                    data = json.load(file)

                process_id = data.get("process_id")

                if not process_id:
                    continue

                process = ManagedProcess(
                    process_id=process_id,
                    label=str(
                        data.get("label", "")
                    ),
                    command=list(
                        data.get("command", [])
                    ),
                    pid=data.get("pid"),
                    status=str(
                        data.get("status", "restored")
                    ),
                    started_at=data.get(
                        "started_at"
                    ),
                    finished_at=data.get(
                        "finished_at"
                    ),
                    exit_code=data.get("exit_code"),
                    stdout_path=data.get(
                        "stdout_path"
                    ),
                    stderr_path=data.get(
                        "stderr_path"
                    ),
                    health_check_url=data.get(
                        "health_check_url"
                    ),
                    health_check_port=data.get(
                        "health_check_port"
                    ),
                )

                # Проверяем, жив ли процесс.
                if process.pid is not None:
                    try:
                        os.kill(
                            process.pid,
                            0,
                        )
                        process.status = "running"
                    except PermissionError:
                        process.status = "running"
                    except (
                        ProcessLookupError,
                        OSError,
                    ):
                        process.status = "exited"
                        process.finished_at = (
                            datetime.now(
                                timezone.utc
                            ).isoformat()
                        )

                self._processes[process_id] = (
                    process
                )

            except Exception:
                logger.exception(
                    "Не удалось восстановить процесс из %s.",
                    metadata_path,
                )

    def _log_paths(
        self,
        process_id: str,
    ) -> tuple[Path, Path]:
        MANAGED_PROCESSES_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        stdout_path = (
            MANAGED_PROCESSES_DIR
            / f"{process_id}_stdout.log"
        )
        stderr_path = (
            MANAGED_PROCESSES_DIR
            / f"{process_id}_stderr.log"
        )

        return stdout_path, stderr_path

    def start_process(
        self,
        command: list[str],
        *,
        label: str | None = None,
        cwd: str | Path | None = None,
        health_check_url: str | None = None,
        health_check_port: int | None = None,
    ) -> ToolResult:
        if not command:
            return ToolResult.failure(
                "EMPTY_COMMAND",
                "Команда не указана.",
            )

        process_id = (
            f"proc_{uuid.uuid4().hex}"
        )
        resolved_label = (
            label or command[0]
        )

        stdout_path, stderr_path = (
            self._log_paths(process_id)
        )

        try:
            stdout_file = stdout_path.open(
                "w",
                encoding="utf-8",
            )
            stderr_file = stderr_path.open(
                "w",
                encoding="utf-8",
            )

            process = subprocess.Popen(
                command,
                stdout=stdout_file,
                stderr=stderr_file,
                cwd=str(cwd) if cwd else None,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                ),
            )

        except FileNotFoundError:
            return ToolResult.failure(
                "COMMAND_NOT_FOUND",
                (
                    f"Команда не найдена: "
                    f"{command[0]}"
                ),
            )

        except OSError as exc:
            return ToolResult.failure(
                "PROCESS_START_FAILED",
                (
                    f"Не удалось запустить процесс: "
                    f"{exc}"
                ),
            )

        managed = ManagedProcess(
            process_id=process_id,
            label=resolved_label,
            command=command,
            pid=process.pid,
            status="running",
            started_at=datetime.now(
                timezone.utc
            ).isoformat(),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            health_check_url=health_check_url,
            health_check_port=health_check_port,
            _process=process,
        )

        with self._lock:
            self._processes[process_id] = (
                managed
            )

        self._save_metadata(managed)

        logger.info(
            "Процесс запущен: process_id=%s "
            "label=%s pid=%s command=%s",
            process_id,
            resolved_label,
            process.pid,
            command,
        )

        return ToolResult.ok(
            (
                f"Процесс '{resolved_label}' запущен. "
                f"PID: {process.pid}. "
                f"Идентификатор: {process_id}."
            ),
            data={
                "process_id": process_id,
                "pid": process.pid,
                "label": resolved_label,
                "command": command,
            },
        )

    def get_process_status(
        self,
        process_id: str,
    ) -> ToolResult:
        with self._lock:
            process = self._processes.get(
                process_id
            )
            if process is not None:
                self._refresh_process_state(process)

        if process is None:
            return ToolResult.failure(
                "PROCESS_NOT_FOUND",
                (
                    f"Процесс с идентификатором "
                    f"'{process_id}' не найден."
                ),
            )

        return ToolResult.ok(
            f"Статус процесса '{process.label}': "
            f"{process.status}.",
            data=process.to_dict(),
        )

    def read_process_output(
        self,
        process_id: str,
        *,
        max_lines: int = 100,
        stream: str = "stdout",
    ) -> ToolResult:
        with self._lock:
            process = self._processes.get(
                process_id
            )

        if process is None:
            return ToolResult.failure(
                "PROCESS_NOT_FOUND",
                (
                    f"Процесс '{process_id}' "
                    "не найден."
                ),
            )

        log_path_str = (
            process.stdout_path
            if stream == "stdout"
            else process.stderr_path
        )

        if not log_path_str:
            return ToolResult.failure(
                "LOG_NOT_AVAILABLE",
                (
                    f"Лог '{stream}' для процесса "
                    f"'{process_id}' недоступен."
                ),
            )

        log_path = Path(log_path_str)

        if not log_path.exists():
            return ToolResult.failure(
                "LOG_FILE_NOT_FOUND",
                (
                    f"Файл лога не найден: "
                    f"{log_path}"
                ),
            )

        try:
            with log_path.open(
                "r",
                encoding="utf-8",
                errors="replace",
            ) as file:
                all_lines = file.readlines()

            tail_lines = all_lines[-max_lines:]

            output = "".join(tail_lines)

            return ToolResult.ok(
                (
                    f"Прочитано {len(tail_lines)} "
                    f"строк из {stream} процесса "
                    f"'{process.label}'."
                ),
                data={
                    "process_id": process_id,
                    "stream": stream,
                    "total_lines": len(all_lines),
                    "returned_lines": len(
                        tail_lines
                    ),
                    "output": output,
                },
            )

        except OSError as exc:
            return ToolResult.failure(
                "LOG_READ_FAILED",
                (
                    f"Не удалось прочитать лог: "
                    f"{exc}"
                ),
            )

    def stop_process(
        self,
        process_id: str,
        *,
        force: bool = False,
    ) -> ToolResult:
        with self._lock:
            process = self._processes.get(
                process_id
            )
            if process is not None:
                self._refresh_process_state(process)

        if process is None:
            return ToolResult.failure(
                "PROCESS_NOT_FOUND",
                (
                    f"Процесс '{process_id}' "
                    "не найден."
                ),
            )

        if not process.is_running:
            return ToolResult.ok(
                (
                    f"Процесс '{process.label}' "
                    "уже завершён."
                ),
                data=process.to_dict(),
            )

        assert process._process is not None

        try:
            if force:
                process._process.kill()
            else:
                process._process.terminate()

                try:
                    process._process.wait(
                        timeout=5.0
                    )
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "Процесс %s не завершился "
                        "за 5 секунд. Принудительное "
                        "завершение.",
                        process_id,
                    )
                    process._process.kill()

            process._process.wait()

            process.status = "stopped"
            process.finished_at = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )
            process.exit_code = (
                process._process.returncode
            )

            self._save_metadata(process)

            logger.info(
                "Процесс остановлен: process_id=%s "
                "label=%s exit_code=%s",
                process_id,
                process.label,
                process.exit_code,
            )

            return ToolResult.ok(
                (
                    f"Процесс '{process.label}' "
                    f"остановлен. "
                    f"Код завершения: "
                    f"{process.exit_code}."
                ),
                data=process.to_dict(),
            )

        except OSError as exc:
            return ToolResult.failure(
                "PROCESS_STOP_FAILED",
                (
                    f"Не удалось остановить процесс: "
                    f"{exc}"
                ),
            )

    def list_processes(self) -> ToolResult:
        with self._lock:
            processes = list(
                self._processes.values()
            )
            for process in processes:
                self._refresh_process_state(process)

        if not processes:
            return ToolResult.ok(
                "Нет управляемых процессов."
            )

        lines: list[str] = []

        for process in processes:
            lines.append(
                (
                    f"- {process.label} "
                    f"(ID: {process.process_id}, "
                    f"PID: {process.pid}, "
                    f"статус: {process.status})"
                )
            )

        return ToolResult.ok(
            "\n".join(lines),
            data={
                "count": len(processes),
                "processes": [
                    p.to_dict() for p in processes
                ],
            },
        )

    def cleanup_all(self) -> None:
        """
        Останавливает все управляемые процессы.

        Вызывается при завершении Nova.
        """
        with self._lock:
            process_ids = list(
                self._processes.keys()
            )

        for process_id in process_ids:
            try:
                self.stop_process(
                    process_id,
                    force=True,
                )
            except Exception:
                logger.exception(
                    "Не удалось остановить процесс %s.",
                    process_id,
                )

        logger.info(
            "Очистка процессов завершена."
        )
