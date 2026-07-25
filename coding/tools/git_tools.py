import subprocess
from pathlib import Path
from typing import Dict, Any, List

def tool_git_status(path: str = ".") -> str:
    """Gets current git status of the workspace."""
    try:
        res = subprocess.run(["git", "status", "-s"], cwd=path, capture_output=True, text=True, timeout=10)
        output = res.stdout.strip()
        return output if output else "Git status clean (no modified/untracked files)."
    except Exception as e:
        return f"Error executing git status: {str(e)}"

def tool_git_diff(path: str = ".") -> str:
    """Gets working directory git diff."""
    try:
        res = subprocess.run(["git", "diff"], cwd=path, capture_output=True, text=True, timeout=15)
        output = res.stdout.strip()
        if not output:
            return "No unstaged git diff."
        if len(output) > 4000:
            return output[:4000] + "\n\n...[git diff truncated]..."
        return output
    except Exception as e:
        return f"Error executing git diff: {str(e)}"

def tool_git_log(max_count: int = 5, path: str = ".") -> str:
    """Gets recent git commits log."""
    try:
        res = subprocess.run(["git", "log", f"-n{max_count}", "--oneline"], cwd=path, capture_output=True, text=True, timeout=10)
        output = res.stdout.strip()
        return output if output else "No git commit history found."
    except Exception as e:
        return f"Error executing git log: {str(e)}"

GIT_TOOLS_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Returns current git working directory status (modified, untracked files).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace directory path (default '.')."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Returns unstaged git diff changes in the codebase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace directory path (default '.')."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Returns recent git commit history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_count": {"type": "integer", "description": "Number of recent commits to fetch (default 5)."},
                    "path": {"type": "string", "description": "Workspace directory path (default '.')."}
                }
            }
        }
    }
]
