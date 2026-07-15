from bella_memory.core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    messages_from_dict,
    messages_to_dict,
)


def test_message_serialization():
    messages = [
        HumanMessage(content="hi"),
        AIMessage(content="hello"),
        SystemMessage(content="be kind"),
    ]
    data = messages_to_dict(messages)
    restored = messages_from_dict(data)
    assert len(restored) == 3
    assert restored[0].content == "hi"
    assert restored[1].type == "ai"
    assert restored[2].type == "system"


def test_base_message_from_dict():
    msg = BaseMessage.from_dict({"type": "human", "content": "test"})
    assert isinstance(msg, HumanMessage)
    assert msg.content == "test"
