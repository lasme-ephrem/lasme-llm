import subprocess
import os
import shlex
from pathlib import Path
from typing import Dict, Any
from core.config import settings
from core.security import resolve_workspace_path, SecurityError


SHELL_CONTROL_TOKENS = {"|", "||", "&&", ";", ">", ">>", "<", "2>", "2>>"}


def _parse_safe_command(command: str) -> list[str]:
    if not command or not command.strip():
        raise SecurityError("Command is empty.")
    if any(token in command for token in ("\r", "\n", "`", "$(", "${")):
        raise SecurityError("Shell expansion and multiline commands are not allowed.")

    parts = shlex.split(command, posix=False)
    if not parts:
        raise SecurityError("Command is empty.")
    if any(part in SHELL_CONTROL_TOKENS for part in parts):
        raise SecurityError("Shell pipelines and redirections are not allowed.")

    executable = Path(parts[0].strip('"')).name.lower()
    allowed = {
        item.strip().lower()
        for item in settings.allowed_commands.split(",")
        if item.strip()
    }
    if executable not in allowed:
        raise SecurityError(
            f"Command '{executable}' is not in LASME_ALLOWED_COMMANDS."
        )
    return [part.strip('"') for part in parts]

def tool_run_command(command: str, cwd: str = ".") -> str:
    """Runs an allow-listed command inside the configured workspace."""
    try:
        working_dir = resolve_workspace_path(cwd)
        args = _parse_safe_command(command)
        result = subprocess.run(
            args,
            shell=False,
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
        output = []
        if result.stdout:
            output.append(f"STDOUT:\n{result.stdout.strip()}")
        if result.stderr:
            output.append(f"STDERR:\n{result.stderr.strip()}")
        output.append(f"Exit Code: {result.returncode}")
        
        return "\n\n".join(output) if output else "Command executed with no output."
    except subprocess.TimeoutExpired:
        return "Error: Command execution timed out (60s limit)."
    except Exception as e:
        return f"Error executing command '{command}': {str(e)}"

TERMINAL_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": "Execute a terminal shell command (e.g. pytest, npm test, python script, git)",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The exact shell command line to execute"},
                "cwd": {"type": "string", "description": "Working directory for the command execution"}
            },
            "required": ["command"]
        }
    }
}
