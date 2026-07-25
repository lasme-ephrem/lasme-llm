import asyncio
from typing import Dict, Any, List
from coding.subagents.manager import subagent_manager

async def async_tool_invoke_subagent(role: str, prompt: str, tools_schema: List[Dict[str, Any]], tools_map: Dict[str, Any]) -> str:
    """Spawns and executes a subagent asynchronously."""
    instance = subagent_manager.create_subagent(role, prompt)
    result = await instance.run(tools_schema, tools_map)
    return f"Subagent [{instance.id}] ({role}) finished with result:\n{result}"

def tool_list_subagents() -> str:
    """Lists all active and historical subagents."""
    subagents = subagent_manager.list_subagents()
    if not subagents:
        return "No subagents have been launched yet."
    lines = ["Active & Recent Subagents:"]
    for s in subagents:
        lines.append(f"- ID: {s['id']} | Role: {s['role']} | Status: {s['status']} | Task: {s['task_prompt'][:60]}...")
    return "\n".join(lines)

def tool_kill_subagent(subagent_id: str) -> str:
    """Kills a specific subagent."""
    success = subagent_manager.kill_subagent(subagent_id)
    if success:
        return f"Subagent [{subagent_id}] terminated."
    return f"Error: Subagent [{subagent_id}] not found."

SUBAGENT_TOOLS_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "invoke_subagent",
            "description": "Invokes a specialized subagent to handle a subtask (researcher, coder, or debugger).",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": ["researcher", "coder", "debugger"],
                        "description": "Role of the subagent: 'researcher' for read-only exploration, 'coder' for code editing, 'debugger' for testing & terminal."
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Clear instructions for the subagent."
                    }
                },
                "required": ["role", "prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_subagents",
            "description": "Lists all active and past subagents and their current statuses.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kill_subagent",
            "description": "Terminates a subagent by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subagent_id": {"type": "string", "description": "ID of the subagent to kill (e.g. 'sub-a1b2c3')."}
                },
                "required": ["subagent_id"]
            }
        }
    }
]
