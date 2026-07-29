from __future__ import annotations

import io
import json
import time

from modules.ui.desktop_protocol import (
    make_command,
)
from modules.ui.stdio_desktop_service import (
    StdioDesktopService,
)


def _wait_for_commands(
    service: StdioDesktopService,
    *,
    expected: int,
    timeout: float = 1.0,
) -> list[dict]:
    deadline = time.monotonic() + timeout
    commands: list[dict] = []
    while time.monotonic() < deadline:
        commands.extend(
            service.get_commands(
                max_count=expected,
            )
        )
        if len(commands) >= expected:
            break
        time.sleep(0.005)
    return commands


def test_publish_writes_python_event_as_one_json_line() -> None:
    output = io.StringIO()
    service = StdioDesktopService(
        input_stream=io.StringIO(),
        output_stream=output,
    )

    assert service.publish(
        "assistant_message",
        {"text": "Готово", "success": True},
    )

    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event_type"] == "assistant_message"
    assert event["payload"] == {
        "text": "Готово",
        "success": True,
    }
    assert isinstance(event["created_at"], float)


def test_reader_accepts_valid_commands_and_skips_bad_frames() -> None:
    first = make_command(
        "submit_user_request",
        {"text": "Проверь проект"},
    )
    second = make_command("refresh", {})
    input_stream = io.StringIO(
        "\n".join(
            [
                "not-json",
                "[]",
                json.dumps(first),
                "",
                json.dumps(second),
            ]
        )
        + "\n"
    )
    service = StdioDesktopService(
        input_stream=input_stream,
        output_stream=io.StringIO(),
    )

    assert service.start()
    commands = _wait_for_commands(
        service,
        expected=2,
    )

    assert commands == [first, second]
    assert service.input_closed
    service.stop()


def test_bounded_queue_keeps_freshest_commands() -> None:
    commands = [
        make_command("refresh", {"index": index})
        for index in range(4)
    ]
    input_stream = io.StringIO(
        "".join(
            f"{json.dumps(command)}\n"
            for command in commands
        )
    )
    service = StdioDesktopService(
        input_stream=input_stream,
        output_stream=io.StringIO(),
        queue_size=2,
    )

    assert service.start()
    deadline = time.monotonic() + 1.0
    while (
        not service.input_closed
        and time.monotonic() < deadline
    ):
        time.sleep(0.005)

    received = service.get_commands()
    assert [
        command["payload"]["index"]
        for command in received
    ] == [2, 3]
    service.stop()


def test_oversized_and_empty_frames_are_ignored() -> None:
    valid = make_command("new_task", {})
    input_stream = io.StringIO(
        "\n"
        + ("x" * 1_025)
        + "\n"
        + json.dumps(valid)
        + "\n"
    )
    service = StdioDesktopService(
        input_stream=input_stream,
        output_stream=io.StringIO(),
        max_line_chars=1_024,
    )

    assert service.start()
    commands = _wait_for_commands(
        service,
        expected=1,
    )

    assert commands == [valid]
    service.stop()


def test_stop_prevents_new_events() -> None:
    output = io.StringIO()
    service = StdioDesktopService(
        input_stream=io.StringIO(),
        output_stream=output,
    )
    service.start()
    service.stop()

    assert not service.publish("runtime", {})
    assert output.getvalue() == ""
