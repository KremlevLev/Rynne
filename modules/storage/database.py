# modules/storage/database.py
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any


logger = logging.getLogger("Database")

DEFAULT_DB_PATH = Path("data/nova.db")


class Database:
    """
    Центральное SQLite-хранилище Nova.

    Потокобезопасно через RLock.
    Автоматически создаёт таблицы при первом подключении.
    """

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = (
            None
        )
        self._connect()
        self._create_tables()

    def _connect(self) -> None:
        self._connection = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        self._connection.row_factory = (
            sqlite3.Row
        )
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            "PRAGMA foreign_keys=ON"
        )

    def _create_tables(self) -> None:
        with self._lock:
            cursor = self._connection.cursor()

            cursor.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT (
                        datetime('now')
                    ),
                    updated_at TEXT NOT NULL DEFAULT (
                        datetime('now')
                    ),
                    metadata TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (
                        datetime('now')
                    ),
                    token_count INTEGER DEFAULT 0,
                    metadata TEXT DEFAULT '{}',
                    FOREIGN KEY (session_id)
                        REFERENCES sessions(session_id)
                );

                CREATE TABLE IF NOT EXISTS memories (
                    memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    source TEXT DEFAULT 'user',
                    confidence REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL DEFAULT (
                        datetime('now')
                    ),
                    updated_at TEXT NOT NULL DEFAULT (
                        datetime('now')
                    ),
                    expires_at TEXT,
                    metadata TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS background_plans (
                    background_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (
                        datetime('now')
                    )
                );

                CREATE TABLE IF NOT EXISTS proactive_events (
                    event_id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (
                        datetime('now')
                    )
                );

                CREATE TABLE IF NOT EXISTS proactive_state (
                    state_key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (
                        datetime('now')
                    )
                );

                CREATE TABLE IF NOT EXISTS tool_activity (
                    operation_id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    observed_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_memories_key
                    ON memories(key);

                CREATE INDEX IF NOT EXISTS idx_memories_category
                    ON memories(category);

                CREATE INDEX IF NOT EXISTS idx_tool_activity_observed
                    ON tool_activity(observed_at);
                """
            )

            self._connection.commit()

    def execute(
        self,
        query: str,
        parameters: tuple = (),
    ) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.execute(
                query,
                parameters,
            )

    def executemany(
        self,
        query: str,
        parameters: list[tuple],
    ) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.executemany(
                query,
                parameters,
            )

    def fetchone(
        self,
        query: str,
        parameters: tuple = (),
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                query,
                parameters,
            ).fetchone()

            if row is None:
                return None

            return dict(row)

    def fetchall(
        self,
        query: str,
        parameters: tuple = (),
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                query,
                parameters,
            ).fetchall()

            return [dict(row) for row in rows]

    def commit(self) -> None:
        with self._lock:
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            if self._connection:
                self._connection.close()
                self._connection = None
