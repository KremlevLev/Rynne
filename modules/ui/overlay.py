# modules/ui/overlay.py
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk


logger = logging.getLogger("Overlay")

_gui_queue: queue.Queue[str | None] = queue.Queue(maxsize=1)
_overlay_thread: threading.Thread | None = None
_ready_event = threading.Event()


def should_start_legacy_overlay(desktop_transport: str) -> bool:
    """The Tk overlay only belongs to the legacy PySide desktop."""
    return desktop_transport.strip().lower() != "stdio"


class NovaOverlay:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Nova Overlay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.9)
        self.root.configure(bg="#121214")

        width, height = 230, 48
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        x = screen_width - width - 20
        y = screen_height - height - 60
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        self.canvas = tk.Canvas(
            self.root,
            width=16,
            height=16,
            bg="#121214",
            highlightthickness=0,
        )
        self.canvas.pack(side="left", padx=(15, 10))

        self.led = self.canvas.create_oval(
            2,
            2,
            14,
            14,
            fill="#555555",
        )

        self.label = tk.Label(
            self.root,
            text="СПИТ",
            fg="#88888F",
            bg="#121214",
            font=("Segoe UI", 10, "bold"),
        )
        self.label.pack(side="left")

        _ready_event.set()
        self.root.after(50, self.process_queue)

    def process_queue(self) -> None:
        latest_status: str | None = None

        try:
            while True:
                item = _gui_queue.get_nowait()
                _gui_queue.task_done()

                if item is None:
                    self.root.destroy()
                    return

                latest_status = item
        except queue.Empty:
            pass

        if latest_status is not None:
            self.update_ui(latest_status)

        self.root.after(50, self.process_queue)

    def update_ui(self, status: str) -> None:
        states = {
            "СПИТ": ("#555555", "#88888F"),
            "СЛУШАЕТ": ("#00FF66", "#00FF66"),
            "РАСПОЗНАЕТ": ("#00DDAA", "#00DDAA"),
            "ДУМАЕТ": ("#FFCC00", "#FFCC00"),
            "ЖДЕТ РАЗРЕШЕНИЕ": ("#FF8800", "#FF8800"),
            "ВЫПОЛНЯЕТ": ("#B266FF", "#B266FF"),
            "ГОВОРИТ": ("#0099FF", "#0099FF"),
            "ОШИБКА": ("#FF3344", "#FF3344"),
            "ЗАВЕРШАЕТ РАБОТУ": ("#999999", "#999999"),
        }

        color, text_color = states.get(
            status,
            ("#555555", "#88888F"),
        )

        self.canvas.itemconfig(self.led, fill=color)
        self.label.config(text=status, fg=text_color)


def _run_gui() -> None:
    try:
        root = tk.Tk()
        NovaOverlay(root)
        root.mainloop()
    except Exception:
        logger.exception("Ошибка GUI overlay.")
    finally:
        _ready_event.clear()


def start_overlay() -> None:
    global _overlay_thread

    if _overlay_thread and _overlay_thread.is_alive():
        return

    _overlay_thread = threading.Thread(
        target=_run_gui,
        name="nova-overlay",
        daemon=True,
    )
    _overlay_thread.start()
    _ready_event.wait(timeout=3.0)


def update_status(status: str | None) -> None:
    try:
        while True:
            _gui_queue.get_nowait()
            _gui_queue.task_done()
    except queue.Empty:
        pass

    try:
        _gui_queue.put_nowait(status)
    except queue.Full:
        pass


def stop_overlay() -> None:
    update_status(None)
