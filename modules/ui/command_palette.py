# modules/ui/command_palette.py
"""
Command Palette в стиле Raycast.

Поддерживает:
  - fuzzy search;
  - навигацию клавиатурой (↑/↓/Enter/Esc);
  - recent commands;
  - pinned commands;
  - отображение hotkeys;
  - не блокирует текущую активную задачу.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    Qt,
    QTimer,
)
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QFrame,
)

from modules.ui.theme import theme
from modules.ui.primitives import Input, Button, IconButton


class Command:
    """Одна команда в palette."""

    def __init__(
        self,
        name: str,
        *,
        category: str = "General",
        hotkey: str = "",
        icon: str = "•",
        callback: Callable[[], None] | None = None,
    ) -> None:
        self.name = name
        self.category = category
        self.hotkey = hotkey
        self.icon = icon
        self.callback = callback
        self._recent = False
        self._pinned = False


class CommandPalette(QFrame):
    """
    Command palette с fuzzy search.

    Появляется по Ctrl/Cmd + K.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._commands: list[Command] = []
        self._filtered: list[Command] = []
        self._recent_commands: list[str] = []
        self._visible = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Подложка
        self._backdrop = QFrame()
        self._backdrop.setStyleSheet(
            f"background: {theme.color('bg.overlay')};"
        )
        self._layout.addWidget(self._backdrop)

        # Контейнер
        container = QFrame()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # Поле поиска
        self._search = Input(placeholder="Введите команду или > ...")
        self._search.setFixedHeight(36)
        self._search.textChanged.connect(self._on_search_changed)
        container_layout.addWidget(self._search)

        # Список команд
        self._list = QListWidget()
        self._list.setStyleSheet(f"""
            QListWidget {{
                background: {theme.color("bg.surface")};
                border: 1px solid {theme.color("border.subtle")};
                border-radius: {theme.radius("md")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 8px 12px;
                border-bottom: 1px solid {theme.color("border.subtle")};
            }}
            QListWidget::item:selected {{
                background: {theme.color("accent.soft")};
                color: {theme.color("accent.primary")};
            }}
        """)
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._list.itemClicked.connect(self._on_item_clicked)
        container_layout.addWidget(self._list)

        self._layout.addWidget(container)

        # Скрытый palette не должен перехватывать клики —
        # иначе нижележащие виджеты становятся недоступными.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    def _on_search_changed(self, text: str) -> None:
        """Фильтрует команды по вводу (fuzzy search)."""
        self._filtered = self._fuzzy_filter(text)
        self._render_list()

    def _fuzzy_filter(self, query: str) -> list[Command]:
        """Простой fuzzy search по названию команды."""
        if not query:
            return self._commands[:10]

        query_lower = query.lower()
        results: list[Command] = []

        for cmd in self._commands:
            if query_lower in cmd.name.lower():
                results.append(cmd)

        # Сортируем: сначала recent, потом по названию
        results.sort(
            key=lambda c: (
                c.name not in self._recent_commands,
                c.name.lower(),
            )
        )

        return results[:15]

    def _render_list(self) -> None:
        self._list.clear()

        for cmd in self._filtered:
            item = QListWidgetItem()
            widget = self._build_item_widget(cmd)
            item.setSizeHint(widget.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, widget)

        if self._filtered:
            self._list.setCurrentRow(0)

    def _build_item_widget(self, cmd: Command) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        icon_label = QLabel(cmd.icon)
        layout.addWidget(icon_label)

        name_label = QLabel(cmd.name)
        name_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.primary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
            }}
        """)
        layout.addWidget(name_label, stretch=1)

        if cmd.category:
            cat_label = QLabel(cmd.category)
            cat_label.setStyleSheet(f"""
                QLabel {{
                    color: {theme.color("text.muted")};
                    font-family: {theme.font_family()};
                    font-size: {theme.font_size("caption")}px;
                }}
            """)
            layout.addWidget(cat_label)

        if cmd.hotkey:
            hk_label = QLabel(cmd.hotkey)
            hk_label.setStyleSheet(f"""
                QLabel {{
                    color: {theme.color("text.muted")};
                    font-family: {theme.font_family()};
                    font-size: {theme.font_size("caption")}px;
                    background: {theme.color("bg.elevated")};
                    padding: 2px 6px;
                    border-radius: {theme.radius("sm")};
                }}
            """)
            layout.addWidget(hk_label)

        return widget

    def _on_selection_changed(self, current: int, previous: int) -> None:
        pass

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if 0 <= row < len(self._filtered):
            cmd = self._filtered[row]
            self._execute(cmd)

    def _execute(self, cmd: Command) -> None:
        self._recent_commands.insert(0, cmd.name)
        if len(self._recent_commands) > 10:
            self._recent_commands.pop()

        if cmd.callback:
            cmd.callback()

        self.hide_palette()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Return:
            if self._filtered:
                row = self._list.currentRow()
                if 0 <= row < len(self._filtered):
                    self._execute(self._filtered[row])
        elif event.key() == Qt.Key_Escape:
            self.hide_palette()
        elif event.key() == Qt.Key_Up:
            self._move_selection(-1)
        elif event.key() == Qt.Key_Down:
            self._move_selection(1)
        else:
            super().keyPressEvent(event)

    def _move_selection(self, delta: int) -> None:
        new_row = max(
            0,
            min(
                self._list.count() - 1,
                self._list.currentRow() + delta,
            )
        )
        self._list.setCurrentRow(new_row)

    def show_palette(self) -> None:
        self._visible = True
        # Убираем прозрачность для мыши, чтобы palette получал клики.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.show()
        self._search.setFocus()
        self._search.setText("")
        self._on_search_changed("")

    def hide_palette(self) -> None:
        self._visible = False
        # Делаем palette прозрачным для мыши, чтобы клики
        # проходили сквозь него к основному UI.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    def is_visible(self) -> bool:
        return self._visible

    def add_command(self, cmd: Command) -> None:
        self._commands.append(cmd)

    def add_commands(self, commands: list[Command]) -> None:
        self._commands.extend(commands)

    def clear(self) -> None:
        self._commands.clear()
        self._filtered.clear()
        self._list.clear()
