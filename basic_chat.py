"""Basic persistent chat example."""

from bella_memory import ConversationBufferMemory
from bella_memory.history.file import FileChatMessageHistory


def main():
    history = FileChatMessageHistory("./bella_memory_data/sessions/charles.json")
    memory = ConversationBufferMemory(
        chat_memory=history,
        human_prefix="Charles",
        ai_prefix="Bella",
        return_messages=True,
    )

    print("Bella: Hello Charles! What would you like to talk about?")
    while True:
        user_input = input("Charles: ")
        if user_input.lower() in {"exit", "quit"}:
            break

        # In a real project, send memory + prompt to your LLM endpoint here.
        context = memory.load_memory_variables({"input": user_input})["history"]
        print("[context messages]", len(context))

        ai_response = f"I hear you: {user_input}"
        print(f"Bella: {ai_response}")
        memory.save_context({"input": user_input}, {"output": ai_response})


if __name__ == "__main__":
    main()
