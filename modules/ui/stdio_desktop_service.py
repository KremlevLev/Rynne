from __future__ import annotations

import io
import json
import logging
import queue
import sys
import threading
from typing import Any, TextIO

from modules.ui.desktop_protocol import make_event


logger = logging.getLogger("StdioDesktopService")


class StdioDesktopService:
    """
    JSON Lines transport between Nova Core and a desktop shell.

    The class exposes the same small surface as DesktopService, so the core
    bridge does not contain transport-specific logic.
    """

    def __init__(
        self,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
        queue_size: int = 500,
        max_line_chars: int = 2_000_000,
    ) -> None:
        self._input = input_stream or sys.stdin
        self._output = (
            output_stream
            or sys.__stdout__
            or sys.stdout
        )
        self._commands: queue.Queue[
            dict[str, Any]
        ] = queue.Queue(maxsize=queue_size)
        self._max_line_chars = max(
            1_024,
            int(max_line_chars),
        )
        self._write_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._started = False
        self._input_closed = False

    @property
    def is_running(self) -> bool:
        return (
            self._started
            and not self._stop_event.is_set()
            and not self._input_closed
        )

    @property
    def input_closed(self) -> bool:
        return self._input_closed

    def start(
        self,
        *,
        premium: bool = False,
    ) -> bool:
        del premium
        if self._started:
            return self.is_running

        self._started = True
        self._stop_event.clear()
        self._input_closed = False
        self._reader_thread = threading.Thread(
            target=self._read_commands,
            name="nova-desktop-stdio-reader",
            daemon=True,
        )
        self._reader_thread.start()
        logger.info("JSONL Desktop transport запущен.")
        return True

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        if self._stop_event.is_set():
            return False

        line = json.dumps(
            make_event(event_type, payload),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            with self._write_lock:
                self._output.write(line)
                self._output.write("\n")
                self._output.flush()
            return True
        except (
            BrokenPipeError,
            OSError,
            ValueError,
        ):
            logger.warning(
                "Desktop shell закрыл JSONL output."
            )
            self._stop_event.set()
            return False

    def get_commands(
        self,
        *,
        max_count: int = 50,
    ) -> list[dict[str, Any]]:
        commands: list[dict[str, Any]] = []
        for _ in range(max(0, int(max_count))):
            try:
                commands.append(
                    self._commands.get_nowait()
                )
            except queue.Empty:
                break
        return commands

    def stop(self) -> None:
        if not self._started:
            return

        self._stop_event.set()
        thread = self._reader_thread
        if (
            thread is not None
            and thread.is_alive()
            and isinstance(self._input, io.StringIO)
        ):
            thread.join(timeout=1.0)

        self._reader_thread = None
        self._started = False
        logger.info("JSONL Desktop transport остановлен.")

    def _read_commands(self) -> None:
        try:
            while not self._stop_event.is_set():
                line = self._input.readline(
                    self._max_line_chars + 1
                )
                if line == "":
                    self._input_closed = True
                    return
                if len(line) > self._max_line_chars:
                    logger.warning(
                        "Команда Desktop UI превышает лимит."
                    )
                    continue

                raw = line.strip()
                if not raw:
                    continue

                try:
                    command = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(
                        "Desktop UI отправил невалидный JSON."
                    )
                    continue

                if not isinstance(command, dict):
                    logger.warning(
                        "Команда Desktop UI должна быть объектом."
                    )
                    continue

                self._put_command(command)
        except (
            OSError,
            ValueError,
        ):
            self._input_closed = True
            logger.warning(
                "Desktop shell закрыл JSONL input."
            )

    def _put_command(
        self,
        command: dict[str, Any],
    ) -> None:
        try:
            self._commands.put_nowait(command)
            return
        except queue.Full:
            pass

        # As in the old UI event queue, fresh actions win over stale backlog.
        try:
            self._commands.get_nowait()
        except queue.Empty:
            return

        try:
            self._commands.put_nowait(command)
        except queue.Full:
            logger.warning(
                "JSONL command queue переполнена."
            )
