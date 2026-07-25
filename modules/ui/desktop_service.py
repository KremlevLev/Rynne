# modules/ui/desktop_service.py
from __future__ import annotations

import logging
import multiprocessing
import queue
from typing import Any

from modules.ui.desktop_protocol import (
    make_event,
)


logger = logging.getLogger("DesktopService")


def _desktop_process_entry(
    event_queue,
    command_queue,
    *,
    premium: bool = False,
) -> None:
    """
    Точка входа для UI-процесса.

    Если premium=True, использует новый премиальный UI.
    Иначе — fallback на старый desktop.py.
    """
    if premium:
        from modules.ui.premium_desktop import (
            run_premium_desktop,
        )

        run_premium_desktop(
            event_queue=event_queue,
            command_queue=command_queue,
        )
    else:
        from modules.ui.desktop import run_desktop

        run_desktop(
            event_queue=event_queue,
            command_queue=command_queue,
        )


class DesktopService:
    """
    Запускает PySide6 UI в отдельном процессе.
    """

    def __init__(
        self,
        *,
        queue_size: int = 500,
    ) -> None:
        context = multiprocessing.get_context(
            "spawn"
        )

        self._event_queue = context.Queue(
            maxsize=queue_size
        )
        self._command_queue = context.Queue(
            maxsize=queue_size
        )

        self._process = None
        self._context = context

    @property
    def is_running(self) -> bool:
        return bool(
            self._process is not None
            and self._process.is_alive()
        )

    def start(self, *, premium: bool = False) -> bool:
        if self.is_running:
            return True

        self._process = self._context.Process(
            target=_desktop_process_entry,
            args=(
                self._event_queue,
                self._command_queue,
            ),
            kwargs={"premium": premium},
            name="nova-desktop-ui",
            daemon=True,
        )

        self._process.start()

        logger.info(
            "Desktop UI запущен. PID=%s premium=%s",
            self._process.pid,
            premium,
        )

        return True

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        event = make_event(
            event_type,
            payload,
        )

        try:
            self._event_queue.put_nowait(
                event
            )
            return True

        except queue.Full:
            # UI должен видеть свежие события, а не старый backlog.
            try:
                self._event_queue.get_nowait()
            except queue.Empty:
                pass

            try:
                self._event_queue.put_nowait(
                    event
                )
                return True
            except queue.Full:
                return False

        except (
            BrokenPipeError,
            EOFError,
            OSError,
        ):
            logger.warning(
                "Desktop UI недоступен."
            )
            return False

    def get_commands(
        self,
        *,
        max_count: int = 50,
    ) -> list[dict[str, Any]]:
        commands: list[dict[str, Any]] = []

        for _ in range(max_count):
            try:
                command = (
                    self._command_queue.get_nowait()
                )
            except queue.Empty:
                break
            except (
                BrokenPipeError,
                EOFError,
                OSError,
            ):
                break

            if isinstance(command, dict):
                commands.append(command)

        return commands

    def stop(self) -> None:
        if self._process is None:
            return

        self.publish(
            "shutdown",
            {},
        )

        self._process.join(
            timeout=3.0
        )

        if self._process.is_alive():
            logger.warning(
                "Desktop UI не завершился. "
                "Выполняется terminate."
            )
            self._process.terminate()
            self._process.join(
                timeout=2.0
            )

        self._process = None
        logger.info("Desktop UI остановлен.")
