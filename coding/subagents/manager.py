import uuid
import asyncio
import logging
from typing import Dict, Any, List, Optional
from core.inference.client import LasmeLLMClient
from core.config import settings

logger = logging.getLogger("SubagentManager")

SUBAGENT_ROLES = {
    "researcher": {
        "title": "Codebase Researcher",
        "description": "Explores the codebase structure, reads files, runs grep searches, and gathers context without modifying files.",
        "system_prompt": """You are Subagent Researcher. Your sole role is to inspect the codebase, search for symbols, read code snippets, and report comprehensive facts to the Master Agent. Do NOT attempt to edit or modify files."""
    },
    "coder": {
        "title": "Code Implementer",
        "description": "Applies precise code edits, writes new modules, and updates existing files.",
        "system_prompt": """You are Subagent Coder. Your sole role is to write clean, maintainable code and apply exact modifications to files using write_file or replace_file_content."""
    },
    "debugger": {
        "title": "Test & Terminal Debugger",
        "description": "Runs terminal commands, linters, and unit tests to verify changes and diagnose errors.",
        "system_prompt": """You are Subagent Debugger. Your sole role is to run tests, linters, and commands via run_command, inspect output logs, and report runtime findings."""
    }
}

ROLE_TOOLS = {
    "researcher": {
        "list_dir", "get_file_tree", "view_file", "grep_search",
        "git_status", "git_diff", "git_log",
    },
    "coder": {
        "list_dir", "get_file_tree", "view_file", "grep_search",
        "write_file", "replace_file_content",
        "git_status", "git_diff",
    },
    "debugger": {
        "list_dir", "get_file_tree", "view_file", "grep_search",
        "run_command", "git_status", "git_diff", "git_log",
    },
}

class SubagentInstance:
    def __init__(self, subagent_id: str, role: str, task_prompt: str, model_name: str = settings.coding_model):
        self.id = subagent_id
        self.role = role
        self.task_prompt = task_prompt
        self.model = model_name
        self.status = "active"  # active, completed, failed
        self.logs: List[Dict[str, Any]] = []
        self.result: Optional[str] = None
        self.client = LasmeLLMClient()

    async def run(self, tools_schema: List[Dict[str, Any]], tools_map: Dict[str, Any]) -> str:
        role_config = SUBAGENT_ROLES.get(self.role, SUBAGENT_ROLES["researcher"])
        system_prompt = role_config["system_prompt"]
        allowed_tools = ROLE_TOOLS.get(self.role, ROLE_TOOLS["researcher"])
        role_tools_schema = [
            schema
            for schema in tools_schema
            if schema.get("function", {}).get("name") in allowed_tools
        ]

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self.task_prompt}
        ]

        self.logs.append({"type": "info", "message": f"Subagent [{role_config['title']}] started."})

        max_steps = 8
        for step in range(max_steps):
            if self.status == "killed":
                self.result = "Subagent was stopped."
                return self.result
            try:
                response = await self.client.chat(
                    model=self.model,
                    messages=messages,
                    tools=role_tools_schema,
                    temperature=0.1
                )
                msg = response.get("message", {})
                messages.append(msg)

                content = msg.get("content", "")
                if content:
                    self.logs.append({"type": "thought", "message": content})

                tool_calls = msg.get("tool_calls", [])
                if not tool_calls:
                    self.status = "completed"
                    self.result = content or "Subagent task finished."
                    self.logs.append({"type": "status", "message": "Subagent completed task successfully."})
                    return self.result

                for tool_call in tool_calls:
                    func_info = tool_call.get("function", {})
                    func_name = func_info.get("name")
                    arguments = func_info.get("arguments", {})
                    if func_name not in allowed_tools:
                        res = f"Error: Tool `{func_name}` is not allowed for role `{self.role}`."
                        messages.append({
                            "role": "tool",
                            "content": res,
                            "name": func_name,
                        })
                        continue

                    self.logs.append({"type": "tool_call", "message": f"Tool `{func_name}` called with {arguments}"})

                    handler = tools_map.get(func_name)
                    if handler:
                        try:
                            res = handler(**arguments)
                        except Exception as e:
                            res = f"Error: {str(e)}"
                    else:
                        res = f"Error: Tool `{func_name}` not found."

                    self.logs.append({"type": "tool_result", "message": f"`{func_name}` -> {str(res)[:300]}"})
                    messages.append({
                        "role": "tool",
                        "content": str(res),
                        "name": func_name
                    })

            except Exception as ex:
                self.status = "failed"
                self.result = f"Error in subagent: {str(ex)}"
                self.logs.append({"type": "error", "message": self.result})
                return self.result

        self.status = "completed"
        self.result = "Subagent reached step limit."
        return self.result

class SubagentManager:
    def __init__(self):
        self.active_subagents: Dict[str, SubagentInstance] = {}

    def create_subagent(self, role: str, task_prompt: str) -> SubagentInstance:
        sub_id = f"sub-{uuid.uuid4().hex[:6]}"
        instance = SubagentInstance(sub_id, role, task_prompt)
        self.active_subagents[sub_id] = instance
        return instance

    def list_subagents(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": inst.id,
                "role": inst.role,
                "title": SUBAGENT_ROLES.get(inst.role, {}).get("title", inst.role),
                "status": inst.status,
                "task_prompt": inst.task_prompt,
                "logs_count": len(inst.logs)
            }
            for inst in self.active_subagents.values()
        ]

    def get_subagent(self, sub_id: str) -> Optional[SubagentInstance]:
        return self.active_subagents.get(sub_id)

    def kill_subagent(self, sub_id: str) -> bool:
        if sub_id in self.active_subagents:
            self.active_subagents[sub_id].status = "killed"
            return True
        return False

# Global Singleton Manager
subagent_manager = SubagentManager()
