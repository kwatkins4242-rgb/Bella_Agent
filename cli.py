"""Command line interface for Bella Memory."""

import argparse
import json
from pathlib import Path

from .persistence.memory_manager import MemoryManager


def main():
    parser = argparse.ArgumentParser(description="Bella Memory CLI")
    parser.add_argument("--session", default="default", help="Session ID")
    parser.add_argument("--storage", default="./bella_memory_data", help="Storage path")
    parser.add_argument("--config", help="Path to memory config JSON")
    sub = parser.add_subparsers(dest="command")

    chat = sub.add_parser("chat", help="Run a simple chat loop")
    clear = sub.add_parser("clear", help="Clear session memory")
    export_cmd = sub.add_parser("export", help="Export session memory to JSON")
    import_cmd = sub.add_parser("import", help="Import session memory from JSON")

    args = parser.parse_args()

    if args.config:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        manager = MemoryManager.build_from_config(args.session, config)
    else:
        manager = MemoryManager(session_id=args.session, storage_path=args.storage)

    if args.command == "clear":
        manager.clear()
        print(f"Cleared memory for session {args.session}")
    elif args.command == "export":
        state = manager.memory.to_dict()
        out_path = Path(args.storage) / f"{args.session}_export.json"
        out_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(f"Exported to {out_path}")
    elif args.command == "import":
        in_path = Path(args.storage) / f"{args.session}_export.json"
        manager.restore(str(in_path))
        print(f"Restored from {in_path}")
    elif args.command == "chat" or args.command is None:
        print(f"Bella Memory chat | session={args.session}")
        while True:
            try:
                user_input = input("You: ")
            except EOFError:
                break
            if user_input.lower() in {"exit", "quit"}:
                break
            context = manager.load_memory_variables({"input": user_input})
            print(f"[memory context keys] {list(context.keys())}")
            ai = "(Connect to your LLM endpoint)"
            print(f"Bella: {ai}")
            manager.add_exchange(user_input, ai)


if __name__ == "__main__":
    main()
