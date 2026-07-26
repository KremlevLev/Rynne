# modules/ui/shell.py
"""
AppShell — основной шаблон Nova Desktop UI.

Содержит трёхзонный layout:
  ┌──────────────┬───────────────────────────────┬────────────────────┐
  │ Sidebar      │ Main workspace                  │ Context / Activity │
  │              │                                 │                    │
  │ Nova         │ Chat / task result / artifacts  │ Current task       │
  │ Chats        │                                 │ Plan / tools       │
  │ Workspaces   │                                 │ Sources / files    │
  │ Skills       │                                 │                    │
  │ Automations  │                                 │                    │
  │ Memory       │                                 │                    │
  │ Settings     │                                 │                    │
  └──────────────┴─────────────────────────────────┴────────────────────┘

Sidebar сворачивается до icon-only режима с tooltip-ами.
Context panel открывается/закрывается плавно.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    Qt,
    Signal,
    QPropertyAnimation,
    QEasingCurve,
    QTimer,
    QSize,
)
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QSplitter,
    QStackedWidget,
    QScrollArea,
    QFrame,
    QLabel,
    QSpacerItem,
    QSizePolicy,
    QMainWindow,
)

from modules.ui.theme import theme
from modules.ui.primitives import (
    Button,
    IconButton,
    Card,
    Badge,
    StatusIndicator,
    Tooltip,
    AnimationLayer,
    EmptyState,
)


class SidebarItem(QWidget):
    """Один пункт в боковой панели."""

    clicked = Signal()

    def __init__(
        self,
        label: str,
        icon: str = "●",
        *,
        active: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._label = label
        self._icon = icon
        self._active = active
        self._collapsed = False
        self._setup_ui()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)

    def _setup_ui(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(12, 8, 12, 8)
        self._layout.setSpacing(12)

        self._icon_label = QLabel(self._icon)
        self._icon_label.setFixedSize(20, 20)
        self._icon_label.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self._icon_label)

        self._text_label = QLabel(self._label)
        self._layout.addWidget(self._text_label)

        self._layout.addStretch()

        self._badge: Badge | None = None
        self._update_style()

    def _update_style(self) -> None:
        bg = (
            theme.color("accent.soft")
            if self._active
            else "transparent"
        )
        text_color = (
            theme.color("accent.primary")
            if self._active
            else theme.color("text.primary")
        )
        radius = theme.radius("md")

        self.setStyleSheet(f"""
            SidebarItem {{
                background: {bg};
                border-radius: {radius};
                border-bottom: 1px solid {theme.color("border.subtle")};
                padding: 0;
            }}
            SidebarItem:hover {{
                background: {theme.color("accent.soft")};
            }}
        """)

        self._text_label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
                font-weight: {theme.font_weight("medium")};
            }}
        """)

        self._icon_label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
            }}
        """)

    def set_active(self, active: bool) -> None:
        self._active = active
        self._update_style()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        if collapsed:
            self._text_label.hide()
            self._icon_label.setAlignment(Qt.AlignCenter)
            self.setToolTip(self._label)
        else:
            self._text_label.show()
            self.setToolTip("")
        self._layout.update()

    def set_badge(self, text: str, status: str = "neutral") -> None:
        if self._badge is None:
            self._badge = Badge(text, status=status)
            self._layout.addWidget(self._badge)
        else:
            self._badge.setText(text)
            self._badge.set_status(status)


class Sidebar(QWidget):
    """Боковая панель с навигацией."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collapsed = False
        self._items: list[SidebarItem] = []
        self._current_item: SidebarItem | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 12, 8, 12)
        self._layout.setSpacing(4)

        # Header: логотип + статус
        self._header = QHBoxLayout()
        self._header.setContentsMargins(12, 8, 12, 8)

        self._logo = QLabel("Nova")
        self._logo.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("accent.primary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("h1")}px;
                font-weight: {theme.font_weight("bold")};
            }}
        """)
        self._header.addWidget(self._logo)

        self._collapse_btn = IconButton(
            "⟨", tooltip="Свернуть панель", size="sm"
        )
        self._collapse_btn.clicked.connect(self._toggle_collapsed)
        self._header.addWidget(self._collapse_btn, alignment=Qt.AlignRight)

        self._layout.addLayout(self._header)

        # Навигационные пункты
        self._nav_container = QVBoxLayout()
        self._nav_container.setSpacing(2)
        self._layout.addLayout(self._nav_container)

        self._add_nav_item("Новая задача", "✚", active=True)
        self._add_nav_item("Чаты", "💬")
        self._add_nav_item("Рабочие пространства", "📁")
        self._add_nav_item("Навыки", "⚡")
        self._add_nav_item("Автоматизации", "🔄")
        self._add_nav_item("Память", "🧠")
        self._add_nav_item("Настройки", "⚙")

        self._layout.addStretch()

        # Нижняя зона: статус модели и сети
        self._status_bar = QHBoxLayout()
        self._status_bar.setContentsMargins(12, 12, 12, 12)

        self._status_indicator = StatusIndicator("idle")
        self._status_bar.addWidget(self._status_indicator)

        self._status_label = QLabel("Готова")
        self._status_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.secondary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("secondary")}px;
            }}
        """)
        self._status_bar.addWidget(self._status_label)

        self._status_bar.addStretch()

        self._model_label = QLabel("Gemini Flash")
        self._model_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.muted")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("caption")}px;
            }}
        """)
        self._status_bar.addWidget(self._model_label)

        self._layout.addLayout(self._status_bar)

        self.setStyleSheet(f"""
            Sidebar {{
                background: {theme.color("bg.elevated")};
                border-right: 1px solid {theme.color("border.subtle")};
            }}
        """)

    def _add_nav_item(
        self, label: str, icon: str, *, active: bool = False
    ) -> SidebarItem:
        item = SidebarItem(label, icon, active=active)
        item.clicked.connect(lambda: self._on_item_clicked(item))
        self._nav_container.addWidget(item)
        self._items.append(item)
        return item

    def _on_item_clicked(self, item: SidebarItem) -> None:
        if self._current_item:
            self._current_item.set_active(False)
        item.set_active(True)
        self._current_item = item

        # TODO: переключить центральный контент
        if hasattr(self.parent(), "_on_sidebar_navigate"):
            self.parent()._on_sidebar_navigate(item)

    def _toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        for item in self._items:
            item.set_collapsed(self._collapsed)

        if self._collapsed:
            self._logo.setText("N")
            self._collapse_btn.setText("⟩")
            target_width = 60
        else:
            self._logo.setText("Nova")
            self._collapse_btn.setText("⟨")
            target_width = 280

        # Плавное изменение ширины
        duration = theme.duration("panel")
        anim = QPropertyAnimation(self, b"minimumWidth")
        anim.setDuration(duration)
        anim.setStartValue(self.minimumWidth())
        anim.setEndValue(target_width)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

        # Также анимируем maximumWidth для корректного ресайза
        anim_max = QPropertyAnimation(self, b"maximumWidth")
        anim_max.setDuration(duration)
        anim_max.setStartValue(self.maximumWidth())
        anim_max.setEndValue(target_width)
        anim_max.setEasingCurve(QEasingCurve.OutCubic)
        anim_max.start()

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_status(self, status: str, label: str = "") -> None:
        self._status_indicator.set_status(status)
        if label:
            self._status_label.setText(label)

    def set_model(self, model_name: str) -> None:
        self._model_label.setText(model_name)


class ContextPanel(QWidget):
    """Правая панель контекста / активности."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._visible = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Заголовок панели
        self._header = QHBoxLayout()
        self._header.setContentsMargins(16, 12, 16, 8)

        self._title = QLabel("Контекст задачи")
        self._title.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.secondary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("caption")}px;
                font-weight: {theme.font_weight("medium")};
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
        """)
        self._header.addWidget(self._title)

        self._header.addStretch()

        self._close_btn = IconButton("✕", tooltip="Закрыть панель", size="sm")
        self._close_btn.clicked.connect(self.hide_panel)
        self._header.addWidget(self._close_btn)

        self._layout.addLayout(self._header)

        # Содержимое
        self._content = Card(padding=16)
        self._content_layout = QVBoxLayout()
        self._content.layout().addLayout(self._content_layout)
        self._layout.addWidget(self._content, stretch=1)

        self._empty = EmptyState(
            "Нет активной задачи",
            "Выберите задачу или отправьте запрос.",
            icon="◉",
        )
        self._content_layout.addWidget(self._empty)

        self.setStyleSheet(f"""
            ContextPanel {{
                background: {theme.color("bg.elevated")};
                border-left: 1px solid {theme.color("border.subtle")};
            }}
        """)

        self.hide()

    def show_panel(self) -> None:
        self._visible = True
        self.show()
        AnimationLayer.fade_in(self, "panel")

    def hide_panel(self) -> None:
        self._visible = False
        AnimationLayer.fade_out(self, "panel", on_done=self.hide)

    def is_visible(self) -> bool:
        return self._visible

    def set_content(self, widget: QWidget) -> None:
        # Очищаем содержимое
        while self._content_layout.count():
            child = self._content_layout.takeAt(0)
            if child.widget():
                child.widget().hide()
        self._content_layout.addWidget(widget)

    def set_title(self, title: str) -> None:
        self._title.setText(title)


class AppShell(QMainWindow):
    """
    Главный шаблон приложения.

    Трёхзонный layout: Sidebar | Main workspace | Context panel.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._apply_window_style()

    def _setup_ui(self) -> None:
        # Главный контейнер
        self._central = QWidget()
        self.setCentralWidget(self._central)

        # Создаём слой для наложения виджетов друг на друга
        from PySide6.QtWidgets import QStackedLayout
        self.overlay_layout = QStackedLayout(self._central)
        self.overlay_layout.setStackingMode(QStackedLayout.StackAll)

        # Основной UI оборачиваем в контейнер
        self._bg_widget = QWidget()
        self._bg_widget.setAttribute(Qt.WA_StyledBackground, True)
        self._main_layout = QHBoxLayout(self._bg_widget)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar()
        self._main_layout.addWidget(self.sidebar)

        # Центральная зона
        self._center_container = QWidget()
        self._center_layout = QVBoxLayout(self._center_container)
        self._center_layout.setContentsMargins(0, 0, 0, 0)
        self._center_layout.setSpacing(0)

        # Workspace (стек экранов)
        self.workspace = QStackedWidget()
        self._center_layout.addWidget(self.workspace)

        self._main_layout.addWidget(self._center_container, stretch=1)

        # Context panel
        self.context_panel = ContextPanel()
        self._main_layout.addWidget(self.context_panel)

        # Добавляем _bg_widget в overlay_layout ПЕРВЫМ (задний фон)
        self.overlay_layout.addWidget(self._bg_widget)

        # Состояние окна
        self.resize(1200, 780)
        self.setWindowTitle("Nova")

    def _apply_window_style(self) -> None:
        self.setStyleSheet(f"""
            QMainWindow {{
                background: {theme.color("bg.base")};
                color: {theme.color("text.primary")};
                font-family: {theme.font_family()};
            }}
        """)

    def add_workspace_screen(self, name: str, widget: QWidget) -> None:
        """Добавляет экран в workspace."""
        self.workspace.addWidget(widget)

    def set_workspace_screen(self, index: int) -> None:
        """Переключает текущий экран."""
        self.workspace.setCurrentIndex(index)

    def _on_sidebar_navigate(self, item: SidebarItem) -> None:
        """Обработчик навигации по боковой панели."""
        index = self.sidebar._items.index(item)
        # Workspace имеет только 2 экрана (chat=0, task=1)
        # Остальные пункты показывают context panel или выводят сообщение
        if index == 0:
            # Новая задача / Чат
            self.workspace.setCurrentWidget(
                self.workspace.widget(0)
            )
            self.context_panel.hide_panel()
        elif index == 1:
            # Чаты - тот же экран чата
            self.workspace.setCurrentWidget(
                self.workspace.widget(0)
            )
            self.context_panel.hide_panel()
        else:
            # Остальные пункты: показываем context panel
            self.context_panel.show_panel()
            self.context_panel.set_title(
                f"Раздел: {item._label}"
            )
            # Переключаемся на чат, но показываем панель
            self.workspace.setCurrentWidget(
                self.workspace.widget(0)
            )

    def set_status(self, status: str, label: str = "") -> None:
        self.sidebar.set_status(status, label)

    def set_model(self, model_name: str) -> None:
        self.sidebar.set_model(model_name)
