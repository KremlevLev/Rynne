"""Рабочие экраны Nova: процессы, память, интеграции и настройки."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules.ui.primitives import Button, StatusIndicator
from modules.ui.theme import theme


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        child_layout = item.layout()
        if child_layout is not None:
            _clear_layout(child_layout)  # type: ignore[arg-type]


def _value_text(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


class ControlPage(QWidget):
    """Базовый экран со скроллом и единым layout."""

    def __init__(self, empty_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._empty_text = empty_text
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 24)
        root.setSpacing(14)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                width: 8px; background: transparent; margin: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {theme.color("border.strong")};
                border-radius: 4px;
                min-height: 28px;
            }}
            """
        )
        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._content = QVBoxLayout(self._container)
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(10)
        self._content.addStretch()
        scroll.setWidget(self._container)
        root.addWidget(scroll)

    def clear(self) -> None:
        _clear_layout(self._content)

    def show_empty(self, text: str | None = None) -> None:
        self.clear()
        card = QFrame()
        card.setObjectName("emptyCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 26, 20, 26)
        title = QLabel(text or self._empty_text)
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color: {theme.color('text.muted')}; font-size: 13px;"
        )
        layout.addWidget(title)
        card.setStyleSheet(
            f"""
            QFrame#emptyCard {{
                background: {theme.color("bg.surface")};
                border: 1px solid {theme.color("border.subtle")};
                border-radius: {theme.radius("lg")};
            }}
            """
        )
        self._content.addWidget(card)
        self._content.addStretch()

    def add_card(self, card: QWidget) -> None:
        stretch_index = max(0, self._content.count() - 1)
        self._content.insertWidget(stretch_index, card)


class DataCard(QFrame):
    """Плотная карточка сущности с metadata и actions."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        status: str = "idle",
        details: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dataCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        indicator = StatusIndicator(status, size=9)
        layout.addWidget(indicator, alignment=Qt.AlignTop)

        content = QVBoxLayout()
        content.setSpacing(4)
        name = QLabel(title)
        name.setWordWrap(True)
        name.setStyleSheet(
            f"color: {theme.color('text.primary')}; font-size: 14px; font-weight: 620;"
        )
        content.addWidget(name)
        if subtitle:
            meta = QLabel(subtitle)
            meta.setWordWrap(True)
            meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
            meta.setStyleSheet(
                f"color: {theme.color('text.secondary')}; font-size: 12px;"
            )
            content.addWidget(meta)
        for detail in details or []:
            label = QLabel(detail)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setStyleSheet(
                f"color: {theme.color('text.muted')}; font-size: 11px;"
            )
            content.addWidget(label)
        layout.addLayout(content, stretch=1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        layout.addLayout(self.actions)
        self.setStyleSheet(
            f"""
            QFrame#dataCard {{
                background: {theme.color("bg.surface")};
                border: 1px solid {theme.color("border.subtle")};
                border-radius: {theme.radius("lg")};
            }}
            QFrame#dataCard:hover {{
                background: {theme.color("bg.surfaceHover")};
                border-color: {theme.color("border.strong")};
            }}
            """
        )

    def add_action(
        self,
        label: str,
        callback,
        *,
        variant: str = "secondary",
    ) -> Button:
        button = Button(label, variant=variant, size="sm")
        button.clicked.connect(callback)
        self.actions.addWidget(button)
        return button


class ProcessesPage(ControlPage):
    stop_requested = Signal(str, bool)
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Нет процессов, запущенных Nova.", parent)
        self.show_empty()

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self.clear()
        if not items:
            self.show_empty()
            return
        for process in items:
            process_id = str(process.get("process_id", ""))
            running = bool(process.get("is_running"))
            command = _value_text(process.get("command"))
            card = DataCard(
                str(process.get("label") or process_id or "Процесс"),
                f"PID {process.get('pid', '—')} · {process.get('status', 'unknown')}",
                status="active" if running else "offline",
                details=[command] if command else None,
            )
            if running and process_id:
                card.add_action(
                    "Остановить",
                    lambda checked=False, pid=process_id: self.stop_requested.emit(
                        pid, False
                    ),
                    variant="ghost",
                )
            self.add_card(card)
        self._content.addStretch()


class MemoryPage(ControlPage):
    delete_requested = Signal(str)
    clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Долговременная память пока пуста.", parent)
        self.show_empty()

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self.clear()
        if not items:
            self.show_empty()
            return

        actions = QHBoxLayout()
        actions.addStretch()
        clear = Button("Очистить память", variant="ghost", size="sm")
        clear.clicked.connect(self.clear_requested.emit)
        actions.addWidget(clear)
        wrapper = QWidget()
        wrapper.setLayout(actions)
        self._content.addWidget(wrapper)

        for memory in items:
            key = str(memory.get("key", ""))
            card = DataCard(
                key or "Факт",
                str(memory.get("value", "")),
                status="idle",
                details=[
                    f"{memory.get('category', 'general')} · "
                    f"источник: {memory.get('source', 'unknown')}"
                ],
            )
            if key:
                card.add_action(
                    "Удалить",
                    lambda checked=False, item_key=key: self.delete_requested.emit(
                        item_key
                    ),
                    variant="ghost",
                )
            self.add_card(card)
        self._content.addStretch()


class IntegrationsPage(ControlPage):
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("MCP-серверы не настроены или ещё подключаются.", parent)
        self.show_empty()

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self.clear()
        if not items:
            self.show_empty()
            return
        for server in items:
            tools_count = int(server.get("tools_count", 0) or 0)
            enabled = bool(server.get("enabled", True))
            connected = tools_count > 0
            transport = str(server.get("transport", "stdio"))
            status_label = (
                f"Подключено · {tools_count} tools"
                if connected
                else ("Настроено · нет доступных tools" if enabled else "Отключено")
            )
            card = DataCard(
                f"{server.get('name', 'MCP')} MCP",
                status_label,
                status="success" if connected else ("warning" if enabled else "offline"),
                details=[f"Транспорт: {transport}"],
            )
            self.add_card(card)
        self._content.addStretch()


class SettingsPage(ControlPage):
    preference_changed = Signal(str, object)

    PROFILE_ITEMS = (
        ("Обычный помощник", "assistant"),
        ("Безопасный", "safe"),
        ("Инженер", "engineer"),
        ("Автономная задача", "autonomous_task"),
        ("Только локально", "private_local"),
    )
    MODEL_ITEMS = (
        ("Автоматически", "auto"),
        ("Быстро", "fast"),
        ("Умно", "smart"),
        ("Код", "coding"),
        ("Vision", "vision"),
        ("Только бесплатно", "free_only"),
        ("Только локально", "local_only"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Настройки недоступны.", parent)
        self._updating = False
        self._build()

    def _build(self) -> None:
        self.clear()
        card = QFrame()
        card.setObjectName("settingsCard")
        form = QVBoxLayout(card)
        form.setContentsMargins(18, 18, 18, 18)
        form.setSpacing(16)

        heading = QLabel("Поведение агента")
        heading.setStyleSheet(
            f"color: {theme.color('text.primary')}; font-size: 16px; font-weight: 650;"
        )
        form.addWidget(heading)

        self._profile = self._combo_row(
            form,
            "Профиль",
            "Определяет допустимую автономность и специализацию.",
            self.PROFILE_ITEMS,
            lambda value: self._emit("assistant_profile", value),
        )
        self._model = self._combo_row(
            form,
            "Режим модели",
            "Nova сохраняет fallback chain и выбирает модель по задаче.",
            self.MODEL_ITEMS,
            lambda value: self._emit("model_mode", value),
        )
        self._tts = self._toggle_row(
            form,
            "Озвучивать ответы",
            "Воспроизводить speech-версию ответа через TTS.",
            lambda checked: self._emit("tts_enabled", checked),
        )
        self._cloud = self._toggle_row(
            form,
            "Разрешить облачные модели",
            "Отключается автоматически в приватном режиме.",
            lambda checked: self._emit("cloud_enabled", checked),
        )
        self._history = self._toggle_row(
            form,
            "Сохранять историю",
            "Хранить контекст сессий локально.",
            lambda checked: self._emit("history_enabled", checked),
        )
        self._proactive_vision = self._toggle_row(
            form,
            "Nova рядом",
            (
                "Иногда отправлять снимок только активного окна "
                "в облачную vision-модель, чтобы Nova могла заметить проблему "
                "и предложить помощь. Выключено по умолчанию."
            ),
            lambda checked: self._emit(
                "proactive_vision_enabled",
                checked,
            ),
        )
        card.setStyleSheet(
            f"""
            QFrame#settingsCard {{
                background: {theme.color("bg.surface")};
                border: 1px solid {theme.color("border.subtle")};
                border-radius: {theme.radius("lg")};
            }}
            QComboBox {{
                background: {theme.color("bg.input")};
                color: {theme.color("text.primary")};
                border: 1px solid {theme.color("border.strong")};
                border-radius: {theme.radius("sm")};
                padding: 7px 10px;
                min-width: 190px;
            }}
            QComboBox:focus {{ border-color: {theme.color("border.active")}; }}
            QCheckBox {{ color: {theme.color("text.primary")}; }}
            """
        )
        self._content.addWidget(card)
        self._content.addStretch()

    def _combo_row(
        self,
        layout: QVBoxLayout,
        title: str,
        description: str,
        items: tuple[tuple[str, str], ...],
        callback,
    ) -> QComboBox:
        row = QHBoxLayout()
        text = QVBoxLayout()
        name = QLabel(title)
        name.setStyleSheet(
            f"color: {theme.color('text.primary')}; font-size: 13px; font-weight: 600;"
        )
        detail = QLabel(description)
        detail.setWordWrap(True)
        detail.setStyleSheet(
            f"color: {theme.color('text.muted')}; font-size: 11px;"
        )
        text.addWidget(name)
        text.addWidget(detail)
        row.addLayout(text, stretch=1)
        combo = QComboBox()
        for label, value in items:
            combo.addItem(label, value)
        combo.currentIndexChanged.connect(
            lambda index: callback(combo.itemData(index))
        )
        row.addWidget(combo)
        layout.addLayout(row)
        return combo

    def _toggle_row(
        self,
        layout: QVBoxLayout,
        title: str,
        description: str,
        callback,
    ) -> QCheckBox:
        row = QHBoxLayout()
        text = QVBoxLayout()
        name = QLabel(title)
        name.setStyleSheet(
            f"color: {theme.color('text.primary')}; font-size: 13px; font-weight: 600;"
        )
        detail = QLabel(description)
        detail.setWordWrap(True)
        detail.setStyleSheet(
            f"color: {theme.color('text.muted')}; font-size: 11px;"
        )
        text.addWidget(name)
        text.addWidget(detail)
        row.addLayout(text, stretch=1)
        checkbox = QCheckBox()
        checkbox.toggled.connect(callback)
        row.addWidget(checkbox)
        layout.addLayout(row)
        return checkbox

    def _emit(self, key: str, value: Any) -> None:
        if not self._updating:
            self.preference_changed.emit(key, value)

    def set_preferences(self, preferences: dict[str, Any]) -> None:
        self._updating = True
        try:
            self._select_data(
                self._profile, str(preferences.get("assistant_profile", "assistant"))
            )
            self._select_data(
                self._model, str(preferences.get("model_mode", "auto"))
            )
            self._tts.setChecked(bool(preferences.get("tts_enabled", True)))
            self._cloud.setChecked(bool(preferences.get("cloud_enabled", True)))
            self._history.setChecked(bool(preferences.get("history_enabled", True)))
            self._proactive_vision.setChecked(
                bool(
                    preferences.get(
                        "proactive_vision_enabled",
                        False,
                    )
                )
            )
        finally:
            self._updating = False

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
