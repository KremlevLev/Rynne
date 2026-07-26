# modules/ui/orb.py
"""
Nova Orb — визуальная сущность Nova.

Лёгкий SVG/canvas-объект с состояниями:
  - Idle     — медленное почти незаметное дыхание
  - Listening— расширяющиеся волны / реакция на микрофон
  - Thinking — медленное вращение внутреннего градиента
  - Working  — направленный поток или мягкая орбитальная линия
  - Speaking — синхронизация с амплитудой TTS
  - Success  — короткая вспышка cyan/green, затем возврат в idle
  - Error    — короткий приглушённый красный импульс
  - Offline  — статичный приглушённый контур

Использует PySide6 QPainter для отрисовки без тяжёлой 3D-графики.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    Qt,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
    QPointF,
    QRectF,
    Property,
)
from PySide6.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QColor,
    QRadialGradient,
    QConicalGradient,
)
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QFrame,
)

from modules.ui.theme import theme


class NovaOrb(QWidget):
    """
    Визуальная сущность Nova — световой орб.

    Отрисовывается с помощью QPainter с градиентами и анимацией.
    """

    def __init__(
        self,
        *,
        size: int = 48,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._size = size
        self._state = "idle"
        self._pulse_phase = 0.0
        self._rotation = 0.0
        self._mic_level = 0.0
        self._reduced_motion = False

        self.setFixedSize(size, size)

        # Таймер анимации
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(30)  # ~33 FPS

        # Анимация состояния
        self._state_anim = QPropertyAnimation(self, b"pulse_phase")
        self._state_anim.setDuration(theme.duration("orbLoop"))
        self._state_anim.setStartValue(0.0)
        self._state_anim.setEndValue(1.0)
        self._state_anim.setLoopCount(-1)
        self._state_anim.setEasingCurve(QEasingCurve.Linear)
        self._state_anim.start()

    @Property(float)
    def pulse_phase(self) -> float:
        return self._pulse_phase

    @pulse_phase.setter
    def pulse_phase(self, value: float) -> None:
        self._pulse_phase = value
        self.update()

    def _on_tick(self) -> None:
        if self._state == "idle":
            self._pulse_phase += 0.01
            if self._pulse_phase > 1.0:
                self._pulse_phase = 0.0
        elif self._state == "thinking":
            self._rotation += 0.5
        elif self._state == "working":
            self._pulse_phase += 0.02
            if self._pulse_phase > 1.0:
                self._pulse_phase = 0.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(0, 0, self._size, self._size)
        center = QPointF(self._size / 2, self._size / 2)
        radius = self._size / 2 - 2

        # Фоновый градиент
        gradient = QRadialGradient(center, radius)
        gradient.setColorAt(0, QColor(theme.color("accent.primary")))
        gradient.setColorAt(1, QColor(theme.color("bg.base")))

        # Цвет в зависимости от состояния
        state_colors = {
            "idle": theme.color("text.muted"),
            "listening": theme.color("accent.secondary"),
            "thinking": theme.color("accent.primary"),
            "working": theme.color("accent.primary"),
            "speaking": theme.color("accent.secondary"),
            "success": theme.color("success"),
            "error": theme.color("danger"),
            "offline": theme.color("text.disabled"),
        }
        color = state_colors.get(self._state, state_colors["idle"])

        # Интенсивность в зависимости от состояния
        if self._state == "idle":
            intensity = 0.3 + 0.2 * abs(
                (self._pulse_phase % 1.0) - 0.5
            ) * 2
        elif self._state == "listening":
            intensity = 0.5 + 0.5 * self._mic_level
        elif self._state == "thinking":
            intensity = 0.7
        elif self._state == "working":
            intensity = 0.5 + 0.3 * abs(
                (self._pulse_phase % 1.0) - 0.5
            ) * 2
        elif self._state == "speaking":
            intensity = 0.4 + 0.6 * self._mic_level
        elif self._state == "success":
            intensity = 0.8
        elif self._state == "error":
            intensity = 0.6
        else:
            intensity = 0.2

        # Применяем интенсивность к цвету
        base_color = QColor(color)
        r = base_color.red() * intensity
        g = base_color.green() * intensity
        b = base_color.blue() * intensity
        final_color = QColor(int(r), int(g), int(b))

        # Рисуем орб
        painter.setBrush(QBrush(final_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(rect)

        # Свечение
        if intensity > 0.3:
            glow_color = QColor(
                final_color.red(),
                final_color.green(),
                final_color.blue(),
                int(80 * intensity),
            )
            glow_pen = QPen(glow_color, 4)
            painter.setPen(glow_pen)
            painter.setBrush(Qt.NoPen)
            painter.drawEllipse(
                QRectF(
                    2, 2,
                    self._size - 4,
                    self._size - 4,
                )
            )

        # Вращение для thinking/working
        if self._state in ("thinking", "working"):
            painter.save()
            painter.translate(center)
            painter.rotate(self._rotation)
            pen = QPen(
                QColor(
                    theme.color("accent.primary"),
                    int(60 * intensity),
                ),
                2,
            )
            painter.setPen(pen)
            painter.setBrush(Qt.NoPen)
            painter.drawEllipse(
                QRectF(-radius + 4, -radius + 4,
                       radius * 2 - 8, radius * 2 - 8)
            )
            painter.restore()

    def set_state(self, state: str) -> None:
        """Устанавливает состояние орба."""
        if state == self._state:
            return
        self._state = state
        self._pulse_phase = 0.0
        self._rotation = 0.0
        self.update()

    def set_mic_level(self, level: float) -> None:
        """Устанавливает уровень микрофона (0.0 - 1.0)."""
        self._mic_level = max(0.0, min(1.0, level))

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = enabled
        if enabled:
            self._timer.stop()
        else:
            self._timer.start(30)

    def get_state(self) -> str:
        return self._state


# ---------------------------------------------------------------------------
# VoiceOverlay
# ---------------------------------------------------------------------------

class VoiceOverlay(QFrame):
    """
    Компактный overlay для голосового режима.

    Появляется по горячей клавише или wake word, показывает:
      - Nova Orb;
      - статус (Слушаю, Думаю, Выполняю);
      - распознанный текст;
      - кнопка stop.

    Не блокирует работу приложений.
    """

    def __init__(
        self,
        *,
        on_stop: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_stop = on_stop
        self._visible = False
        self._setup_ui()
        # Скрытый overlay не должен перехватывать клики —
        # иначе нижележащие виджеты становятся недоступными.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    def _setup_ui(self) -> None:
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(16, 10, 16, 10)
        self._layout.setSpacing(12)

        # Orb
        self._orb = NovaOrb(size=32)
        self._layout.addWidget(self._orb)

        # Статус
        self._status_label = QLabel("Слушаю…")
        self._status_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.primary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
                font-weight: {theme.font_weight("medium")};
            }}
        """)
        self._layout.addWidget(self._status_label)

        # Распознанный текст
        self._text_label = QLabel("")
        self._text_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.secondary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("secondary")}px;
            }}
        """)
        self._layout.addWidget(self._text_label)

        self._layout.addStretch()

        # Кнопка stop
        from modules.ui.primitives import IconButton

        self._stop_btn = IconButton("⏹", tooltip="Остановить", size="sm", variant="ghost")
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        self._layout.addWidget(self._stop_btn)

        # Стиль overlay
        self.setStyleSheet(f"""
            VoiceOverlay {{
                background: {theme.color("bg.surface")};
                border: 1px solid {theme.color("border.subtle")};
                border-radius: {theme.radius("xl")};
            }}
        """)

    def _on_stop_clicked(self) -> None:
        if self._on_stop:
            self._on_stop()

    def show_overlay(self) -> None:
        """Показывает overlay с анимацией."""
        self._visible = True
        # Убираем прозрачность для мыши, чтобы overlay получал клики.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.show()

    def hide_overlay(self) -> None:
        """Скрывает overlay."""
        self._visible = False
        # Делаем overlay прозрачным для мыши, чтобы клики
        # проходили сквозь него к основному UI.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    def is_visible(self) -> bool:
        return self._visible

    def set_state(self, state: str) -> None:
        """Обновляет состояние орба и статус."""
        self._orb.set_state(state)

        state_labels = {
            "listening": "Слушаю…",
            "thinking": "Думаю…",
            "working": "Выполняю…",
            "speaking": "Говорю…",
            "success": "Готово!",
            "error": "Ошибка",
            "idle": "Готова",
        }
        self._status_label.setText(state_labels.get(state, state))

    def set_text(self, text: str) -> None:
        """Обновляет распознанный текст."""
        self._text_label.setText(text)

    def set_mic_level(self, level: float) -> None:
        """Обновляет уровень микрофона."""
        self._orb.set_mic_level(level)

    def set_reduced_motion(self, enabled: bool) -> None:
        self._orb.set_reduced_motion(enabled)
