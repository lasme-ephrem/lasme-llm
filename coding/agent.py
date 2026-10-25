import json
import logging
from typing import Dict, Any, Callable, Optional
from core.inference.client import LasmeLLMClient
from core.config import settings
from coding.tools.fs_tools import (
    tool_list_dir,
    tool_get_file_tree,
    tool_view_file,
    tool_write_file,
    tool_replace_file_content,
    tool_move_file,
    tool_delete_file,
    tool_grep_search,
    CODING_TOOLS_SCHEMAS
)
from coding.tools.terminal_tools import tool_run_command, TERMINAL_TOOL_SCHEMA
from coding.tools.git_tools import tool_git_status, tool_git_diff, tool_git_log, GIT_TOOLS_SCHEMAS
from coding.tools.subagent_tools import (
    async_tool_invoke_subagent,
    tool_list_subagents,
    tool_kill_subagent,
    SUBAGENT_TOOLS_SCHEMAS
)

logger = logging.getLogger("LasmeCodingAgent")

SYSTEM_PROMPT = """You are LasmeLLMCoding, an elite autonomous agentic software engineering assistant.
You operate like Google Antigravity / OpenAI Codex IDEs.

Your goal is to inspect codebases, form implementation plans, edit files cleanly, execute terminal commands/tests, and delegate subtasks to specialized subagents.

Architecture & Rules:
1. EXPLORE FIRST: Use `get_file_tree`, `list_dir`, `view_file`, or `grep_search` to understand the codebase layout before taking action.
2. EDIT PRECISELY: Use `replace_file_content` for surgical updates, or `write_file` for new files.
3. VERIFY WITH TERMINAL: Run linters, unit tests, or build commands via `run_command` after code modifications.
4. SUBAGENT DELEGATION: For multi-step or independent tasks, invoke subagents using `invoke_subagent` with appropriate roles (`researcher`, `coder`, `debugger`).
5. GIT CONTROL: Check status or diffs using `git_status` and `git_diff` whenever appropriate.
"""

class LasmeCodingAgent:
    def __init__(self, model_name: str = settings.coding_model):
        self.client = LasmeLLMClient()
        self.model = model_name
        tools_schema = (
            CODING_TOOLS_SCHEMAS
            + ([TERMINAL_TOOL_SCHEMA] if settings.agent_terminal_enabled else [])
            + GIT_TOOLS_SCHEMAS
            + SUBAGENT_TOOLS_SCHEMAS
        )
        if not settings.allow_destructive_agent_tools:
            tools_schema = [
                schema
                for schema in tools_schema
                if schema.get("function", {}).get("name")
                not in {"delete_file", "move_file"}
            ]
        self.tools_schema = tools_schema

        # Direct synchronous/async handler registry
        self.tools_map: Dict[str, Callable] = {
            "list_dir": tool_list_dir,
            "get_file_tree": tool_get_file_tree,
            "view_file": tool_view_file,
            "write_file": tool_write_file,
            "replace_file_content": tool_replace_file_content,
            "move_file": tool_move_file,
            "delete_file": tool_delete_file,
            "grep_search": tool_grep_search,
            "run_command": tool_run_command,
            "git_status": tool_git_status,
            "git_diff": tool_git_diff,
            "git_log": tool_git_log,
            "list_subagents": tool_list_subagents,
            "kill_subagent": tool_kill_subagent
        }
        if not settings.agent_terminal_enabled:
            self.tools_map.pop("run_command", None)
        if not settings.allow_destructive_agent_tools:
            self.tools_map.pop("delete_file", None)
            self.tools_map.pop("move_file", None)

    async def execute_task(self, user_prompt: str, callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None) -> str:
        """Executes a coding task agentically using ReAct loop with multi-agent delegation."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        max_steps = 20
        for step in range(max_steps):
            if callback:
                callback("status", f"Step {step+1}/{max_steps}: Reasoning...", {"step": step + 1})

            response = await self.client.chat(
                model=self.model,
                messages=messages,
                tools=self.tools_schema,
                temperature=0.1,
                stream=False
            )

            msg = response.get("message", {})
            messages.append(msg)

            content = msg.get("content", "")
            if content and callback:
                callback("thought", content, {"step": step + 1})

            tool_calls = msg.get("tool_calls", [])

            # Fallback JSON parsing if model outputs tool call in content string
            if not tool_calls and content.strip().startswith("{") and "arguments" in content:
                try:
                    parsed_tool = json.loads(content.strip())
                    if "name" in parsed_tool and "arguments" in parsed_tool:
                        tool_calls = [{"function": parsed_tool}]
                except Exception:
                    pass

            if not tool_calls:
                # No more tool calls required
                return content or "Task finished successfully."

            # Execute tool calls
            for tool_call in tool_calls:
                func_info = tool_call.get("function", {})
                func_name = func_info.get("name")
                arguments = func_info.get("arguments", {})

                if callback:
                    callback("tool_call", f"Invoking tool `{func_name}`", {"name": func_name, "args": arguments})

                # Special handler for invoke_subagent
                if func_name == "invoke_subagent":
                    role = arguments.get("role", "researcher")
                    prompt = arguments.get("prompt", "")
                    result = await async_tool_invoke_subagent(role, prompt, self.tools_schema, self.tools_map)
                else:
                    handler = self.tools_map.get(func_name)
                    if handler:
                        try:
                            result = handler(**arguments)
                        except Exception as e:
                            result = f"Error executing tool `{func_name}`: {str(e)}"
                    else:
                        result = f"Error: Tool `{func_name}` not recognized."

                if callback:
                    callback("tool_result", f"Result from `{func_name}`", {"name": func_name, "result": str(result)[:600]})

                messages.append({
                    "role": "tool",
                    "content": str(result),
                    "name": func_name
                })

        return "Task completed maximum step limit."
