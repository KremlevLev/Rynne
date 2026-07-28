# modules/ui/task_view.py
"""
Task Execution UI — экран активной задачи.

Показывает:
  - заголовок задачи и статус;
  - план с состояниями (completed/active/pending/failed/skipped);
  - activity timeline (сгруппированный);
  - управление: Pause, Resume, Cancel, Retry, Approve;
  - понятное отображение partial success.

Все данные привязаны к реальным событиям backend через event bus.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QFrame,
)

from modules.ui.theme import theme
from modules.ui.primitives import (
    Button,
    IconButton,
    Card,
    Badge,
    StatusIndicator,
)


class PlanStep(QWidget):
    """Один шаг плана с состоянием."""

    def __init__(
        self,
        text: str = "",
        *,
        status: str = "pending",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._status = status
        self._setup_ui()

    def _setup_ui(self) -> None:
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 6, 0, 6)
        self._layout.setSpacing(12)

        self._indicator = StatusIndicator(self._status, size=16)
        self._layout.addWidget(self._indicator)

        self._label = QLabel(self._text)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.primary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
            }}
        """)
        self._layout.addWidget(self._label, stretch=1)

        self._status_badge = Badge(self._status, status="neutral")
        self._layout.addWidget(self._status_badge)

    def set_status(self, status: str) -> None:
        self._status = status
        self._indicator.set_status(status)

        status_labels = {
            "completed": ("✓", "success"),
            "active": ("●", "accent"),
            "pending": ("○", "neutral"),
            "failed": ("!", "danger"),
            "skipped": ("⊘", "neutral"),
        }
        icon, badge_status = status_labels.get(status, ("○", "neutral"))
        self._status_badge.setText(icon)
        self._status_badge.set_status(badge_status)


class PlanView(QWidget):
    """Вид плана задачи."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._steps: list[PlanStep] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

    def add_step(self, text: str, status: str = "pending") -> PlanStep:
        step = PlanStep(text, status=status)
        self._steps.append(step)
        self._layout.addWidget(step)
        return step

    def set_step_status(self, index: int, status: str) -> None:
        if 0 <= index < len(self._steps):
            self._steps[index].set_status(status)

    def clear(self) -> None:
        for step in self._steps:
            step.deleteLater()
        self._steps.clear()


class TimelineEvent(QWidget):
    """Одно событие в timeline."""

    def __init__(
        self,
        time: str = "",
        description: str = "",
        *,
        status: str = "completed",
        details: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._time = time
        self._description = description
        self._status = status
        self._details = details
        self._expanded = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 6, 0, 6)
        self._layout.setSpacing(12)

        self._indicator = StatusIndicator(self._status, size=14)
        self._layout.addWidget(self._indicator)

        content = QVBoxLayout()
        content.setSpacing(2)

        desc_label = QLabel(self._description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.primary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
            }}
        """)
        content.addWidget(desc_label)

        if self._time:
            time_label = QLabel(self._time)
            time_label.setStyleSheet(f"""
                QLabel {{
                    color: {theme.color("text.muted")};
                    font-family: {theme.font_family()};
                    font-size: {theme.font_size("caption")}px;
                }}
            """)
            content.addWidget(time_label)

        self._layout.addLayout(content, stretch=1)

        # Кнопка раскрытия
        if self._details:
            self._expand_btn = IconButton("▼", tooltip="Подробнее", size="sm")
            self._expand_btn.clicked.connect(self._toggle_expand)
            self._layout.addWidget(self._expand_btn)

            self._details_widget = QFrame()
            self._details_widget.hide()
            details_layout = QVBoxLayout(self._details_widget)
            details_layout.setContentsMargins(16, 8, 16, 8)
            details_label = QLabel(self._details)
            details_label.setWordWrap(True)
            details_label.setStyleSheet(f"""
                QLabel {{
                    color: {theme.color("text.secondary")};
                    font-family: {theme.font_family()};
                    font-size: {theme.font_size("secondary")}px;
                }}
            """)
            details_layout.addWidget(details_label)

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self.layout().addWidget(self._details_widget)
            self._details_widget.show()
            self._expand_btn.setText("▲")
        else:
            self._details_widget.hide()
            self._expand_btn.setText("▼")


class TimelineView(QScrollArea):
    """Прокручиваемый timeline активности."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._events: list[TimelineEvent] = []
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
        """)

    def add_event(self, event: TimelineEvent) -> None:
        self._events.append(event)
        self._layout.addWidget(event)

    def clear(self) -> None:
        for event in self._events:
            event.deleteLater()
        self._events.clear()


class TaskView(QWidget):
    """
    Полный экран активной задачи.

    Содержит:
      - заголовок и статус;
      - план;
      - timeline;
      - управление задачей.
    """

    def __init__(
        self,
        *,
        on_pause: Callable[[], None] | None = None,
        on_resume: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_retry: Callable[[], None] | None = None,
        on_approve: Callable[[], None] | None = None,
        on_deny: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._on_cancel = on_cancel
        self._on_retry = on_retry
        self._on_approve = on_approve
        self._on_deny = on_deny
        self._task_id: str | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(16)

        # Заголовок
        self._header = QHBoxLayout()

        self._title = QLabel("Новая задача")
        self._title.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.primary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("h1")}px;
                font-weight: {theme.font_weight("semibold")};
            }}
        """)
        self._header.addWidget(self._title)

        self._header.addStretch()

        self._status_indicator = StatusIndicator("idle")
        self._header.addWidget(self._status_indicator)

        self._status_label = QLabel("Ожидание")
        self._status_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.secondary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
            }}
        """)
        self._header.addWidget(self._status_label)

        self._layout.addLayout(self._header)

        # Таймер
        self._timer_label = QLabel("00:00")
        self._timer_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.muted")};
                font-family: {theme.font_family("mono")}
                font-size: {theme.font_size("secondary")}px;
            }}
        """)
        self._header.addWidget(self._timer_label)

        # Управление
        self._controls = QHBoxLayout()
        self._controls.setSpacing(8)

        self._pause_btn = Button("Остановить", variant="ghost", size="sm")
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        self._controls.addWidget(self._pause_btn)

        self._cancel_btn = Button("Отменить", variant="ghost", size="sm")
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        self._controls.addWidget(self._cancel_btn)

        self._controls.addStretch()

        self._layout.addLayout(self._controls)

        # План
        plan_header = QLabel("План")
        plan_header.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.secondary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("section")}px;
                font-weight: {theme.font_weight("semibold")};
            }}
        """)
        self._layout.addWidget(plan_header)

        self._plan_view = PlanView()
        self._layout.addWidget(self._plan_view)

        # Timeline
        timeline_header = QLabel("Активность")
        timeline_header.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.secondary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("section")}px;
                font-weight: {theme.font_weight("semibold")};
            }}
        """)
        self._layout.addWidget(timeline_header)

        self._timeline = TimelineView()
        self._layout.addWidget(self._timeline, stretch=1)

        # Approval card (скрыт по умолчанию)
        self._approval_card: QWidget | None = None

        self._start_timer()

    def _start_timer(self) -> None:
        self._seconds = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)
        self._timer.start(1000)

    def _on_timer_tick(self) -> None:
        self._seconds += 1
        minutes = self._seconds // 60
        seconds = self._seconds % 60
        self._timer_label.setText(f"{minutes:02d}:{seconds:02d}")

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def set_status(self, status: str, label: str = "") -> None:
        self._status_indicator.set_status(status)
        if label:
            self._status_label.setText(label)

    def set_task_id(self, task_id: str) -> None:
        self._task_id = task_id

    def set_step_status(self, index: int, status: str) -> None:
        """Обновляет статус шага плана по индексу."""
        self._plan_view.set_step_status(index, status)

    def add_plan_step(self, text: str, status: str = "pending") -> PlanStep:
        return self._plan_view.add_step(text, status)

    def add_timeline_event(
        self,
        time: str,
        description: str,
        *,
        status: str = "completed",
        details: str = "",
    ) -> TimelineEvent:
        event = TimelineEvent(
            time, description, status=status, details=details
        )
        self._timeline.add_event(event)
        return event

    def show_approval(
        self,
        title: str,
        description: str,
        *,
        details: str = "",
    ) -> None:
        """Показывает карточку подтверждения."""
        if self._approval_card:
            self._approval_card.deleteLater()

        card = Card(padding=16)
        card_layout = card.layout()

        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("danger")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("bodyLg")}px;
                font-weight: {theme.font_weight("semibold")};
            }}
        """)
        card_layout.addWidget(title_label)

        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.primary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
            }}
        """)
        card_layout.addWidget(desc_label)

        if details:
            details_label = QLabel(details)
            details_label.setWordWrap(True)
            details_label.setStyleSheet(f"""
                QLabel {{
                    color: {theme.color("text.secondary")};
                    font-family: {theme.font_family()};
                    font-size: {theme.font_size("secondary")}px;
                }}
            """)
            card_layout.addWidget(details_label)

        btn_layout = QHBoxLayout()
        reject_btn = Button("Отклонить", variant="ghost", size="sm")
        reject_btn.clicked.connect(self._on_reject_approval)
        btn_layout.addWidget(reject_btn)

        approve_btn = Button("Подтвердить", variant="primary", size="sm")
        approve_btn.clicked.connect(self._on_approve_clicked)
        btn_layout.addWidget(approve_btn)

        card_layout.addLayout(btn_layout)

        self._approval_card = card
        self._layout.insertWidget(3, card)

    def _on_pause_clicked(self) -> None:
        if self._on_pause:
            self._on_pause()

    def _on_resume_clicked(self) -> None:
        if self._on_resume:
            self._on_resume()

    def _on_cancel_clicked(self) -> None:
        if self._on_cancel:
            self._on_cancel()

    def _on_retry_clicked(self) -> None:
        if self._on_retry:
            self._on_retry()

    def _on_approve_clicked(self) -> None:
        if self._on_approve:
            self._on_approve()
        self._hide_approval()

    def _on_reject_approval(self) -> None:
        if self._on_deny:
            self._on_deny()
        self._hide_approval()

    def _hide_approval(self) -> None:
        if self._approval_card:
            self._approval_card.deleteLater()
            self._approval_card = None

    def clear(self) -> None:
        self._plan_view.clear()
        self._timeline.clear()
        self._hide_approval()
