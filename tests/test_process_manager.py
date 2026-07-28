# tests/test_process_manager.py
from __future__ import annotations

import time

from modules.windows.process_manager import (
    ProcessManager,
)


def test_start_and_stop_process() -> None:
    manager = ProcessManager()

    result = manager.start_process(
        ["python", "-c", "print('hello')"],
        label="test_script",
    )

    assert result.success
    assert result.data["pid"] is not None

    process_id = result.data["process_id"]

    time.sleep(0.5)

    status_result = manager.get_process_status(
        process_id
    )

    assert status_result.success
    assert status_result.data["status"] == "exited"
    assert status_result.data["exit_code"] == 0

    stop_result = manager.stop_process(
        process_id
    )

    assert stop_result.success


def test_list_processes() -> None:
    manager = ProcessManager()

    result = manager.start_process(
        ["python", "-c", "print('test')"],
        label="list_test",
    )

    assert result.success

    list_result = manager.list_processes()

    assert list_result.success
    assert "list_test" in list_result.message

    manager.stop_process(
        result.data["process_id"]
    )


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
    # Проверяем, что вывод есть в data["output"], а не в message.
    assert "output_line" in output_result.data["output"]


def test_stop_nonexistent_process() -> None:
    manager = ProcessManager()

    result = manager.stop_process(
        "nonexistent_id"
    )

    assert not result.success
    assert result.code == "PROCESS_NOT_FOUND"


def test_get_nonexistent_process_status() -> None:
    manager = ProcessManager()

    result = manager.get_process_status(
        "nonexistent_id"
    )

    assert not result.success
    assert result.code == "PROCESS_NOT_FOUND"


def test_cleanup_all() -> None:
    manager = ProcessManager()

    result = manager.start_process(
        ["python", "-c", "import time; time.sleep(10)"],
        label="cleanup_test",
    )

    assert result.success

    manager.cleanup_all()

    status_result = manager.get_process_status(
        result.data["process_id"]
    )

    assert status_result.success
    assert status_result.data["status"] in {
        "stopped",
        "exited",
    }
