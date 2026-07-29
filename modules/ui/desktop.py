# modules/ui/desktop.py
from __future__ import annotations

import json
import queue
import sys
from typing import Any

from modules.ui.desktop_protocol import (
    make_command,
)
from PySide6.QtWidgets import (
            QComboBox,
            QLineEdit,
)

def run_desktop(
    *,
    event_queue,
    command_queue,
) -> None:
    try:
        from PySide6.QtCore import (
            QTimer,
            Qt,
        )
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import (
            QApplication,
            QHBoxLayout,
            QLabel,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QSplitter,
            QTabWidget,
            QTableWidget,
            QTableWidgetItem,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except ImportError:
        return

    class NovaDesktopWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()

            self.event_queue = event_queue
            self.command_queue = command_queue

            self.setWindowTitle(
                "Nova Control Center"
            )
            self.resize(1180, 760)

            self._processes: list[
                dict[str, Any]
            ] = []
            self._memories: list[
                dict[str, Any]
            ] = []
            self._permissions: list[
                dict[str, Any]
            ] = []

            self._build_ui()
            self._apply_style()

            self.timer = QTimer(self)
            self.timer.timeout.connect(
                self._process_events
            )
            self.timer.start(100)

            self._send_command("refresh")
        def _input_mode_changed(
            self,
            _index: int,
        ) -> None:
            input_mode = (
                self.input_mode_combo
                .currentData()
            )

            if not input_mode:
                return

            self._send_command(
                "set_input_mode",
                {
                    "input_mode": input_mode,
                },
            )

        def _create_chat_tab(
            self,
        ) -> QWidget:
            widget = QWidget()
            layout = QVBoxLayout(widget)

            self.chat_history = QTextEdit()
            self.chat_history.setReadOnly(True)
            self.chat_history.setPlaceholderText(
                "Диалог с Nova..."
            )

            controls = QHBoxLayout()

            self.profile_combo = QComboBox()
            self.profile_combo.addItem(
                "Помощник",
                "assistant",
            )
            self.profile_combo.addItem(
                "Безопасный",
                "safe",
            )
            self.profile_combo.addItem(
                "Инженер",
                "engineer",
            )
            self.profile_combo.addItem(
                "Автономная задача",
                "autonomous_task",
            )
            self.profile_combo.addItem(
                "Приватный локальный",
                "private_local",
            )
            self.input_mode_combo = QComboBox()
            self.input_mode_combo.currentIndexChanged.connect(
                self._input_mode_changed
            )

            self.input_mode_combo.addItem(
                "Ввод: Wake word",
                "wake_word",
            )
            self.input_mode_combo.addItem(
                "Ввод: Непрерывный",
                "continuous",
            )
            self.input_mode_combo.addItem(
                "Ввод: Нажми и говори",
                "push_to_talk",
            )
            self.input_mode_combo.addItem(
                "Ввод: Только текст",
                "text_only",
            )
            self.input_mode_combo.addItem(
                "Ввод: Приватный",
                "privacy",
            )

            self.model_mode_combo = QComboBox()
            self.model_mode_combo.addItem(
                "Модель: Авто",
                "auto",
            )
            self.model_mode_combo.addItem(
                "Модель: Быстрая",
                "fast",
            )
            self.model_mode_combo.addItem(
                "Модель: Умная",
                "smart",
            )
            self.model_mode_combo.addItem(
                "Модель: Код",
                "coding",
            )
            self.model_mode_combo.addItem(
                "Только бесплатные",
                "free_only",
            )
            self.model_mode_combo.addItem(
                "Только локальная",
                "local_only",
            )

            controls.addWidget(
                self.profile_combo
            )
            controls.addWidget(
                self.model_mode_combo
            )
            controls.addStretch()
            controls.addWidget(
                self.input_mode_combo
            )

            input_layout = QHBoxLayout()

            self.chat_input = QLineEdit()
            self.chat_input.setPlaceholderText(
                "Введите команду Nova..."
            )
            self.chat_input.returnPressed.connect(
                self._submit_chat_request
            )

            send_button = QPushButton(
                "Отправить"
            )
            send_button.clicked.connect(
                self._submit_chat_request
            )

            cancel_button = QPushButton(
                "Отмена"
            )
            cancel_button.clicked.connect(
                lambda: self._send_command(
                    "cancel_current_request"
                )
            )

            input_layout.addWidget(
                self.chat_input
            )
            input_layout.addWidget(
                send_button
            )
            input_layout.addWidget(
                cancel_button
            )

            layout.addWidget(
                self.chat_history
            )
            layout.addLayout(controls)
            layout.addLayout(input_layout)

            return widget

        def _submit_chat_request(
            self,
        ) -> None:
            text = self.chat_input.text().strip()

            if not text:
                return

            profile = (
                self.profile_combo.currentData()
                or "assistant"
            )

            model_mode = (
                self.model_mode_combo.currentData()
                or "auto"
            )

            self._append_chat_message(
                "Вы",
                text,
            )

            self._send_command(
                "submit_user_request",
                {
                    "text": text,
                    "profile": profile,
                    "model_mode": model_mode,
                },
            )

            self.chat_input.clear()

        def _append_chat_message(
            self,
            author: str,
            text: str,
        ) -> None:
            if not text.strip():
                return

            safe_author = (
                str(author)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

            safe_text = (
                str(text)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
            )

            color = (
                "#66d9ff"
                if author == "Nova"
                else "#7dff9a"
            )

            self.chat_history.append(
                (
                    f"<p><b style='color:{color}'>"
                    f"{safe_author}:</b><br>"
                    f"{safe_text}</p>"
                )
            )

        def _update_preferences(
            self,
            payload: dict[str, Any],
        ) -> None:
            profile_value = str(
                payload.get(
                    "assistant_profile",
                    "assistant",
                )
            )
            input_mode_value = str(
                payload.get(
                    "input_mode",
                    "continuous",
                )
            )

            input_mode_index = (
                self.input_mode_combo.findData(
                    input_mode_value
                )
            )

            self.input_mode_combo.blockSignals(
                True
            )
            self.input_mode_combo.setCurrentIndex(
                input_mode_index
            )
            self.input_mode_combo.blockSignals(
                False
            )


            model_mode_value = str(
                payload.get(
                    "model_mode",
                    "auto",
                )
            )

            profile_index = (
                self.profile_combo.findData(
                    profile_value
                )
            )

            if profile_index >= 0:
                self.profile_combo.setCurrentIndex(
                    profile_index
                )

            model_index = (
                self.model_mode_combo.findData(
                    model_mode_value
                )
            )

            if model_index >= 0:
                self.model_mode_combo.setCurrentIndex(
                    model_index
                )

        def _build_ui(self) -> None:
            root = QWidget()
            root_layout = QVBoxLayout(root)

            header_layout = QHBoxLayout()

            self.title_label = QLabel(
                "NOVA CONTROL CENTER"
            )
            self.title_label.setObjectName(
                "title"
            )

            self.state_label = QLabel(
                "● СПИТ"
            )
            self.state_label.setObjectName(
                "state"
            )

            refresh_button = QPushButton(
                "Обновить"
            )
            refresh_button.clicked.connect(
                lambda: self._send_command(
                    "refresh"
                )
            )

            header_layout.addWidget(
                self.title_label
            )
            header_layout.addStretch()
            header_layout.addWidget(
                self.state_label
            )
            header_layout.addWidget(
                refresh_button
            )

            root_layout.addLayout(
                header_layout
            )

            self.tabs = QTabWidget()
            self.tabs.addTab(
                self._create_chat_tab(),
                "Чат",
            )
            self.tabs.addTab(
                self._create_overview_tab(),
                "Обзор",
            )
            self.tabs.addTab(
                self._create_processes_tab(),
                "Процессы",
            )
            self.tabs.addTab(
                self._create_memories_tab(),
                "Память",
            )
            self.tabs.addTab(
                self._create_permissions_tab(),
                "Разрешения",
            )
            self.tabs.addTab(
                self._create_models_tab(),
                "Модели",
            )
            self.tabs.addTab(
                self._create_log_tab(),
                "Журнал",
            )

            root_layout.addWidget(self.tabs)

            self.setCentralWidget(root)

        def _create_overview_tab(self) -> QWidget:
            widget = QWidget()
            layout = QVBoxLayout(widget)

            self.overview_text = QTextEdit()
            self.overview_text.setReadOnly(True)
            self.overview_text.setPlainText(
                "Nova Core подключается..."
            )

            layout.addWidget(
                self.overview_text
            )

            return widget

        def _create_processes_tab(
            self,
        ) -> QWidget:
            widget = QWidget()
            layout = QVBoxLayout(widget)

            self.process_table = QTableWidget(
                0,
                5,
            )
            self.process_table.setHorizontalHeaderLabels(
                [
                    "ID",
                    "Название",
                    "PID",
                    "Статус",
                    "Команда",
                ]
            )
            self.process_table.setSelectionBehavior(
                QTableWidget.SelectRows
            )

            buttons = QHBoxLayout()

            stop_button = QPushButton(
                "Остановить"
            )
            stop_button.clicked.connect(
                self._stop_selected_process
            )

            force_button = QPushButton(
                "Завершить принудительно"
            )
            force_button.clicked.connect(
                lambda: self._stop_selected_process(
                    force=True
                )
            )

            buttons.addWidget(stop_button)
            buttons.addWidget(force_button)
            buttons.addStretch()

            layout.addWidget(
                self.process_table
            )
            layout.addLayout(buttons)

            return widget

        def _create_memories_tab(
            self,
        ) -> QWidget:
            widget = QWidget()
            layout = QVBoxLayout(widget)

            self.memory_table = QTableWidget(
                0,
                4,
            )
            self.memory_table.setHorizontalHeaderLabels(
                [
                    "Ключ",
                    "Значение",
                    "Категория",
                    "Уверенность",
                ]
            )
            self.memory_table.setSelectionBehavior(
                QTableWidget.SelectRows
            )

            buttons = QHBoxLayout()

            delete_button = QPushButton(
                "Забыть выбранное"
            )
            delete_button.clicked.connect(
                self._delete_selected_memory
            )

            clear_button = QPushButton(
                "Очистить всю память"
            )
            clear_button.clicked.connect(
                self._clear_memories
            )

            buttons.addWidget(delete_button)
            buttons.addWidget(clear_button)
            buttons.addStretch()

            layout.addWidget(
                self.memory_table
            )
            layout.addLayout(buttons)

            return widget

        def _create_permissions_tab(
            self,
        ) -> QWidget:
            widget = QWidget()
            layout = QVBoxLayout(widget)

            self.permission_table = QTableWidget(
                0,
                5,
            )
            self.permission_table.setHorizontalHeaderLabels(
                [
                    "Operation ID",
                    "Инструмент",
                    "Риск",
                    "Категория",
                    "Описание",
                ]
            )
            self.permission_table.setSelectionBehavior(
                QTableWidget.SelectRows
            )

            buttons = QHBoxLayout()

            allow_button = QPushButton(
                "Разрешить"
            )
            allow_button.clicked.connect(
                self._allow_selected_permission
            )

            deny_button = QPushButton(
                "Запретить"
            )
            deny_button.clicked.connect(
                self._deny_selected_permission
            )

            buttons.addWidget(allow_button)
            buttons.addWidget(deny_button)
            buttons.addStretch()

            layout.addWidget(
                self.permission_table
            )
            layout.addLayout(buttons)

            return widget

        def _create_models_tab(
            self,
        ) -> QWidget:
            widget = QWidget()
            layout = QVBoxLayout(widget)

            self.models_text = QTextEdit()
            self.models_text.setReadOnly(True)

            layout.addWidget(
                self.models_text
            )

            return widget

        def _create_log_tab(self) -> QWidget:
            widget = QWidget()
            layout = QVBoxLayout(widget)

            self.log_text = QTextEdit()
            self.log_text.setReadOnly(True)

            layout.addWidget(
                self.log_text
            )

            return widget

        def _apply_style(self) -> None:
            self.setStyleSheet(
                """
                QMainWindow, QWidget {
                    background: #111216;
                    color: #e8e9ee;
                    font-family: "Segoe UI";
                    font-size: 13px;
                }

                QLabel#title {
                    color: #66d9ff;
                    font-size: 20px;
                    font-weight: 700;
                    padding: 8px;
                }

                QLabel#state {
                    color: #7dff9a;
                    font-weight: 700;
                    padding: 8px;
                }

                QTabWidget::pane {
                    border: 1px solid #2a2d35;
                }

                QTabBar::tab {
                    background: #1a1c22;
                    color: #b7bac5;
                    padding: 10px 18px;
                }

                QTabBar::tab:selected {
                    background: #252832;
                    color: #66d9ff;
                }

                QPushButton {
                    background: #252832;
                    border: 1px solid #3a3e49;
                    border-radius: 5px;
                    padding: 8px 14px;
                }

                QPushButton:hover {
                    background: #303440;
                    border-color: #66d9ff;
                }

                QTableWidget, QTextEdit {
                    background: #16181e;
                    border: 1px solid #2a2d35;
                    gridline-color: #2a2d35;
                    selection-background-color: #284c5c;
                }

                QHeaderView::section {
                    background: #20232b;
                    color: #d7d9e1;
                    padding: 7px;
                    border: 1px solid #30333d;
                }
                """
            )

        def _process_events(self) -> None:
            for _ in range(100):
                try:
                    event = (
                        self.event_queue.get_nowait()
                    )
                except queue.Empty:
                    break
                except (
                    BrokenPipeError,
                    EOFError,
                    OSError,
                ):
                    break

                if not isinstance(event, dict):
                    continue

                event_type = event.get(
                    "event_type"
                )
                payload = event.get(
                    "payload",
                    {},
                )

                if event_type == "shutdown":
                    self.close()
                    return

                if event_type == "runtime":
                    self._update_runtime(
                        payload
                    )
                elif event_type == "processes":
                    self._update_processes(
                        payload.get(
                            "items",
                            [],
                        )
                    )
                elif event_type == "memories":
                    self._update_memories(
                        payload.get(
                            "items",
                            [],
                        )
                    )
                elif event_type == "permissions":
                    self._update_permissions(
                        payload.get(
                            "items",
                            [],
                        )
                    )
                elif event_type == "models":
                    self.models_text.setPlainText(
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                elif event_type == "user_message":
                    self._append_chat_message(
                        "Вы",
                        str(
                            payload.get(
                                "text",
                                "",
                            )
                        ),
                    )

                elif event_type == "assistant_message":
                    self._append_chat_message(
                        "Nova",
                        str(
                            payload.get(
                                "display_text",
                                "",
                            )
                        ),
                    )

                elif event_type == "proactive_suggestion":
                    title = str(
                        payload.get("title", "")
                    ).strip()
                    message = str(
                        payload.get("message", "")
                    ).strip()
                    reason = str(
                        payload.get("reason", "")
                    ).strip()
                    combined = "\n\n".join(
                        part
                        for part in (
                            title,
                            message,
                            (
                                f"Почему: {reason}"
                                if reason
                                else ""
                            ),
                        )
                        if part
                    )
                    self._append_chat_message(
                        "Nova",
                        combined,
                    )

                elif event_type == "preferences":
                    self._update_preferences(
                        payload
                    )

                elif event_type == (
                    "command_result"
                ):
                    self._append_log(
                        (
                            "Команда UI: "
                            f"{payload.get('message', '')}"
                        )
                    )

        def _update_runtime(
            self,
            payload: dict[str, Any],
        ) -> None:
            state = str(
                payload.get(
                    "state",
                    "НЕИЗВЕСТНО",
                )
            )

            self.state_label.setText(
                f"● {state}"
            )

            overview = {
                "state": state,
                "active": payload.get(
                    "active"
                ),
                "processes": len(
                    self._processes
                ),
                "memories": len(
                    self._memories
                ),
                "pending_permissions": len(
                    self._permissions
                ),
            }

            self.overview_text.setPlainText(
                json.dumps(
                    overview,
                    ensure_ascii=False,
                    indent=2,
                )
            )

        def _update_processes(
            self,
            items: list[dict[str, Any]],
        ) -> None:
            self._processes = items
            self.process_table.setRowCount(
                len(items)
            )

            for row, item in enumerate(items):
                values = [
                    item.get(
                        "process_id",
                        "",
                    ),
                    item.get("label", ""),
                    item.get("pid", ""),
                    item.get("status", ""),
                    " ".join(
                        item.get(
                            "command",
                            [],
                        )
                    ),
                ]

                for column, value in enumerate(
                    values
                ):
                    self.process_table.setItem(
                        row,
                        column,
                        QTableWidgetItem(
                            str(value)
                        ),
                    )

            self.process_table.resizeColumnsToContents()

        def _update_memories(
            self,
            items: list[dict[str, Any]],
        ) -> None:
            self._memories = items
            self.memory_table.setRowCount(
                len(items)
            )

            for row, item in enumerate(items):
                values = [
                    item.get("key", ""),
                    item.get("value", ""),
                    item.get(
                        "category",
                        "",
                    ),
                    item.get(
                        "confidence",
                        "",
                    ),
                ]

                for column, value in enumerate(
                    values
                ):
                    self.memory_table.setItem(
                        row,
                        column,
                        QTableWidgetItem(
                            str(value)
                        ),
                    )

            self.memory_table.resizeColumnsToContents()

        def _update_permissions(
            self,
            items: list[dict[str, Any]],
        ) -> None:
            self._permissions = items
            self.permission_table.setRowCount(
                len(items)
            )

            for row, item in enumerate(items):
                values = [
                    item.get(
                        "operation_id",
                        "",
                    ),
                    item.get(
                        "tool_name",
                        "",
                    ),
                    item.get("risk", ""),
                    item.get(
                        "category",
                        "",
                    ),
                    item.get(
                        "message",
                        "",
                    ),
                ]

                for column, value in enumerate(
                    values
                ):
                    self.permission_table.setItem(
                        row,
                        column,
                        QTableWidgetItem(
                            str(value)
                        ),
                    )

            self.permission_table.resizeColumnsToContents()

            if items:
                self.tabs.setCurrentIndex(4)

        def _selected_row(
            self,
            table: QTableWidget,
        ) -> int | None:
            selected = (
                table.selectionModel()
                .selectedRows()
            )

            if not selected:
                return None

            return selected[0].row()

        def _stop_selected_process(
            self,
            force: bool = False,
        ) -> None:
            row = self._selected_row(
                self.process_table
            )

            if row is None:
                return

            process_id = str(
                self._processes[row].get(
                    "process_id",
                    "",
                )
            )

            self._send_command(
                "stop_process",
                {
                    "process_id": process_id,
                    "force": force,
                },
            )

        def _delete_selected_memory(
            self,
        ) -> None:
            row = self._selected_row(
                self.memory_table
            )

            if row is None:
                return

            key = str(
                self._memories[row].get(
                    "key",
                    "",
                )
            )

            self._send_command(
                "delete_memory",
                {
                    "key": key,
                },
            )

        def _clear_memories(self) -> None:
            answer = QMessageBox.question(
                self,
                "Очистить память",
                (
                    "Удалить всю долговременную "
                    "память Nova?"
                ),
            )

            if answer == QMessageBox.Yes:
                self._send_command(
                    "clear_memories"
                )

        def _allow_selected_permission(
            self,
        ) -> None:
            self._resolve_permission(
                allow=True
            )

        def _deny_selected_permission(
            self,
        ) -> None:
            self._resolve_permission(
                allow=False
            )

        def _resolve_permission(
            self,
            *,
            allow: bool,
        ) -> None:
            row = self._selected_row(
                self.permission_table
            )

            if row is None:
                return

            operation_id = str(
                self._permissions[row].get(
                    "operation_id",
                    "",
                )
            )

            self._send_command(
                (
                    "confirm_permission"
                    if allow
                    else "deny_permission"
                ),
                {
                    "operation_id": (
                        operation_id
                    ),
                },
            )

        def _send_command(
            self,
            action: str,
            payload: dict[str, Any]
            | None = None,
        ) -> None:
            command = make_command(
                action,
                payload,
            )

            try:
                self.command_queue.put_nowait(
                    command
                )
            except queue.Full:
                self._append_log(
                    "Очередь команд UI заполнена."
                )

        def _append_log(
            self,
            message: str,
        ) -> None:
            self.log_text.append(message)

    app = QApplication(sys.argv)

    window = NovaDesktopWindow()
    window.show()

    app.exec()
