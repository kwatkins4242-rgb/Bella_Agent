"""Summary memory example using remote Ollama."""

import os

from bella_memory import ConversationSummaryMemory
from bella_memory.history.file import FileChatMessageHistory
from bella_memory.llm.ollama_llm import OllamaLLM


def main():
    llm = OllamaLLM(
        model=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://100.58.95.110:11434"),
    )
    history = FileChatMessageHistory("./bella_memory_data/sessions/charles_summary.json")
    memory = ConversationSummaryMemory(llm=llm, chat_memory=history)

    print("Bella: Hey Charles. Ready to chat.")
    while True:
        user_input = input("Charles: ")
        if user_input.lower() in {"exit", "quit"}:
            break

        print("Summary so far:", memory.buffer)
        ai_response = "(Connect this to your LLM endpoint.)"
        print(f"Bella: {ai_response}")
        memory.save_context({"input": user_input}, {"output": ai_response})


if __name__ == "__main__":
    main()
