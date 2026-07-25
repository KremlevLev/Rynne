# conftest.py
"""
Глобальные фикстуры для тестов Nova.

Создаёт QApplication один раз на сессию, чтобы тесты, которые
инстанцируют QWidget-объекты (ChatMessage, TaskView, CommandPalette и т.д.),
могли работать без явного создания QApplication в каждом тесте.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def _qapp():
    """Создаёт QApplication для всей сессии тестов."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
