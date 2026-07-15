#!/usr/bin/env python3
"""
Backend Parser — port 8002.
Simple FastAPI service that parses user intent, extracts entities, and routes
tasks to the loop (8001) or Bella (8000).
"""
import os
import json
import re
import logging
import httpx
from typing import List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/env/ENV"))
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backend.parser")

PARSER_PORT = int(os.getenv("BACKEND_PARSER_PORT", "8002"))
LOOP_URL    = os.getenv("LOOP_URL", "http://127.0.0.1:8001")
BELLA_URL   = os.getenv("BELLA_URL", "http://127.0.0.1:8000")

app = FastAPI(title="ODIN Parser", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ParseRequest(BaseModel):
    message: str
    session_id: str = "default"


class ParsedIntent(BaseModel):
    intent: str
    entities: dict
    confidence: float
    destination: str
    reply: str


INTENT_PATTERNS = [
    ("code", r"\b(write|create|generate|build|fix|debug|refactor)\b.*\b(code|script|function|app|api)\b"),
    ("file", r"\b(read|write|edit|delete|list|find|search)\b.*\b(file|folder|directory)\b"),
    ("shell", r"\b(run|execute|shell|command|terminal|cmd)\b"),
    ("memory", r"\b(remember|recall|memory|what did we|search memory)\b"),
    ("chat", r".*"),
]


def parse_intent(message: str) -> dict:
    lowered = message.lower()
    for intent, pattern in INTENT_PATTERNS:
        if re.search(pattern, lowered):
            entities = {
                "files": re.findall(r"[\w\-\/]+\.(py|js|json|md|txt|html|css|sh)", message),
                "urls": re.findall(r"https?://\S+", message),
                "session_id": "default",
            }
            return {
                "intent": intent,
                "entities": entities,
                "confidence": 0.8 if intent != "chat" else 0.4,
            }
    return {"intent": "chat", "entities": {}, "confidence": 0.4}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "parser", "port": PARSER_PORT}


@app.post("/parse", response_model=ParsedIntent)
async def parse(req: ParseRequest):
    parsed = parse_intent(req.message)
    intent = parsed["intent"]
    destination = "loop" if intent in {"code", "shell", "file"} else "bella"

    return ParsedIntent(
        intent=intent,
        entities=parsed["entities"],
        confidence=parsed["confidence"],
        destination=destination,
        reply=f"Routing to {destination} as {intent} task."
    )


@app.post("/route")
async def route(req: ParseRequest):
    parsed = await parse(req)
    target_url = f"{LOOP_URL}/api/chat" if parsed.destination == "loop" else f"{BELLA_URL}/v1/chat"
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                target_url,
                json={"message": req.message, "session_id": req.session_id},
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
            return {"parsed": parsed.dict(), "response": data}
    except Exception as e:
        logger.error(f"Routing failed: {e}")
        return {"parsed": parsed.dict(), "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Parser starting on 0.0.0.0:{PARSER_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PARSER_PORT)
