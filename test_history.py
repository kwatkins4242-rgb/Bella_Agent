import os
import tempfile

from bella_memory.core.messages import AIMessage, HumanMessage
from bella_memory.history.file import FileChatMessageHistory
from bella_memory.history.in_memory import ChatMessageHistory
from bella_memory.history.sqlite import SQLiteChatMessageHistory


def test_in_memory_history():
    history = ChatMessageHistory()
    history.add_user_message("hello")
    history.add_ai_message("hi there")
    assert len(history) == 2
    assert isinstance(history.messages[0], HumanMessage)


def test_file_history(tmp_path):
    path = tmp_path / "history.json"
    history = FileChatMessageHistory(path)
    history.add_message(HumanMessage(content="hi"))
    history.add_message(AIMessage(content="hey"))
    del history
    restored = FileChatMessageHistory(path)
    assert len(restored) == 2


def test_sqlite_history(tmp_path):
    db = tmp_path / "db.sqlite"
    history = SQLiteChatMessageHistory("s1", connection_string=f"sqlite:///{db}")
    history.add_message(HumanMessage(content="a"))
    history.add_message(AIMessage(content="b"))
    assert len(history.get_messages()) == 2
    history.clear()
    assert len(history.get_messages()) == 0
