"""
ODIN Engine - The Brain
Infinite loop orchestration. Reads from config.json only.
Routes through planner → reasoning → coder → verifier via the router.
"""

import json
import asyncio
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, AsyncGenerator

from router import get_router
from db import get_db
from permissions import PermissionGate
from mcp_tools import MCPToolExecutor

logger = logging.getLogger("odin.engine")

CONFIG_PATH = Path(__file__).parent.parent / "config.json"


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


class TaskState:
    """JSON-serializable state passed between all roles."""

    def __init__(self, goal: str, session_id: str):
        self.session_id = session_id
        self.task_id = str(uuid.uuid4())
        self.goal = goal
        self.created_at = datetime.utcnow().isoformat()
        self.status = "pending"  # pending | planning | reasoning | coding | verifying | complete | failed
        self.plan_steps: list = []
        self.reasoning_notes: str = ""
        self.code_output: str = ""
        self.verification_result: dict = {}
        self.tool_calls: list = []
        self.context: list = []  # full message history
        self.iteration: int = 0
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        return self.__dict__

    def to_context_summary(self) -> str:
        return json.dumps({
            "goal": self.goal,
            "status": self.status,
            "plan_steps": self.plan_steps,
            "reasoning_notes": self.reasoning_notes,
            "code_output": self.code_output[:2000] if self.code_output else "",
            "tool_calls": self.tool_calls[-5:],
            "iteration": self.iteration,
        }, indent=2)


class OdinEngine:
    """
    The infinite orchestration loop.
    All role → provider assignments come from the router (set via dashboard).
    No model names, no API keys, no providers are hardcoded here.
    """

    def __init__(self, stream_callback=None, permission_gate: PermissionGate = None):
        self.config = load_config()
        self.router = get_router()
        self.db = get_db()
        self.permission_gate = permission_gate or PermissionGate()
        self.stream_callback = stream_callback  # async fn(role, text_chunk)
        self.running = False
        self._current_task: Optional[TaskState] = None
        self.mcp_tools = MCPToolExecutor()  # ← MCP tool connection

        engine_cfg = self.config["odin"]["engine"]
        self.max_iterations = engine_cfg.get("max_loop_iterations", 50)
        self.loop_sleep = engine_cfg.get("loop_sleep_seconds", 1)

    async def _stream(self, role: str, text: str):
        """Send text to the dashboard stream."""
        if self.stream_callback:
            await self.stream_callback(role, text)

    async def _llm(self, role: str, messages: list) -> str:
        """Call the router for a role, collect full response, stream chunks."""
        full_response = ""
        await self._stream(role, f"\n[{role.upper()}] thinking...\n")
        async for chunk in self.router.chat(role, messages, stream=True):
            full_response += chunk
            await self._stream(role, chunk)
        return full_response

    async def _plan(self, state: TaskState) -> list:
        """Planner role: break the goal into numbered steps."""
        state.status = "planning"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are ODIN's Planner. Your job is to decompose the user's goal "
                    "into clear, numbered, actionable steps. Output ONLY a JSON array of step strings. "
                    "No preamble, no explanation. Example: [\"Step 1: ...\", \"Step 2: ...\"]"
                ),
            },
            {
                "role": "user",
                "content": f"GOAL: {state.goal}\n\nGenerate the execution plan as a JSON array.",
            },
        ]
        response = await self._llm("planner", messages)
        try:
            # Extract JSON array from response
            start = response.find("[")
            end = response.rfind("]") + 1
            if start != -1 and end > start:
                steps = json.loads(response[start:end])
                return steps
        except json.JSONDecodeError:
            pass
        # Fallback: treat each line as a step
        return [line.strip() for line in response.split("\n") if line.strip()]

    async def _reason(self, state: TaskState) -> str:
        """Reasoning role: deep analysis given the plan and current state."""
        state.status = "reasoning"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are ODIN's Reasoning engine. Analyze the goal and plan, "
                    "identify edge cases, risks, and the best approach. "
                    "Think step by step. Be thorough."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"GOAL: {state.goal}\n\n"
                    f"PLAN:\n{json.dumps(state.plan_steps, indent=2)}\n\n"
                    f"Provide your analysis and reasoning for executing this plan."
                ),
            },
        ]
        return await self._llm("reasoning", messages)

    async def _execute_loop(self, state: TaskState) -> str:
        """
        Main execution loop: orchestrator drives coder + tool use until COMPLETE.
        Passes full state as context so nothing is lost.
        """
        state.status = "coding"

        system_prompt = (
            "You are ODIN, an autonomous agent executing a task. "
            "You have access to tools via XML tags. "
            "When you need to run a shell command: <tool>shell_run</tool><params>{\"command\": \"ls\"}</params>\n"
            "When you need to write a file: <tool>file_write</tool><params>{\"path\": \"file.py\", \"content\": \"...\"}</params>\n"
            "When you need to read a file: <tool>file_read</tool><params>{\"path\": \"file.py\"}</params>\n"
            "When you need git operations: <tool>git_commit</tool><params>{\"message\": \"feat: ...\"}</params>\n"
            "When you need to query MongoDB: <tool>mongo_query</tool><params>{\"collection\": \"...\", \"query\": {}}</params>\n"
            "When the task is fully complete: output <COMPLETE> on its own line.\n"
            "Only call tools when necessary. Always explain what you're doing."
        )

        state.context = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"TASK GOAL: {state.goal}\n\n"
                    f"PLAN TO FOLLOW:\n{json.dumps(state.plan_steps, indent=2)}\n\n"
                    f"REASONING NOTES:\n{state.reasoning_notes}\n\n"
                    "Begin execution. Use tools as needed. Output <COMPLETE> when done."
                ),
            },
        ]

        while state.iteration < self.max_iterations:
            state.iteration += 1
            await self._stream("engine", f"\n--- Iteration {state.iteration} ---\n")

            # Call the coder role
            response = await self._llm("coder", state.context)
            state.context.append({"role": "assistant", "content": response})

            # Check for completion
            if "<COMPLETE>" in response:
                await self._stream("engine", "\n[ENGINE] Task marked COMPLETE by coder.\n")
                return response

            # Check for tool calls
            if "<tool>" in response:
                tool_result = await self._handle_tool_call(response, state)
                state.context.append({
                    "role": "user",
                    "content": f"TOOL_RESULT: {tool_result}"
                })
                state.tool_calls.append({
                    "iteration": state.iteration,
                    "response_snippet": response[:200],
                    "result_snippet": str(tool_result)[:200],
                    "timestamp": datetime.utcnow().isoformat(),
                })
            else:
                # No tool call, no COMPLETE — continue with orchestrator guidance
                state.context.append({
                    "role": "user",
                    "content": (
                        "Continue with the next step. If you need tools, use the XML format. "
                        "Output <COMPLETE> when the entire task is done."
                    ),
                })

            await asyncio.sleep(self.loop_sleep)

        raise TimeoutError(f"Max iterations ({self.max_iterations}) reached without COMPLETE.")

    async def _handle_tool_call(self, response: str, state: TaskState) -> str:
        """Parse tool XML, gate permission, execute via MCP server."""
        import re

        tool_match = re.search(r"<tool>(.*?)</tool>", response, re.DOTALL)
        params_match = re.search(r"<params>(.*?)</params>", response, re.DOTALL)

        if not tool_match:
            return "ERROR: Could not parse tool name from response."

        tool_name = tool_match.group(1).strip()
        params_str = params_match.group(1).strip() if params_match else "{}"

        try:
            params = json.loads(params_str)
        except json.JSONDecodeError:
            params = {"raw": params_str}

        await self._stream("permissions", f"\n[PERMISSION REQUEST] Tool: {tool_name} | Params: {params_str}\n")

        # Permission gate — deny-first
        allowed = await self.permission_gate.request(
            tool_name=tool_name,
            params=params,
            context=f"Iteration {state.iteration} | Goal: {state.goal[:100]}"
        )

        if not allowed:
            result = f"DENIED: User rejected execution of '{tool_name}'."
            await self._stream("permissions", f"[DENIED] {tool_name}\n")
            return result

        # Execute via MCP
        await self._stream("engine", f"[EXECUTING] {tool_name}({params_str})\n")
        result = await self._call_mcp(tool_name, params)
        await self._stream("engine", f"[RESULT] {str(result)[:500]}\n")
        return result

    async def _call_mcp(self, tool_name: str, params: dict) -> str:
        """Call the MCP tool executor - now with REAL tool connections!"""
        try:
            # Route to appropriate MCP tool method
            tool_map = {
                "shell_run": self.mcp_tools.shell_run,
                "shell_run_local": self.mcp_tools.shell_run_local,
                "shell_background": self.mcp_tools.shell_background,
                "file_read": self.mcp_tools.file_read,
                "file_read_local": self.mcp_tools.file_read_local,
                "file_write": self.mcp_tools.file_write,
                "file_write_local": self.mcp_tools.file_write_local,
                "file_list": self.mcp_tools.file_list,
                "file_search": self.mcp_tools.file_search,
                "memory_search": self.mcp_tools.memory_search,
                "memory_save": self.mcp_tools.memory_save,
                "memory_recall": self.mcp_tools.memory_recall,
                "memory_graph_query": self.mcp_tools.memory_graph_query,
                "n8n_trigger": self.mcp_tools.n8n_trigger,
                "n8n_handoff": self.mcp_tools.n8n_handoff,
                "odin_chat": self.mcp_tools.odin_chat,
                "odin_auto": self.mcp_tools.odin_auto,
                "odin_code": self.mcp_tools.odin_code,
                "health_check": self.mcp_tools.health_check,
                "http_post": self.mcp_tools.http_post,
                "http_get": self.mcp_tools.http_get,
            }

            tool_fn = tool_map.get(tool_name)
            if not tool_fn:
                # Fallback: call generic tool method
                result = await self.mcp_tools.call_tool(tool_name, params)
                return json.dumps(result, indent=2)

            # Call the specific tool method
            result = await tool_fn(**params)

            if result.get("success"):
                return json.dumps(result.get("result", result), indent=2)
            else:
                return f"ERROR: {result.get('error', 'Unknown error')}"

        except Exception as e:
            logger.error(f"MCP tool call failed: {tool_name} → {e}")
            return f"MCP ERROR: {str(e)}"

    async def _verify(self, state: TaskState, execution_output: str) -> dict:
        """Verifier role: check execution output against original plan steps."""
        state.status = "verifying"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are ODIN's Verifier. Check whether the execution output "
                    "satisfies every step in the original plan. "
                    "Respond in JSON: {\"passed\": true/false, \"steps_verified\": [], \"steps_failed\": [], \"notes\": \"\"}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"ORIGINAL GOAL: {state.goal}\n\n"
                    f"PLANNED STEPS:\n{json.dumps(state.plan_steps, indent=2)}\n\n"
                    f"EXECUTION OUTPUT (last 3000 chars):\n{execution_output[-3000:]}\n\n"
                    "Did the execution satisfy all planned steps? Respond with the JSON."
                ),
            },
        ]
        response = await self._llm("verifier", messages)
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(response[start:end])
        except json.JSONDecodeError:
            pass
        return {"passed": False, "notes": f"Could not parse verifier response: {response[:500]}"}

    async def _git_commit(self, state: TaskState):
        """Auto git commit+push on task completion."""
        cfg = self.config["odin"]["git"]
        if not cfg.get("auto_commit"):
            return
        await self._call_mcp("git_commit", {
            "message": f"odin: task complete [{state.task_id[:8]}] - {state.goal[:60]}"
        })
        if cfg.get("auto_push"):
            await self._call_mcp("shell_run", {"command": "git push"})

    async def run_task(self, goal: str, session_id: str) -> AsyncGenerator[dict, None]:
        """
        Full task pipeline: plan → reason → execute → verify → commit.
        Yields status events for the dashboard stream.
        """
        self.running = True
        state = TaskState(goal=goal, session_id=session_id)
        self._current_task = state

        # Log task start to MongoDB
        await self.db.log_task_start(state)

        try:
            yield {"event": "start", "task_id": state.task_id, "goal": goal}

            # 1. Plan
            await self._stream("planner", f"[PLANNER] Breaking down: {goal}\n")
            state.plan_steps = await self._plan(state)
            yield {"event": "plan", "steps": state.plan_steps}
            await self.db.log_event(state, "plan_complete", {"steps": state.plan_steps})

            # 2. Reason
            await self._stream("reasoning", "[REASONING] Analyzing plan...\n")
            state.reasoning_notes = await self._reason(state)
            yield {"event": "reasoning_complete"}
            await self.db.log_event(state, "reasoning_complete", {})

            # 3. Execute
            await self._stream("coder", "[CODER] Starting execution loop...\n")
            execution_output = await self._execute_loop(state)
            state.code_output = execution_output
            yield {"event": "execution_complete"}
            await self.db.log_event(state, "execution_complete", {})

            # 4. Verify
            await self._stream("verifier", "[VERIFIER] Checking output against plan...\n")
            verification = await self._verify(state, execution_output)
            state.verification_result = verification
            yield {"event": "verification", "result": verification}
            await self.db.log_event(state, "verification", verification)

            if not verification.get("passed"):
                await self._stream("engine", f"[ENGINE] Verification failed: {verification.get('notes')}\n")
                yield {"event": "warning", "message": "Verification did not fully pass. Review logs."}

            # 5. Git commit
            await self._git_commit(state)

            state.status = "complete"
            yield {"event": "complete", "state": state.to_dict()}
            await self.db.log_task_complete(state)

        except Exception as e:
            state.status = "failed"
            state.error = str(e)
            logger.error(f"Task failed: {e}", exc_info=True)
            await self._stream("engine", f"\n[ERROR] {str(e)}\n")
            yield {"event": "error", "message": str(e)}
            await self.db.log_event(state, "error", {"error": str(e)})
        finally:
            self.running = False
            self._current_task = None

    def get_status(self) -> dict:
        if self._current_task:
            return {
                "running": self.running,
                "task_id": self._current_task.task_id,
                "status": self._current_task.status,
                "iteration": self._current_task.iteration,
                "goal": self._current_task.goal,
            }
        return {"running": False}

    def get_role_assignments(self) -> dict:
        return self.router.get_assignments()

    def assign_role(self, role: str, provider: str, model: str):
        self.router.assign_role(role, provider, model)
