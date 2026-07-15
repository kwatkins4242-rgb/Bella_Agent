"""Optional FastAPI service for memory operations."""

from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .persistence.memory_manager import MemoryManager

app = FastAPI(title="Bella Memory API")

managers: Dict[str, MemoryManager] = {}


class MessageRequest(BaseModel):
    session_id: str
    input: str
    output: str
    config: Optional[Dict[str, Any]] = None


class QueryRequest(BaseModel):
    session_id: str
    input: str
    config: Optional[Dict[str, Any]] = None


class FactRequest(BaseModel):
    session_id: str
    fact: str


def _get_manager(session_id: str, config: Optional[Dict[str, Any]] = None) -> MemoryManager:
    key = f"{session_id}:{id(config)}"
    if key not in managers:
        if config:
            managers[key] = MemoryManager.build_from_config(session_id, config)
        else:
            managers[key] = MemoryManager(session_id=session_id)
    return managers[key]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/memory/load")
def load_memory(req: QueryRequest):
    try:
        manager = _get_manager(req.session_id, req.config)
        return manager.load_memory_variables({"input": req.input})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/memory/save")
def save_memory(req: MessageRequest):
    try:
        manager = _get_manager(req.session_id, req.config)
        manager.add_exchange(req.input, req.output)
        return {"status": "saved"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/memory/fact")
def add_fact(req: FactRequest):
    try:
        manager = _get_manager(req.session_id)
        manager.add_user_fact(req.fact)
        return {"status": "fact_added"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/memory/clear")
def clear_memory(req: QueryRequest):
    try:
        manager = _get_manager(req.session_id, req.config)
        manager.clear()
        return {"status": "cleared"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
