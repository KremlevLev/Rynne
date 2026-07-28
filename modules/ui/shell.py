# modules/ui/shell.py
"""Основной shell нового Nova Desktop UI.

Shell отвечает только за presentation layer: навигацию, раскладку,
статус и правую панель контекста. Команды backend он не исполняет.
"""
from __future__ import annotations


from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from modules.ui.primitives import Button, IconButton, StatusIndicator
from modules.ui.theme import theme


NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("chat", "Диалог", "⌁"),
    ("tasks", "Задачи", "✓"),
    ("processes", "Процессы", "▣"),
    ("memory", "Память", "◇"),
    ("integrations", "Интеграции", "↗"),
    ("settings", "Настройки", "⚙"),
)


class SidebarItem(QPushButton):
    """Настоящая кнопка навигации, кликабельная по всей площади."""

    def __init__(
        self,
        label: str,
        icon: str = "•",
        *,
        key: str | None = None,
        active: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._label = label
        self._icon = icon
        self._key = key or label.lower()
        self._active = active
        self._collapsed = False
        self._badge_text = ""
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setCheckable(True)
        self.setChecked(active)
        self.setMinimumHeight(42)
        self.setFocusPolicy(Qt.StrongFocus)
        self._update_content()
        self._update_style()

    def _update_content(self) -> None:
        if self._collapsed:
            self.setText(self._icon)
            self.setToolTip(self._label)
        else:
            suffix = f"   {self._badge_text}" if self._badge_text else ""
            self.setText(f"{self._icon}   {self._label}{suffix}")
            self.setToolTip("")

    def _update_style(self) -> None:
        self.setStyleSheet(
            f"""
            SidebarItem {{
                background: {"#211e3a" if self._active else "transparent"};
                color: {theme.color("text.primary") if self._active else theme.color("text.secondary")};
                border: 1px solid {"#3a3267" if self._active else "transparent"};
                border-radius: {theme.radius("md")};
                padding: 8px 12px;
                text-align: {"center" if self._collapsed else "left"};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("bodySm")}px;
                font-weight: {theme.font_weight("medium")};
            }}
            SidebarItem:hover {{
                background: {theme.color("bg.surfaceHover")};
                color: {theme.color("text.primary")};
                border-color: {theme.color("border.subtle")};
            }}
            SidebarItem:pressed {{
                background: {theme.color("accent.soft")};
            }}
            SidebarItem:focus {{
                border-color: {theme.color("border.active")};
            }}
            """
        )

    def set_active(self, active: bool) -> None:
        self._active = active
        self.setChecked(active)
        self._update_style()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._update_content()
        self._update_style()

    def set_badge(self, text: str, status: str = "neutral") -> None:
        del status
        self._badge_text = text
        self._update_content()


class Sidebar(QWidget):
    """Компактная навигация приложения."""

    navigate = Signal(str)
    new_task_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collapsed = False
        self._items: list[SidebarItem] = []
        self._items_by_key: dict[str, SidebarItem] = {}
        self._current_item: SidebarItem | None = None
        self._animations: list[QPropertyAnimation] = []
        self.setMinimumWidth(236)
        self.setMaximumWidth(236)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(6)
        self._layout = layout

        header = QHBoxLayout()
        header.setContentsMargins(6, 2, 2, 8)
        header.setSpacing(10)

        mark = QLabel("N")
        mark.setObjectName("novaMark")
        mark.setFixedSize(34, 34)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(
            f"""
            QLabel#novaMark {{
                color: white;
                background: {theme.color("accent.primary")};
                border-radius: 11px;
                font-family: {theme.font_family()};
                font-size: 17px;
                font-weight: 700;
            }}
            """
        )
        header.addWidget(mark)

        self._brand = QWidget()
        brand_layout = QVBoxLayout(self._brand)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(0)
        name = QLabel("Nova")
        name.setStyleSheet(
            f"color: {theme.color('text.primary')}; font-size: 16px; font-weight: 650;"
        )
        subtitle = QLabel("OS agent")
        subtitle.setStyleSheet(
            f"color: {theme.color('text.muted')}; font-size: 11px;"
        )
        brand_layout.addWidget(name)
        brand_layout.addWidget(subtitle)
        header.addWidget(self._brand, stretch=1)

        self._collapse_btn = IconButton("‹", tooltip="Свернуть панель", size="sm")
        self._collapse_btn.clicked.connect(self._toggle_collapsed)
        header.addWidget(self._collapse_btn)
        layout.addLayout(header)

        new_task = Button("＋  Новая задача", variant="primary", size="md")
        new_task.setMinimumHeight(40)
        new_task.clicked.connect(self.new_task_requested.emit)
        self._new_task_button = new_task
        layout.addWidget(new_task)
        layout.addSpacing(8)

        section = QLabel("РАБОЧАЯ ОБЛАСТЬ")
        section.setStyleSheet(
            f"color: {theme.color('text.muted')}; font-size: 10px; "
            "font-weight: 650; padding: 2px 8px;"
        )
        self._section_label = section
        layout.addWidget(section)

        for key, label, icon in NAV_ITEMS:
            item = SidebarItem(
                label,
                icon,
                key=key,
                active=(key == "chat"),
            )
            item.clicked.connect(
                lambda checked=False, selected=item: self._on_item_clicked(selected)
            )
            layout.addWidget(item)
            self._items.append(item)
            self._items_by_key[key] = item
            if key == "chat":
                self._current_item = item

        layout.addStretch(1)

        self._footer = QFrame()
        self._footer.setObjectName("sidebarFooter")
        footer_layout = QVBoxLayout(self._footer)
        footer_layout.setContentsMargins(10, 10, 10, 10)
        footer_layout.setSpacing(5)

        status_row = QHBoxLayout()
        self._status_indicator = StatusIndicator("idle", size=8)
        status_row.addWidget(self._status_indicator)
        self._status_label = QLabel("Подключение…")
        self._status_label.setStyleSheet(
            f"color: {theme.color('text.secondary')}; font-size: 12px;"
        )
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        footer_layout.addLayout(status_row)

        self._model_label = QLabel("Модель: auto")
        self._model_label.setWordWrap(True)
        self._model_label.setStyleSheet(
            f"color: {theme.color('text.muted')}; font-size: 11px;"
        )
        footer_layout.addWidget(self._model_label)
        layout.addWidget(self._footer)

        self.setStyleSheet(
            f"""
            QWidget#sidebar {{
                background: {theme.color("bg.elevated")};
                border-right: 1px solid {theme.color("border.subtle")};
            }}
            QFrame#sidebarFooter {{
                background: {theme.color("bg.surface")};
                border: 1px solid {theme.color("border.subtle")};
                border-radius: {theme.radius("md")};
            }}
            """
        )

    def _on_item_clicked(self, item: SidebarItem) -> None:
        if self._current_item is not None and self._current_item is not item:
            self._current_item.set_active(False)
        item.set_active(True)
        self._current_item = item
        self.navigate.emit(item._key)

    def activate(self, key: str) -> None:
        item = self._items_by_key.get(key)
        if item is not None:
            self._on_item_clicked(item)

    def _toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        target = 72 if self._collapsed else 236

        for item in self._items:
            item.set_collapsed(self._collapsed)
        self._brand.setVisible(not self._collapsed)
        self._section_label.setVisible(not self._collapsed)
        self._footer.setVisible(not self._collapsed)
        self._new_task_button.setText("＋" if self._collapsed else "＋  Новая задача")
        self._new_task_button.setToolTip(
            "Новая задача" if self._collapsed else ""
        )
        self._collapse_btn.setText("›" if self._collapsed else "‹")

        self._animations.clear()
        for prop in (b"minimumWidth", b"maximumWidth"):
            animation = QPropertyAnimation(self, prop, self)
            animation.setDuration(theme.duration("panel"))
            animation.setStartValue(self.width())
            animation.setEndValue(target)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            animation.start()
            self._animations.append(animation)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_status(self, status: str, label: str = "") -> None:
        self._status_indicator.set_status(status)
        if label:
            self._status_label.setText(label)

    def set_model(self, model_name: str) -> None:
        clean = model_name.strip(" :") or "auto"
        self._model_label.setText(f"Модель: {clean}")

    def set_badge(self, key: str, text: str) -> None:
        item = self._items_by_key.get(key)
        if item is not None:
            item.set_badge(text)


class ContextPanel(QWidget):
    """Правая панель текущей задачи и активности."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._visible = False
        self._animation: QPropertyAnimation | None = None
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("contextPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        eyebrow = QLabel("КОНТЕКСТ")
        eyebrow.setStyleSheet(
            f"color: {theme.color('text.muted')}; font-size: 10px; font-weight: 650;"
        )
        self._title = QLabel("Текущая задача")
        self._title.setStyleSheet(
            f"color: {theme.color('text.primary')}; font-size: 16px; font-weight: 650;"
        )
        title_box.addWidget(eyebrow)
        title_box.addWidget(self._title)
        header.addLayout(title_box)
        header.addStretch()
        close = IconButton("×", tooltip="Закрыть контекст", size="sm")
        close.clicked.connect(self.hide_panel)
        header.addWidget(close)
        layout.addLayout(header)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(10)
        self._empty = QLabel(
            "Здесь появятся план, инструменты и результаты активной задачи."
        )
        self._empty.setWordWrap(True)
        self._empty.setStyleSheet(
            f"color: {theme.color('text.muted')}; font-size: 13px; "
            f"background: {theme.color('bg.surface')}; "
            f"border: 1px solid {theme.color('border.subtle')}; "
            f"border-radius: {theme.radius('md')}; padding: 14px;"
        )
        self._content_layout.addWidget(self._empty)
        self._content_layout.addStretch()
        layout.addWidget(self._content, stretch=1)

        self.setStyleSheet(
            f"""
            QWidget#contextPanel {{
                background: {theme.color("bg.elevated")};
                border-left: 1px solid {theme.color("border.subtle")};
            }}
            """
        )

    def _animate_width(self, target: int) -> None:
        self._animation = QPropertyAnimation(self, b"maximumWidth", self)
        self._animation.setDuration(theme.duration("panel"))
        self._animation.setStartValue(self.maximumWidth())
        self._animation.setEndValue(target)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.start()

    def show_panel(self) -> None:
        self._visible = True
        self.setMinimumWidth(0)
        self._animate_width(310)

    def hide_panel(self) -> None:
        self._visible = False
        self._animate_width(0)

    def is_visible(self) -> bool:
        return self._visible

    def clear(self) -> None:
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._empty:
                widget.deleteLater()
        self._empty.show()

    def set_content(self, widget: QWidget) -> None:
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            old = item.widget()
            if old is not None:
                old.deleteLater()
        self._empty.hide()
        self._content_layout.insertWidget(0, widget)

    def set_title(self, title: str) -> None:
        self._title.setText(title)


class AppShell(QMainWindow):
    """Трёхзонный shell: навигация, workspace и task context."""

    navigate = Signal(str)
    new_task_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._screens: dict[str, QWidget] = {}
        self._screen_titles: dict[str, tuple[str, str]] = {}
        self._setup_ui()
        self._apply_window_style()

    def _setup_ui(self) -> None:
        self._central = QWidget()
        self.setCentralWidget(self._central)
        self.overlay_layout = QStackedLayout(self._central)
        self.overlay_layout.setStackingMode(QStackedLayout.StackAll)

        self._bg_widget = QWidget()
        self._bg_widget.setObjectName("appBackground")
        self._bg_widget.setAttribute(Qt.WA_StyledBackground, True)
        main = QHBoxLayout(self._bg_widget)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        self._main_layout = main

        self.sidebar = Sidebar(self._bg_widget)
        self.sidebar.navigate.connect(self._on_sidebar_navigate)
        self.sidebar.new_task_requested.connect(self.new_task_requested.emit)
        main.addWidget(self.sidebar)

        self._center_container = QWidget()
        self._center_container.setObjectName("centerContainer")
        center = QVBoxLayout(self._center_container)
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)
        self._center_layout = center

        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(24, 15, 18, 15)
        topbar_layout.setSpacing(12)
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        self._page_title = QLabel("Диалог")
        self._page_title.setStyleSheet(
            f"color: {theme.color('text.primary')}; font-size: 17px; font-weight: 650;"
        )
        self._page_subtitle = QLabel("Рабочая сессия Nova")
        self._page_subtitle.setStyleSheet(
            f"color: {theme.color('text.muted')}; font-size: 11px;"
        )
        title_box.addWidget(self._page_title)
        title_box.addWidget(self._page_subtitle)
        topbar_layout.addLayout(title_box)
        topbar_layout.addStretch()

        self._context_button = Button("Контекст", variant="secondary", size="sm")
        self._context_button.clicked.connect(self._toggle_context)
        topbar_layout.addWidget(self._context_button)
        center.addWidget(topbar)

        self.workspace = QStackedWidget()
        self.workspace.setObjectName("workspace")
        center.addWidget(self.workspace, stretch=1)
        main.addWidget(self._center_container, stretch=1)

        self.context_panel = ContextPanel(self._bg_widget)
        main.addWidget(self.context_panel)
        self.overlay_layout.addWidget(self._bg_widget)

        self.resize(1320, 820)
        self.setMinimumSize(980, 640)
        self.setWindowTitle("Nova · OS Agent")

    def _apply_window_style(self) -> None:
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget#appBackground, QWidget#centerContainer,
            QStackedWidget#workspace {{
                background: {theme.color("bg.base")};
                color: {theme.color("text.primary")};
                font-family: {theme.font_family()};
            }}
            QFrame#topbar {{
                background: {theme.color("bg.base")};
                border-bottom: 1px solid {theme.color("border.subtle")};
            }}
            QLabel {{
                font-family: {theme.font_family()};
            }}
            QToolTip {{
                background: {theme.color("bg.surfaceHover")};
                color: {theme.color("text.primary")};
                border: 1px solid {theme.color("border.strong")};
                border-radius: 6px;
                padding: 6px 8px;
            }}
            """
        )

    def add_workspace_screen(
        self,
        name: str,
        widget: QWidget,
        *,
        title: str | None = None,
        subtitle: str = "",
    ) -> None:
        self._screens[name] = widget
        self._screen_titles[name] = (title or name.title(), subtitle)
        self.workspace.addWidget(widget)

    def set_workspace_screen(self, index: int) -> None:
        self.workspace.setCurrentIndex(index)

    def show_screen(self, name: str) -> bool:
        widget = self._screens.get(name)
        if widget is None:
            return False
        self.workspace.setCurrentWidget(widget)
        title, subtitle = self._screen_titles.get(name, (name.title(), ""))
        self._page_title.setText(title)
        self._page_subtitle.setText(subtitle)
        return True

    def _on_sidebar_navigate(self, item_or_key: SidebarItem | str) -> None:
        key = (
            item_or_key._key
            if isinstance(item_or_key, SidebarItem)
            else str(item_or_key)
        )
        self.show_screen(key)
        self.navigate.emit(key)

    def _toggle_context(self) -> None:
        if self.context_panel.is_visible():
            self.context_panel.hide_panel()
        else:
            self.context_panel.show_panel()

    def set_context_widget(self, title: str, widget: QWidget) -> None:
        self.context_panel.set_title(title)
        self.context_panel.set_content(widget)
        self.context_panel.show_panel()

    def set_status(self, status: str, label: str = "") -> None:
        self.sidebar.set_status(status, label)

    def set_model(self, model_name: str) -> None:
        self.sidebar.set_model(model_name)

    def set_badge(self, key: str, value: int | str | None) -> None:
        text = "" if value in (None, 0, "0", "") else str(value)
        self.sidebar.set_badge(key, text)
