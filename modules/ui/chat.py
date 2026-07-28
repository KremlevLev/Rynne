# modules/ui/chat.py
"""
Chat UI и Composer для Nova Desktop UI.

Содержит:
  - ChatMessage       — структурированное сообщение (user или assistant)
  - ChatView          — прокручиваемый список сообщений
  - Composer          — поле ввода с voice, attachments, model selector
  - ToolActivityCard  — компактная карточка tool call
  - ErrorCard         — карточка ошибки с retry
  - ArtifactCard      — карточка артефакта
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QTextEdit,
    QPushButton,
    QScrollArea,
    QFrame,
    QSizePolicy,
    QComboBox,
    QFileDialog,
)

from modules.ui.theme import theme
from modules.ui.primitives import (
    Button,
    IconButton,
    Card,
    Badge,
    StatusIndicator,
)


# ---------------------------------------------------------------------------
# ChatMessage
# ---------------------------------------------------------------------------

class ChatMessage(QWidget):
    """
    Структурированное сообщение в чате.

    Поддерживает:
      - краткий ответ;
      - progress/status;
      - раскрываемые детали;
      - действия;
      - артефакты;
      - подтверждения.
    """

    def __init__(
        self,
        author: str = "Nova",
        text: str = "",
        *,
        is_user: bool = False,
        timestamp: str = "",
        status: str = "sent",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._author = author
        self._text = text
        self._is_user = is_user
        self._timestamp = timestamp
        self._status = status
        self._actions: list[tuple[str, Callable]] = []
        self._details_widget: QWidget | None = None
        self._artifacts: list[QWidget] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(12)

        # Аватар
        self._avatar = StatusIndicator(
            "active" if self._is_user else "idle",
            size=10,
        )

        # Контейнер сообщения
        self._bubble = Card(
            padding=12,
            radius_key="lg",
            hover=not self._is_user,
        )
        self._bubble.setMaximumWidth(820)
        self._bubble.setSizePolicy(
            QSizePolicy.Preferred,
            QSizePolicy.Maximum,
        )
        if self._is_user:
            self._bubble.setStyleSheet(
                f"""
                Card {{
                    background: {theme.color("accent.soft")};
                    border: 1px solid #3a3267;
                    border-radius: {theme.radius("lg")};
                }}
                """
            )
        self._bubble_layout = QVBoxLayout()
        self._bubble_layout.setContentsMargins(0, 0, 0, 0)
        self._bubble_layout.setSpacing(6)
        self._bubble.layout().addLayout(self._bubble_layout)

        # Автор + статус
        header = QHBoxLayout()
        author_label = QLabel(self._author)
        author_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.primary") if self._is_user else theme.color("accent.primary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
                font-weight: {theme.font_weight("semibold")};
            }}
        """)
        header.addWidget(author_label)
        header.addStretch()

        status_badge = Badge(self._status, status="neutral")
        header.addWidget(status_badge)

        self._bubble_layout.addLayout(header)

        # Текст
        self._text_label = QLabel(self._text)
        self._text_label.setWordWrap(True)
        self._text_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.primary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
                font-weight: {theme.font_weight("regular")};
            }}
        """)
        self._bubble_layout.addWidget(self._text_label)

        # Время
        if self._timestamp:
            time_label = QLabel(self._timestamp)
            time_label.setStyleSheet(f"""
                QLabel {{
                    color: {theme.color("text.muted")};
                    font-family: {theme.font_family()};
                    font-size: {theme.font_size("caption")}px;
                }}
            """)
            self._bubble_layout.addWidget(time_label)

        # Действия
        self._actions_layout = QHBoxLayout()
        self._actions_layout.setSpacing(8)
        self._bubble_layout.addLayout(self._actions_layout)

        # Детали (скрыты по умолчанию)
        self._details_container = QFrame()
        self._details_container.hide()
        details_layout = QVBoxLayout(self._details_container)
        details_layout.setContentsMargins(8, 8, 8, 8)
        details_layout.setSpacing(4)

        self._details_label = QLabel()
        self._details_label.setWordWrap(True)
        self._details_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.secondary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("secondary")}px;
            }}
        """)
        details_layout.addWidget(self._details_label)
        self._bubble_layout.addWidget(self._details_container)

        # Артефакты
        self._artifacts_layout = QHBoxLayout()
        self._artifacts_layout.setSpacing(8)
        self._bubble_layout.addLayout(self._artifacts_layout)

        if self._is_user:
            self._layout.addStretch(1)
            self._layout.addWidget(self._bubble)
            self._layout.addWidget(
                self._avatar,
                alignment=Qt.AlignTop,
            )
        else:
            self._layout.addWidget(
                self._avatar,
                alignment=Qt.AlignTop,
            )
            self._layout.addWidget(self._bubble)
            self._layout.addStretch(1)

    def set_text(self, text: str) -> None:
        """Обновляет текст сообщения (для streaming)."""
        self._text = text
        self._text_label.setText(text)

    def append_text(self, chunk: str) -> None:
        """Добавляет чанк текста (для streaming без дрожания)."""
        self._text += chunk
        self._text_label.setText(self._text)

    def add_action(
        self,
        label: str,
        callback: Callable[[], None],
        *,
        variant: str = "ghost",
    ) -> None:
        """Добавляет кнопку-действие под сообщением."""
        btn = Button(label, variant=variant, size="sm")
        btn.clicked.connect(callback)
        self._actions_layout.addWidget(btn)
        self._actions.append((label, callback))

    def set_details(self, text: str) -> None:
        """Устанавливает раскрываемые детали."""
        self._details_label.setText(text)
        self._details_container.show()

    def toggle_details(self) -> None:
        """Переключает видимость деталей."""
        if self._details_container.isVisible():
            self._details_container.hide()
        else:
            self._details_container.show()

    def add_artifact(self, widget: QWidget) -> None:
        """Добавляет карточку артефакта."""
        self._artifacts.append(widget)
        self._artifacts_layout.addWidget(widget)

    def set_status(self, status: str) -> None:
        """Обновляет статус сообщения."""
        self._status = status


# ---------------------------------------------------------------------------
# ChatView
# ---------------------------------------------------------------------------

class ChatView(QScrollArea):
    """Прокручиваемый список сообщений чата."""

    starter_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._messages: list[ChatMessage] = []
        self._widgets: list[QWidget] = []
        self._container = QWidget()
        self._container.setObjectName("chatCanvas")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(34, 28, 34, 28)
        self._layout.setSpacing(10)
        self._welcome = self._build_welcome()
        self._layout.addWidget(self._welcome, stretch=1)
        self._layout.addStretch()

        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(f"""
            QScrollArea, QWidget#chatCanvas {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                border: none;
                width: 6px;
                margin: 0;
                padding: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {theme.color("border.subtle")};
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {theme.color("text.muted")};
            }}
        """)

    def _build_welcome(self) -> QWidget:
        welcome = QWidget()
        welcome.setObjectName("welcome")
        layout = QVBoxLayout(welcome)
        layout.setContentsMargins(40, 40, 40, 34)
        layout.setSpacing(12)
        layout.addStretch()

        orb = QLabel("N")
        orb.setFixedSize(54, 54)
        orb.setAlignment(Qt.AlignCenter)
        orb.setStyleSheet(
            f"""
            QLabel {{
                color: white;
                background: {theme.color("accent.primary")};
                border: 4px solid {theme.color("accent.soft")};
                border-radius: 27px;
                font-size: 20px;
                font-weight: 700;
            }}
            """
        )
        layout.addWidget(orb, alignment=Qt.AlignCenter)

        title = QLabel("Чем займёмся?")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"color: {theme.color('text.primary')}; font-size: 26px; font-weight: 680;"
        )
        layout.addWidget(title)
        subtitle = QLabel(
            "Работаю с кодом, файлами, приложениями, браузером и долгими задачами."
        )
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"color: {theme.color('text.secondary')}; font-size: 13px;"
        )
        layout.addWidget(subtitle)
        layout.addSpacing(10)

        starters = (
            "Открой проект и запусти тесты",
            "Разбери папку Downloads",
            "Исследуй тему и создай заметку",
            "Покажи активные процессы Nova",
        )
        grid = QVBoxLayout()
        grid.setSpacing(7)
        for prompt in starters:
            button = QPushButton(prompt)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumHeight(38)
            button.setStyleSheet(
                f"""
                QPushButton {{
                    background: {theme.color("bg.surface")};
                    color: {theme.color("text.secondary")};
                    border: 1px solid {theme.color("border.subtle")};
                    border-radius: {theme.radius("md")};
                    padding: 8px 12px;
                    text-align: left;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    color: {theme.color("text.primary")};
                    background: {theme.color("bg.surfaceHover")};
                    border-color: {theme.color("border.active")};
                }}
                """
            )
            button.clicked.connect(
                lambda checked=False, value=prompt: self.starter_selected.emit(value)
            )
            grid.addWidget(button)
        starter_wrap = QWidget()
        starter_wrap.setMaximumWidth(540)
        starter_wrap.setLayout(grid)
        layout.addWidget(starter_wrap, alignment=Qt.AlignHCenter)
        layout.addStretch()
        return welcome

    def add_message(self, message: ChatMessage) -> None:
        """Добавляет сообщение в чат."""
        self._welcome.hide()
        self._messages.append(message)
        self._widgets.append(message)
        self._layout.insertWidget(self._layout.count() - 1, message)
        self._scroll_to_bottom()

    def add_widget(self, widget: QWidget) -> None:
        """Добавляет произвольный виджет (например, ToolActivityCard) в чат."""
        self._welcome.hide()
        self._widgets.append(widget)
        self._layout.insertWidget(self._layout.count() - 1, widget)
        self._scroll_to_bottom()

    def append_to_last(self, chunk: str) -> None:
        """Добавляет чанк к последнему сообщению."""
        if self._messages:
            self._messages[-1].append_text(chunk)
        self._scroll_to_bottom()

    def clear(self) -> None:
        """Очищает чат."""
        for widget in self._widgets:
            self._layout.removeWidget(widget)
            widget.deleteLater()
        self._messages.clear()
        self._widgets.clear()
        self._welcome.show()

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(10, self._do_scroll)

    def _do_scroll(self) -> None:
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()
        )


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------

class _ComposerInput(QTextEdit):
    submit_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and not event.modifiers() & Qt.ShiftModifier
        ):
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)


class Composer(QWidget):
    """
    Поле ввода с поддержкой:
      - multiline;
      - drag-and-drop файлов;
      - вставка скриншота;
      - voice input;
      - выбор режима работы;
      - отправка Enter, новая строка Shift+Enter.
    """

    def __init__(
        self,
        *,
        on_submit: Callable[[str, dict], None] | None = None,
        on_voice_toggle: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_submit = on_submit
        self._on_voice_toggle = on_voice_toggle
        self._voice_active = False
        self._attachments: list[str] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 10, 24, 18)
        outer.setSpacing(0)

        self._surface = QFrame()
        self._surface.setObjectName("composerSurface")
        surface = QVBoxLayout(self._surface)
        surface.setContentsMargins(14, 10, 10, 9)
        surface.setSpacing(6)

        self._input = _ComposerInput()
        self._input.setPlaceholderText("Спроси Nova или дай задачу…")
        self._input.setAcceptRichText(False)
        self._input.setMinimumHeight(44)
        self._input.setMaximumHeight(72)
        self._input.setTabChangesFocus(True)
        self._input.submit_requested.connect(self._on_send_clicked)
        self._input.setStyleSheet(
            f"""
            QTextEdit {{
                background: transparent;
                color: {theme.color("text.primary")};
                border: none;
                padding: 3px 2px;
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
                selection-background-color: {theme.color("accent.primary")};
            }}
            """
        )
        surface.addWidget(self._input)

        self._attachment_label = QLabel()
        self._attachment_label.hide()
        self._attachment_label.setStyleSheet(
            f"color: {theme.color('accent.secondary')}; font-size: 11px;"
        )
        surface.addWidget(self._attachment_label)

        controls = QHBoxLayout()
        controls.setSpacing(7)
        self._attach_btn = Button("＋  Контекст", variant="ghost", size="sm")
        self._attach_btn.setToolTip("Добавить файлы или изображения")
        self._attach_btn.clicked.connect(self._pick_attachments)
        controls.addWidget(self._attach_btn)

        self._mode_select = QComboBox()
        for label, value in (
            ("Auto", "auto"),
            ("Fast", "fast"),
            ("Smart", "smart"),
            ("Coding", "coding"),
            ("Local", "local_only"),
        ):
            self._mode_select.addItem(label, value)
        self._mode_select.setFixedHeight(30)
        self._mode_select.setStyleSheet(
            f"""
            QComboBox {{
                background: transparent;
                color: {theme.color("text.muted")};
                border: 1px solid transparent;
                border-radius: {theme.radius("sm")};
                padding: 3px 8px;
                font-size: 11px;
            }}
            QComboBox:hover {{
                color: {theme.color("text.primary")};
                border-color: {theme.color("border.subtle")};
            }}
            QComboBox QAbstractItemView {{
                background: {theme.color("bg.surfaceHover")};
                color: {theme.color("text.primary")};
                border: 1px solid {theme.color("border.strong")};
                selection-background-color: {theme.color("accent.soft")};
            }}
            """
        )
        controls.addWidget(self._mode_select)

        self._mode_label = QLabel("Safe autonomy")
        self._mode_label.setStyleSheet(
            f"color: {theme.color('text.muted')}; font-size: 11px;"
        )
        controls.addWidget(self._mode_label)
        controls.addStretch()

        self._voice_btn = IconButton(
            "◎", tooltip="Переключить голосовой режим", size="sm"
        )
        self._voice_btn.clicked.connect(self._on_voice_clicked)
        controls.addWidget(self._voice_btn)

        self._send_btn = IconButton(
            "↑", tooltip="Отправить (Enter)", size="md", variant="primary"
        )
        self._send_btn.clicked.connect(self._on_send_clicked)
        controls.addWidget(self._send_btn)
        surface.addLayout(controls)
        outer.addWidget(self._surface)
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(f"""
            Composer {{
                background: {theme.color("bg.base")};
                border: none;
            }}
            QFrame#composerSurface {{
                background: {theme.color("bg.input")};
                border: 1px solid {theme.color("border.strong")};
                border-radius: {theme.radius("lg")};
            }}
        """)

    def _on_send_clicked(self) -> None:
        text = self._input.toPlainText().strip()
        if not text and not self._attachments:
            return

        if self._on_submit:
            self._on_submit(text, {
                "profile": "assistant",
                "model_mode": self._mode_select.currentData() or "auto",
                "attachments": list(self._attachments),
            })

        self._input.clear()
        self._attachments.clear()
        self._update_attachment_label()

    def _pick_attachments(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Добавить контекст",
            "",
            "Все файлы (*.*)",
        )
        if not paths:
            return
        for path in paths:
            if path not in self._attachments:
                self._attachments.append(path)
        self._update_attachment_label()

    def _update_attachment_label(self) -> None:
        if not self._attachments:
            self._attachment_label.clear()
            self._attachment_label.hide()
            return
        names = [path.replace("\\", "/").rsplit("/", 1)[-1] for path in self._attachments]
        suffix = "" if len(names) <= 3 else f"  +{len(names) - 3}"
        self._attachment_label.setText("Контекст: " + " · ".join(names[:3]) + suffix)
        self._attachment_label.show()

    def _on_voice_clicked(self) -> None:
        self._voice_active = not self._voice_active
        if self._on_voice_toggle:
            self._on_voice_toggle()

        if self._voice_active:
            self._voice_btn.setText("●")
            self._voice_btn.setToolTip("Остановить голосовой режим")
        else:
            self._voice_btn.setText("◎")
            self._voice_btn.setToolTip("Переключить голосовой режим")

    def set_voice_state(self, active: bool, listening: bool = False) -> None:
        """Обновляет состояние кнопки микрофона."""
        self._voice_active = active
        if active:
            self._voice_btn.setText("●")
        else:
            self._voice_btn.setText("◎")

    def set_disabled(self, disabled: bool) -> None:
        self._input.setDisabled(disabled)
        self._send_btn.setDisabled(disabled)

    def set_mode(self, mode: str) -> None:
        self._mode_label.setText(mode)

    def focus_input(self) -> None:
        self._input.setFocus()

    def set_text(self, text: str) -> None:
        self._input.setPlainText(text)
        cursor = self._input.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._input.setTextCursor(cursor)


# ---------------------------------------------------------------------------
# ToolActivityCard
# ---------------------------------------------------------------------------

class ToolActivityCard(QWidget):
    """Компактная карточка tool call с состоянием."""

    def __init__(
        self,
        tool_name: str = "",
        description: str = "",
        *,
        status: str = "pending",
        duration: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tool_name = tool_name
        self._description = description
        self._status = status
        self._duration = duration
        self._expanded = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 9, 12, 9)
        self._layout.setSpacing(6)
        summary = QHBoxLayout()
        summary.setSpacing(10)

        # Индикатор статуса
        self._indicator = StatusIndicator(self._status)
        summary.addWidget(self._indicator)

        # Контент
        content = QVBoxLayout()
        content.setSpacing(2)

        self._name_label = QLabel(self._description or self._tool_name)
        self._name_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.primary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
                font-weight: {theme.font_weight("medium")};
            }}
        """)
        content.addWidget(self._name_label)

        self._meta_label = QLabel(
            f"{self._tool_name} · {self._duration}" if self._duration
            else self._tool_name
        )
        self._meta_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.muted")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("caption")}px;
            }}
        """)
        content.addWidget(self._meta_label)

        summary.addLayout(content, stretch=1)

        # Кнопка раскрытия
        self._expand_btn = IconButton("▼", tooltip="Подробнее", size="sm")
        self._expand_btn.clicked.connect(self._toggle_expand)
        summary.addWidget(self._expand_btn)
        self._layout.addLayout(summary)

        # Раскрываемый контент
        self._details = QFrame()
        self._details.hide()
        details_layout = QVBoxLayout(self._details)
        details_layout.setContentsMargins(16, 8, 16, 8)
        self._details_label = QLabel()
        self._details_label.setWordWrap(True)
        self._details_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.secondary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("secondary")}px;
            }}
        """)
        details_layout.addWidget(self._details_label)
        self._layout.addWidget(self._details)

        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(f"""
            ToolActivityCard {{
                background: {theme.color("bg.surface")};
                border: 1px solid {theme.color("border.subtle")};
                border-radius: {theme.radius("md")};
            }}
        """)

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self._details.show()
            self._expand_btn.setText("▲")
        else:
            self._details.hide()
            self._expand_btn.setText("▼")

    def set_status(self, status: str) -> None:
        self._status = status
        self._indicator.set_status(status)

    def set_duration(self, duration: str) -> None:
        self._duration = duration
        self._meta_label.setText(
            f"{self._tool_name} · {self._duration}" if self._duration
            else self._tool_name
        )

    def set_details(self, text: str) -> None:
        self._details_label.setText(text)


# ---------------------------------------------------------------------------
# ErrorCard
# ---------------------------------------------------------------------------

class ErrorCard(QWidget):
    """Карточка ошибки с кнопками retry, settings, details."""

    def __init__(
        self,
        title: str = "Ошибка",
        message: str = "",
        *,
        on_retry: Callable[[], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        on_details: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._setup_ui(title, message, on_retry, on_settings, on_details)

    def _setup_ui(
        self,
        title: str,
        message: str,
        on_retry: Callable[[], None] | None,
        on_settings: Callable[[], None] | None,
        on_details: Callable[[], None] | None,
    ) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        indicator = StatusIndicator("danger", size=20)
        layout.addWidget(indicator)

        content = QVBoxLayout()
        content.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("danger")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
                font-weight: {theme.font_weight("semibold")};
            }}
        """)
        content.addWidget(title_label)

        if message:
            msg_label = QLabel(message)
            msg_label.setWordWrap(True)
            msg_label.setStyleSheet(f"""
                QLabel {{
                    color: {theme.color("text.secondary")};
                    font-family: {theme.font_family()};
                    font-size: {theme.font_size("secondary")}px;
                }}
            """)
            content.addWidget(msg_label)

        layout.addLayout(content, stretch=1)

        # Кнопки
        if on_retry:
            retry_btn = Button("Повторить", variant="ghost", size="sm")
            retry_btn.clicked.connect(on_retry)
            layout.addWidget(retry_btn)

        if on_settings:
            settings_btn = Button("Настройки", variant="ghost", size="sm")
            settings_btn.clicked.connect(on_settings)
            layout.addWidget(settings_btn)

        if on_details:
            details_btn = Button("Подробнее", variant="ghost", size="sm")
            details_btn.clicked.connect(on_details)
            layout.addWidget(details_btn)

        self.setStyleSheet(f"""
            ErrorCard {{
                background: {theme.color("bg.surface")};
                border: 1px solid {theme.color("danger")}40;
                border-radius: {theme.radius("md")};
            }}
        """)


# ---------------------------------------------------------------------------
# ArtifactCard
# ---------------------------------------------------------------------------

class ArtifactCard(QWidget):
    """Карточка артефакта: файл, заметка, ссылка, код, diff и т.д."""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        *,
        artifact_type: str = "file",
        on_open: Callable[[], None] | None = None,
        on_copy: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._setup_ui(title, subtitle, artifact_type, on_open, on_copy)

    def _setup_ui(
        self,
        title: str,
        subtitle: str,
        artifact_type: str,
        on_open: Callable[[], None] | None,
        on_copy: Callable[[], None] | None,
    ) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Иконка типа
        type_icons = {
            "file": "📄",
            "folder": "📁",
            "note": "◈",
            "link": "🔗",
            "image": "🖼",
            "pdf": "📄",
            "table": "📊",
            "code": "</>",
            "diff": "±",
            "pr": "🔀",
            "issue": "🎯",
            "report": "📋",
            "workflow": "🔄",
        }
        icon = type_icons.get(artifact_type, "📄")

        icon_label = QLabel(icon)
        icon_label.setFixedSize(24, 24)
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        content = QVBoxLayout()
        content.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.color("text.primary")};
                font-family: {theme.font_family()};
                font-size: {theme.font_size("body")}px;
                font-weight: {theme.font_weight("semibold")};
            }}
        """)
        content.addWidget(title_label)

        if subtitle:
            sub_label = QLabel(subtitle)
            sub_label.setStyleSheet(f"""
                QLabel {{
                    color: {theme.color("text.muted")};
                    font-family: {theme.font_family()};
                    font-size: {theme.font_size("caption")}px;
                }}
            """)
            content.addWidget(sub_label)

        layout.addLayout(content, stretch=1)

        # Кнопки
        if on_open:
            open_btn = Button("Открыть", variant="ghost", size="sm")
            open_btn.clicked.connect(on_open)
            layout.addWidget(open_btn)

        if on_copy:
            copy_btn = Button("Скопировать", variant="ghost", size="sm")
            copy_btn.clicked.connect(on_copy)
            layout.addWidget(copy_btn)

        self.setStyleSheet(f"""
            ArtifactCard {{
                background: {theme.color("bg.surface")};
                border: 1px solid {theme.color("border.subtle")};
                border-radius: {theme.radius("lg")};
            }}
        """)
