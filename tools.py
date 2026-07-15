# app/tools.py — ODIN Tool Wrappers
# Calls tools.js via subprocess; returns clean strings to the agent loop.

import subprocess
import json
import os
from langchain_core.tools import tool

# tools.js lives in the same directory
_TOOLS_JS = os.path.join(os.path.dirname(__file__), 'tools.js')


def _run_node(action: str, path: str, extra: str = None) -> dict:
    """Execute tools.js and return parsed JSON dict."""
    cmd = ['node', _TOOLS_JS, action, path]
    if extra is not None:
        cmd.append(extra)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {'status': 'ERROR', 'payload': None, 'error': r.stdout or r.stderr}


# ── Tool 1: Workspace Parser ─────────────────────────────────────────────────
@tool
def parse_workspace(workspace_path: str) -> str:
    """
    Recursively maps a project directory. Returns a flat list of all file paths
    plus a nested tree. Run this ONCE before any read/write so you know exactly
    what exists and where. Never guess paths — always parse first.
    """
    d = _run_node('parse_workspace', workspace_path)
    if d.get('status') == 'SUCCESS':
        p = d['payload']
        # Return compact summary + flat path list (cheap on tokens)
        flat = '\n'.join(p.get('flat_paths', []))
        return f"ROOT: {p['root']}\nFILES ({p['file_count']}):\n{flat}"
    return f"ERROR: {d.get('error')}"


# ── Tool 2: Search Files ──────────────────────────────────────────────────────
@tool
def search_files(workspace_path: str, query: str) -> str:
    """
    Grep-style search across all text files in workspace_path.
    Use this instead of reading every file — returns only matching lines with
    their file path and line number. Much cheaper than bulk file reads.
    Example: search_files('/home/kwatk/Odin1', 'def run_agent')
    """
    d = _run_node('search_files', workspace_path, query)
    if d.get('status') == 'SUCCESS':
        p = d['payload']
        if not p['hits']:
            return f"No matches for '{query}' in {workspace_path}"
        lines = [f"{h['file']}:{h['line']}  {h['text']}" for h in p['hits']]
        return f"HITS ({p['hit_count']}) for '{query}':\n" + '\n'.join(lines)
    return f"ERROR: {d.get('error')}"


# ── Tool 3: Read File ─────────────────────────────────────────────────────────
@tool
def read_file(file_path: str) -> str:
    """
    Read the full content of a single file. Only use after parse_workspace
    confirms the path exists. Do not use to scan directories.
    """
    d = _run_node('read_file', file_path)
    if d.get('status') == 'SUCCESS':
        return d['payload']['content']
    return f"ERROR: {d.get('error')}"


# ── Tool 4: Write File ────────────────────────────────────────────────────────
@tool
def write_file(file_path: str, content: str) -> str:
    """
    Write or overwrite a file at file_path with content.
    Creates parent directories automatically. Returns SUCCESS or ERROR from OS.
    Never claim a file was written without calling this tool — the OS result
    is the only ground truth.
    """
    d = _run_node('write_file', file_path, content)
    if d.get('status') == 'SUCCESS':
        return f"SUCCESS: {d['payload']}"
    return f"ERROR: {d.get('error')}"
