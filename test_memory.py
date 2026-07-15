import pytest

from bella_memory.core.messages import AIMessage, HumanMessage
from bella_memory.history.in_memory import ChatMessageHistory
from bella_memory.memory.buffer import ConversationBufferMemory
from bella_memory.memory.buffer_window import ConversationBufferWindowMemory
from bella_memory.memory.combined import CombinedMemory
from bella_memory.memory.entity import ConversationEntityMemory
from bella_memory.memory.kg import ConversationKGMemory
from bella_memory.memory.summary import ConversationSummaryMemory
from bella_memory.memory.vectorstore import VectorStoreRetrieverMemory
from bella_memory.vectorstore.in_memory import InMemoryVectorStore


def test_buffer_memory():
    history = ChatMessageHistory()
    memory = ConversationBufferMemory(
        chat_memory=history, human_prefix="Charles", ai_prefix="Bella"
    )
    memory.save_context({"input": "hi"}, {"output": "hello"})
    assert "Charles: hi" in memory.load_memory_variables()["history"]
    assert "Bella: hello" in memory.load_memory_variables()["history"]


def test_buffer_window_memory():
    memory = ConversationBufferWindowMemory(k=1)
    memory.save_context({"input": "1"}, {"output": "a"})
    memory.save_context({"input": "2"}, {"output": "b"})
    memory.save_context({"input": "3"}, {"output": "c"})
    history = memory.load_memory_variables()["history"]
    assert "1" not in history
    assert "3" in history


def test_summary_memory(fake_llm):
    fake_llm.responses = {"Progressively summarize": "Summary of chat."}
    memory = ConversationSummaryMemory(llm=fake_llm)
    memory.save_context({"input": "hi"}, {"output": "hello"})
    assert memory.buffer == "Summary of chat."
    assert "Summary of chat." in memory.load_memory_variables()["history"]


def test_entity_memory(fake_llm):
    fake_llm.responses = {
        "Extract all entities": '["Charles", "Bella"]',
        "Known fact": "Charles is the user.",
    }
    memory = ConversationEntityMemory(llm=fake_llm)
    memory.save_context({"input": "I am Charles."}, {"output": "Nice to meet you Charles."})
    assert "Charles" in memory.entity_store


def test_kg_memory(fake_llm):
    fake_llm.responses = {
        "knowledge graph extraction": '[["Charles", "has_daughter", "Emma"]]',
    }
    memory = ConversationKGMemory(llm=fake_llm)
    memory.save_context(
        {"input": "My daughter Emma loves horses."},
        {"output": "That is wonderful."},
    )
    triples = memory.get_knowledge_triples()
    assert any(t == ("Charles", "has_daughter", "Emma") for t in triples)


def test_vectorstore_memory():
    vectorstore = InMemoryVectorStore()
    memory = VectorStoreRetrieverMemory(vectorstore=vectorstore, k=2)
    memory.save_context({"input": "I live in Weatherford, TX."}, {"output": "Got it."})
    result = memory.load_memory_variables({"input": "Where do I live?"})
    assert "Weatherford" in result["history"]


def test_combined_memory(fake_llm):
    fake_llm.responses = {"Progressively summarize": "Summary."}
    buffer = ConversationBufferMemory(return_messages=True)
    summary = ConversationSummaryMemory(llm=fake_llm)
    combined = CombinedMemory(memories=[buffer, summary])
    combined.save_context({"input": "hi"}, {"output": "hello"})
    vars = combined.load_memory_variables()
    assert "history" in vars
