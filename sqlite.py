"""SQLite backed chat history."""

import json
import sqlite3
from pathlib import Path
from typing import List

from ..core.base_chat_message_history import BaseChatMessageHistory
from ..core.messages import BaseMessage, messages_from_dict, messages_to_dict


class SQLiteChatMessageHistory(BaseChatMessageHistory):
    """Chat history persisted to SQLite."""

    def __init__(
        self,
        session_id: str,
        connection_string: str = "sqlite:///memory.db",
        table_name: str = "message_store",
    ) -> None:
        self.session_id = session_id
        self.table_name = table_name
        if connection_string.startswith("sqlite:///"):
            self.db_path = connection_string[len("sqlite:///") :]
        else:
            self.db_path = connection_string
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._create_table()

    def _connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _create_table(self) -> None:
        with self._connection() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    message TEXT NOT NULL
                )
                """
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_session
                ON {self.table_name}(session_id)
                """
            )

    def add_message(self, message: BaseMessage) -> None:
        with self._connection() as conn:
            conn.execute(
                f"INSERT INTO {self.table_name} (session_id, message) VALUES (?, ?)",
                (self.session_id, json.dumps(message.to_dict(), ensure_ascii=False)),
            )

    def get_messages(self) -> List[BaseMessage]:
        with self._connection() as conn:
            cursor = conn.execute(
                f"SELECT message FROM {self.table_name} WHERE session_id = ? ORDER BY id ASC",
                (self.session_id,),
            )
            rows = cursor.fetchall()
        return messages_from_dict([json.loads(row[0]) for row in rows])

    def clear(self) -> None:
        with self._connection() as conn:
            conn.execute(
                f"DELETE FROM {self.table_name} WHERE session_id = ?",
                (self.session_id,),
            )
