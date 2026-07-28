# modules/ui/primitives.py
"""
Базовые UI primitives для Nova Desktop UI.

Содержит переиспользуемые виджеты, построенные на PySide6, стилизованные
через design tokens из modules.ui.theme.

Все primitives:
  - Button          — текстовая кнопка с состояниями
  - IconButton      — кнопка-иконка
  - Input           — поле ввода с placeholder и clear
  - Card            — поверхность с тенью
  - Badge           — маленькая метка статуса
  - Tooltip         — подсказка по hover
  - Modal           — модальное окно
  - Dropdown        — выпадающий список
  - Tabs            — вкладки
  - Toggle          — переключатель
  - Skeleton        — placeholder при загрузке
  - Toast           — временное уведомление
  - EmptyState      — пустое состояние
  - StatusIndicator — индикатор статуса (colored dot)
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    Qt,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
)
from PySide6.QtGui import (
    QFont,
    QColor,
    QPainter,
    QBrush,
)
from PySide6.QtWidgets import (
    QWidget,
    QPushButton,
    QLineEdit,
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QFrame,
    QMenu,
    QGraphicsOpacityEffect,
)

from modules.ui.theme import theme


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _set_font(widget: QWidget, size_key: str = "body",
              weight_key: str = "regular", mono: bool = False) -> None:
    """Устанавливает шрифт на виджет из design tokens."""
    # QFont принимает одно имя семейства, а не CSS fallback-список.
    # Передача строки вида "'Inter', 'Segoe UI', sans-serif" приводила
    # к tofu-квадратам вместо кириллицы на части Windows-систем.
    font = QFont("Cascadia Mono" if mono else "Segoe UI")
    font.setPixelSize(theme.font_size(size_key))
    font.setWeight(QFont.Weight(theme.font_weight(weight_key)))
    widget.setFont(font)


def _set_style(widget: QWidget, css: str) -> None:
    """Применяет CSS-стили к виджету."""
    widget.setStyleSheet(css)


# ---------------------------------------------------------------------------
# Button
# ---------------------------------------------------------------------------

class Button(QPushButton):
    """
    Кнопка с состояниями: default, hover, pressed, disabled.

    Поддерживает варианты: primary, secondary, ghost, danger.
    """

    def __init__(
        self,
        text: str = "",
        *,
        variant: str = "secondary",
        size: str = "md",
        icon: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._variant = variant
        self._size = size
        self._icon_text = icon
        self._reduced_motion = False
        self._apply_style()
        _set_font(self, "body", "medium")

    def _apply_style(self) -> None:
        bg = theme.color("bg.surface")
        bg_hover = theme.color("bg.surfaceHover")
        text_color = theme.color("text.primary")
        border = theme.color("border.subtle")
        radius = theme.radius("md")

        if self._variant == "primary":
            bg = theme.color("accent.primary")
            bg_hover = theme.color("accent.primary")
            text_color = "#FFFFFF"
        elif self._variant == "ghost":
            bg = "transparent"
            bg_hover = theme.color("accent.soft")
        elif self._variant == "danger":
            bg = theme.color("danger")
            bg_hover = theme.color("danger")
            text_color = "#FFFFFF"

        padding = {
            "sm": "6px 14px",
            "md": "8px 16px",
            "lg": "10px 20px",
        }.get(self._size, "8px 16px")

        self.setStyleSheet(f"""
            Button {{
                background: {bg};
                color: {text_color};
                border: 1px solid {border};
                border-radius: {radius};
                padding: {padding};
                font-family: {theme.font_family()};
                font-size: {theme.font_size('body')}px;
                font-weight: {theme.font_weight('medium')};
            }}
            Button:hover {{
                background: {bg_hover};
                border-color: {theme.color('border.active') if self._variant == 'ghost' else border};
            }}
            Button:pressed {{
                background: {bg_hover};
            }}
            Button:disabled {{
                background: {theme.color('bg.surface')};
                color: {theme.color('text.disabled')};
                border-color: {theme.color('border.subtle')};
            }}
        """)

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = enabled
        self._apply_style()


# ---------------------------------------------------------------------------
# IconButton
# ---------------------------------------------------------------------------

class IconButton(QPushButton):
    """Кнопка с иконкой (Unicode или текст). Размеры: sm, md, lg."""

    def __init__(
        self,
        icon: str = "",
        *,
        tooltip: str = "",
        size: str = "md",
        variant: str = "ghost",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(icon, parent)
        self._size = size
        self._variant = variant
        self.setToolTip(tooltip)
        self._apply_style()
        _set_font(self, "body", "medium")

    def _apply_style(self) -> None:
        dim = {"sm": 24, "md": 32, "lg": 40}.get(self._size, 32)
        radius = theme.radius("pill")
        bg = "transparent"
        text_color = theme.color("text.secondary")

        if self._variant == "primary":
            bg = theme.color("accent.primary")
            text_color = "#FFFFFF"

        self.setFixedSize(dim, dim)
        self.setStyleSheet(f"""
            IconButton {{
                background: {bg};
                color: {text_color};
                border: 1px solid {theme.color('border.subtle')};
                border-radius: {radius};
                font-family: {theme.font_family()};
                font-size: {theme.font_size('body')}px;
                font-weight: {theme.font_weight('medium')};
            }}
            IconButton:hover {{
                background: {theme.color('accent.soft') if self._variant == 'ghost' else bg};
                border-color: {theme.color('border.active')};
                color: {theme.color('accent.primary') if self._variant == 'ghost' else text_color};
            }}
            IconButton:disabled {{
                color: {theme.color('text.disabled')};
                border-color: {theme.color('border.subtle')};
            }}
        """)


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

class Input(QLineEdit):
    """Поле ввода с placeholder, clear button и поддержкой multiline."""

    def __init__(
        self,
        placeholder: str = "",
        *,
        text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setText(text)
        self._apply_style()
        _set_font(self, "body", "regular")

    def _apply_style(self) -> None:
        radius = theme.radius("md")
        self.setStyleSheet(f"""
            Input {{
                background: {theme.color('bg.surface')};
                color: {theme.color('text.primary')};
                border: 1px solid {theme.color('border.subtle')};
                border-radius: {radius};
                padding: 8px 12px;
                font-family: {theme.font_family()};
                font-size: {theme.font_size('body')}px;
                font-weight: {theme.font_weight('regular')};
            }}
            Input:focus {{
                border-color: {theme.color('border.active')};
                background: {theme.color('bg.surfaceHover')};
            }}
            Input:disabled {{
                background: {theme.color('bg.elevated')};
                color: {theme.color('text.disabled')};
            }}
        """)


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

class Card(QFrame):
    """Поверхность с тенью и скруглением."""

    def __init__(
        self,
        *,
        padding: int = 16,
        radius_key: str = "lg",
        hover: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._padding = padding
        self._radius_key = radius_key
        self._hover = hover
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(padding, padding, padding, padding)
        layout.setSpacing(8)

    def _apply_style(self) -> None:
        bg = theme.color("bg.surface")
        border = theme.color("border.subtle")
        radius = theme.radius(self._radius_key)

        hover_css = ""
        if self._hover:
            hover_css = f"""
                Card:hover {{
                    background: {theme.color('bg.surfaceHover')};
                }}
            """

        self.setStyleSheet(f"""
            Card {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {radius};
            }}
            {hover_css}
        """)

    def set_padding(self, padding: int) -> None:
        self._padding = padding
        self.layout().setContentsMargins(padding, padding, padding, padding)


# ---------------------------------------------------------------------------
# Badge
# ---------------------------------------------------------------------------

class Badge(QLabel):
    """Маленькая метка статуса: success, warning, danger, info, neutral."""

    def __init__(
        self,
        text: str = "",
        *,
        status: str = "neutral",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._status = status
        self._apply_style()
        _set_font(self, "caption", "medium")

    def _apply_style(self) -> None:
        status_colors = {
            "success": theme.color("success"),
            "warning": theme.color("warning"),
            "danger": theme.color("danger"),
            "info": theme.color("info"),
            "neutral": theme.color("text.muted"),
            "accent": theme.color("accent.primary"),
        }
        bg = status_colors.get(self._status, status_colors["neutral"])
        radius = theme.radius("pill")

        self.setStyleSheet(f"""
            Badge {{
                background: {bg}20;
                color: {bg};
                border-radius: {radius};
                padding: 2px 8px;
                font-family: {theme.font_family()};
                font-size: {theme.font_size('caption')}px;
                font-weight: {theme.font_weight('medium')};
            }}
        """)

    def set_status(self, status: str) -> None:
        self._status = status
        self._apply_style()


# ---------------------------------------------------------------------------
# StatusIndicator
# ---------------------------------------------------------------------------

class StatusIndicator(QWidget):
    """Цветной индикатор (кружок) со статусом."""

    def __init__(
        self,
        status: str = "idle",
        *,
        size: int = 10,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._status = status
        self._dot_size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        colors = {
            "idle": theme.color("text.muted"),
            "active": theme.color("accent.primary"),
            "success": theme.color("success"),
            "warning": theme.color("warning"),
            "danger": theme.color("danger"),
            "offline": theme.color("text.disabled"),
        }
        color = colors.get(self._status, colors["idle"])

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(color)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, self._dot_size, self._dot_size)

    def set_status(self, status: str) -> None:
        self._status = status
        self.update()


# ---------------------------------------------------------------------------
# Tooltip
# ---------------------------------------------------------------------------

class Tooltip:
    """Простая подсказка по hover для любого виджета."""

    @staticmethod
    def attach(widget: QWidget, text: str) -> None:
        widget.setToolTip(text)


# ---------------------------------------------------------------------------
# Modal
# ---------------------------------------------------------------------------

class Modal(QFrame):
    """Модальное окно с затемнением и центрированием."""

    def __init__(
        self,
        title: str = "",
        *,
        width: int = 480,
        height: int = 320,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._content_widget: QWidget | None = None
        self._setup_ui(width, height)

    def _setup_ui(self, width: int, height: int) -> None:
        overlay = QFrame(self)
        overlay.setStyleSheet(
            f"background: {theme.color('bg.overlay')};"
        )
        overlay.setGeometry(0, 0, width, height)

        content = Card(parent=self, padding=20)
        content.setGeometry(40, 40, width - 80, height - 80)

        header = QHBoxLayout()
        title_label = QLabel(self._title)
        _set_font(title_label, "section", "semibold")
        header.addWidget(title_label)
        header.addStretch()

        close_btn = IconButton("✕", tooltip="Закрыть", size="sm")
        close_btn.clicked.connect(self.hide)
        header.addWidget(close_btn)

        content.layout().addLayout(header)

        self._content_widget = QWidget()
        content.layout().addWidget(self._content_widget)

        self.hide()

    def set_content(self, widget: QWidget) -> None:
        if self._content_widget:
            layout = self._content_widget.layout()
            if layout is None:
                layout = QVBoxLayout(self._content_widget)
                self._content_widget.setLayout(layout)
            layout.addWidget(widget)

    def show_modal(self) -> None:
        self.show()


# ---------------------------------------------------------------------------
# Dropdown
# ---------------------------------------------------------------------------

class Dropdown(QFrame):
    """Выпадающий список с поиском."""

    def __init__(
        self,
        placeholder: str = "Выберите...",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_open = False
        self._menu: QMenu | None = None
        self._items: list[tuple[str, str]] = []
        self._selected_text = placeholder
        self._on_select: Callable[[str], None] | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._button = Button(self._selected_text, variant="secondary", size="sm")
        self._button.clicked.connect(self._toggle)
        layout.addWidget(self._button)

        self._arrow = QLabel("▼")
        _set_font(self._arrow, "caption", "regular")
        layout.addWidget(self._arrow)

        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(f"""
            Dropdown {{
                background: {theme.color('bg.surface')};
                border: 1px solid {theme.color('border.subtle')};
                border-radius: {theme.radius('md')};
            }}
        """)

    def _toggle(self) -> None:
        if self._is_open:
            self._close()
        else:
            self._open()

    def _open(self) -> None:
        if not self._items:
            return
        self._is_open = True
        self._arrow.setText("▲")
        if self._menu is None:
            self._menu = QMenu(self)
        self._menu.clear()
        for label, value in self._items:
            action = self._menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, item_label=label, item_value=value: (
                    self._select(item_label, item_value)
                )
            )
        self._menu.aboutToHide.connect(self._close)
        self._menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _close(self) -> None:
        self._is_open = False
        self._arrow.setText("▼")

    def set_items(self, items: list[tuple[str, str]]) -> None:
        """Устанавливает список (label, value)."""
        self._items = [
            (str(label), str(value))
            for label, value in items
        ]

    def _select(self, label: str, value: str) -> None:
        self._selected_text = label
        self._button.setText(label)
        self._close()
        if self._on_select is not None:
            self._on_select(value)

    def on_select(self, callback: Callable[[str], None]) -> None:
        self._on_select = callback

    def current_text(self) -> str:
        return self._selected_text


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

class Tabs(QFrame):
    """Вкладки с переключением."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tabs: list[tuple[str, QWidget]] = []
        self._current_index = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        self._header = QHBoxLayout()
        self._header.setContentsMargins(0, 0, 0, 0)
        self._header.setSpacing(0)

        self._content = QVBoxLayout()
        self._content.setContentsMargins(0, 0, 0, 0)

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addLayout(self._header)
        main.addLayout(self._content)

    def add_tab(self, label: str, widget: QWidget) -> None:
        index = len(self._tabs)
        self._tabs.append((label, widget))

        btn = Button(label, variant="ghost", size="sm")
        btn.clicked.connect(lambda _, i=index: self._switch(i))
        self._header.addWidget(btn)

        widget.setVisible(index == 0)
        self._content.addWidget(widget)

    def _switch(self, index: int) -> None:
        if index == self._current_index:
            return
        old_label, old_widget = self._tabs[self._current_index]
        new_label, new_widget = self._tabs[index]

        old_widget.setVisible(False)
        new_widget.setVisible(True)
        self._current_index = index

    def current_index(self) -> int:
        return self._current_index


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------

class Toggle(QPushButton):
    """Переключатель вкл/выкл."""

    def __init__(
        self,
        *,
        checked: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self._apply_style()

    def _apply_style(self) -> None:
        self.setFixedSize(40, 24)
        self.setStyleSheet(f"""
            Toggle {{
                background: {theme.color('text.disabled')};
                border: none;
                border-radius: {theme.radius('pill')};
            }}
            Toggle:checked {{
                background: {theme.color('accent.primary')};
            }}
        """)


# ---------------------------------------------------------------------------
# Skeleton
# ---------------------------------------------------------------------------

class Skeleton(QLabel):
    """Placeholder при загрузке — мерцающая анимация."""

    def __init__(
        self,
        *,
        width: int = 120,
        height: int = 16,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._apply_style()

        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(theme.duration("micro"))
        self._anim.setStartValue(0.3)
        self._anim.setEndValue(0.7)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.start()

    def _apply_style(self) -> None:
        self.setStyleSheet(f"""
            Skeleton {{
                background: {theme.color('border.subtle')};
                border-radius: {theme.radius('sm')};
            }}
        """)


# ---------------------------------------------------------------------------
# Toast
# ---------------------------------------------------------------------------

class Toast(QLabel):
    """Временное уведомление, исчезает через N секунд."""

    def __init__(
        self,
        message: str,
        *,
        duration: int = 3000,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(message, parent)
        self._duration = duration
        self._apply_style()
        _set_font(self, "bodySm", "medium")

        QTimer.singleShot(duration, self, self._fade_out)

    def _apply_style(self) -> None:
        radius = theme.radius("md")
        self.setStyleSheet(f"""
            Toast {{
                background: {theme.color('bg.surface')};
                color: {theme.color('text.primary')};
                border: 1px solid {theme.color('border.subtle')};
                border-left: 4px solid {theme.color('accent.primary')};
                border-radius: {radius};
                padding: 10px 16px;
            }}
        """)

    def _fade_out(self) -> None:
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(theme.duration("micro"))
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self.deleteLater)
        anim.start()


# ---------------------------------------------------------------------------
# EmptyState
# ---------------------------------------------------------------------------

class EmptyState(QWidget):
    """Пустое состояние с иконкой и текстом."""

    def __init__(
        self,
        title: str = "Ничего не найдено",
        subtitle: str = "",
        *,
        icon: str = "◉",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._setup_ui(title, subtitle, icon)

    def _setup_ui(self, title: str, subtitle: str, icon: str) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)

        icon_label = QLabel(icon)
        _set_font(icon_label, "h1", "regular")
        icon_label.setStyleSheet(
            f"color: {theme.color('text.muted')};"
        )
        layout.addWidget(icon_label, alignment=Qt.AlignCenter)

        title_label = QLabel(title)
        _set_font(title_label, "bodyLg", "semibold")
        title_label.setStyleSheet(
            f"color: {theme.color('text.primary')};"
        )
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        if subtitle:
            sub_label = QLabel(subtitle)
            _set_font(sub_label, "secondary", "regular")
            sub_label.setStyleSheet(
                f"color: {theme.color('text.secondary')};"
            )
            sub_label.setAlignment(Qt.AlignCenter)
            sub_label.setWordWrap(True)
            layout.addWidget(sub_label)


# ---------------------------------------------------------------------------
# AnimationLayer — удобный слой анимаций
# ---------------------------------------------------------------------------

class AnimationLayer:
    """
    Централизованный слой анимаций.

    Предоставляет методы для создания анимаций с едиными
    длительностями и easing из design tokens.
    """

    @staticmethod
    def fade_in(
        widget: QWidget,
        duration_key: str = "micro",
        on_done: Callable[[], None] | None = None,
    ) -> QPropertyAnimation:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(theme.duration(duration_key))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        if on_done:
            anim.finished.connect(on_done)
        anim.start()
        return anim

    @staticmethod
    def fade_out(
        widget: QWidget,
        duration_key: str = "micro",
        on_done: Callable[[], None] | None = None,
    ) -> QPropertyAnimation:
        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(theme.duration(duration_key))
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        if on_done:
            anim.finished.connect(on_done)
        anim.start()
        return anim

    @staticmethod
    def slide_in(
        widget: QWidget,
        duration_key: str = "panel",
        direction: str = "left",
    ) -> QPropertyAnimation:
        anim = QPropertyAnimation(widget, b"pos")
        anim.setDuration(theme.duration(duration_key))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        return anim


# ---------------------------------------------------------------------------
# ReducedMotionMixin
# ---------------------------------------------------------------------------

class ReducedMotionMixin:
    """
    Миксин для поддержки Reduce Motion.

    При включённом reduce motion:
      - анимации отключаются;
      - переходы заменяются на короткие fade.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._reduced_motion = False

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = enabled

    def maybe_animate(self, anim: QPropertyAnimation) -> None:
        if self._reduced_motion:
            anim.setDuration(0)
        anim.start()
