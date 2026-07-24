# modules/domain/ledger.py
"""Execution Ledger - отслеживание всех side effects.

Позволяет:
- Записывать каждый side effect
- Поддерживать rollback metadata
- Возобновлять задачи после перезапуска
- Генерировать отчёты о выполненных действиях
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SideEffectRecord:
    """Запись о выполненном side effect."""
    id: str
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    timestamp: str
    session_id: str
    turn_id: str
    rollback_info: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "result": self.result,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "rollback_info": self.rollback_info,
            "verification": self.verification,
            "artifacts": self.artifacts,
        }


@dataclass
class ExecutionLedger:
    """
    Журнал выполнения всех side effects.
    
    Позволяет отменять действия, восстанавливать состояние
    и анализировать выполненные операции.
    """
    
    records: list[SideEffectRecord] = field(default_factory=list)
    
    def record(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        session_id: str,
        turn_id: str,
        rollback_info: dict[str, Any] | None = None,
        verification: dict[str, Any] | None = None,
        artifacts: list[str] | None = None,
    ) -> SideEffectRecord:
        """
        Добавляет запись о выполненном действии.
        
        Args:
            tool_name: Имя вызванного инструмента
            arguments: Аргументы инструмента
            result: Результат выполнения
            session_id: ID сессии
            turn_id: ID хода
            rollback_info: Информация для отката (опционально)
            verification: Информация о верификации (опционально)
            artifacts: Список артефактов (опционально)
            
        Returns:
            Созданная запись
        """
        record = SideEffectRecord(
            id=f"se_{uuid.uuid4().hex}",
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            timestamp=datetime.now().isoformat(),
            session_id=session_id,
            turn_id=turn_id,
            rollback_info=rollback_info,
            verification=verification,
            artifacts=artifacts or [],
        )
        self.records.append(record)
        return record
    
    def get_rollbackable_records(
        self,
        session_id: str | None = None,
    ) -> list[SideEffectRecord]:
        """
        Возвращает записи, которые можно откатить.
        
        Args:
            session_id: Фильтр по сессии (опционально)
            
        Returns:
            Список записей с rollback_info
        """
        return [
            r
            for r in self.records
            if r.rollback_info is not None
            and (session_id is None or r.session_id == session_id)
        ]
    
    def get_by_tool(
        self,
        tool_name: str,
        session_id: str | None = None,
    ) -> list[SideEffectRecord]:
        """
        Возвращает записи по имени инструмента.
        """
        return [
            r
            for r in self.records
            if r.tool_name == tool_name
            and (session_id is None or r.session_id == session_id)
        ]
    
    def to_json(self) -> str:
        """Сериализует журнал в JSON."""
        return json.dumps(
            [r.to_dict() for r in self.records],
            ensure_ascii=False,
            indent=2,
        )
    
    def clear(self) -> None:
        """Очищает журнал."""
        self.records.clear()
    
    def __len__(self) -> int:
        return len(self.records)


# Глобальный журнал для текущей сессии
_ledger: ExecutionLedger | None = None


def get_ledger() -> ExecutionLedger:
    """
    Возвращает глобальный журнал выполнения.
    
    Создаёт журнал при первом обращении.
    """
    global _ledger
    if _ledger is None:
        _ledger = ExecutionLedger()
    return _ledger


def reset_ledger() -> None:
    """Сбрасывает глобальный журнал (для тестов)."""
    global _ledger
    _ledger = None