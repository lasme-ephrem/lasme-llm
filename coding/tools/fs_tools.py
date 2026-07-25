import os
import re
import shutil
from pathlib import Path
from typing import Dict, Any, List
from core.security import resolve_workspace_path, SecurityError

def tool_list_dir(path: str = ".") -> str:
    """Lists files and directories at the given path."""
    try:
        p = resolve_workspace_path(path)
        if not p.exists():
            return f"Error: Path '{path}' does not exist."
        
        entries = []
        for item in sorted(p.iterdir()):
            prefix = "[DIR] " if item.is_dir() else "[FILE]"
            entries.append(f"{prefix} {item.name}")
        
        return "\n".join(entries) if entries else "Directory is empty."
    except Exception as e:
        return f"Error listing directory '{path}': {str(e)}"

def tool_get_file_tree(path: str = ".", max_depth: int = 3) -> str:
    """Returns a visual tree structure of the workspace."""
    try:
        root = resolve_workspace_path(path)
        if not root.exists():
            return f"Error: Path '{path}' does not exist."

        tree_lines = [f"📁 {root.name}/"]
        ignored = {".git", "__pycache__", "node_modules", "venv", ".idea", ".vscode", "scratch", ".system_generated"}

        def build_tree(dir_path: Path, prefix: str = "", current_depth: int = 1):
            if current_depth > max_depth:
                return
            
            items = sorted([item for item in dir_path.iterdir() if item.name not in ignored], key=lambda x: (not x.is_dir(), x.name.lower()))
            count = len(items)
            for idx, item in enumerate(items):
                is_last = (idx == count - 1)
                connector = "└── " if is_last else "├── "
                if item.is_dir():
                    tree_lines.append(f"{prefix}{connector}📁 {item.name}/")
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    build_tree(item, new_prefix, current_depth + 1)
                else:
                    tree_lines.append(f"{prefix}{connector}📄 {item.name}")

        build_tree(root)
        return "\n".join(tree_lines)
    except Exception as e:
        return f"Error generating tree for '{path}': {str(e)}"

def tool_view_file(path: str, start_line: int = 1, end_line: int = 200) -> str:
    """Reads lines from a file."""
    try:
        p = resolve_workspace_path(path)
        if not p.exists() or not p.is_file():
            return f"Error: File '{path}' does not exist."
        
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        total_lines = len(lines)
        
        start_idx = max(0, start_line - 1)
        end_idx = min(total_lines, end_line)
        
        selected_lines = lines[start_idx:end_idx]
        formatted = [f"{i + start_idx + 1:4d} | {line}" for i, line in enumerate(selected_lines)]
        
        header = f"--- {p.name} (Lines {start_idx+1}-{end_idx} of {total_lines}) ---\n"
        return header + "\n".join(formatted)
    except Exception as e:
        return f"Error reading file '{path}': {str(e)}"

def tool_write_file(path: str, content: str) -> str:
    """Creates or overwrites a file with content."""
    try:
        p = resolve_workspace_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to {p.name}."
    except Exception as e:
        return f"Error writing file '{path}': {str(e)}"

def tool_replace_file_content(path: str, target: str, replacement: str) -> str:
    """Replaces target string with replacement string in a file."""
    try:
        p = resolve_workspace_path(path)
        if not p.exists():
            return f"Error: File '{path}' does not exist."
        
        text = p.read_text(encoding="utf-8")
        if target not in text:
            return f"Error: Target text not found in '{p.name}'."
        
        count = text.count(target)
        new_text = text.replace(target, replacement, 1)
        p.write_text(new_text, encoding="utf-8")
        return f"Successfully replaced content in {p.name} (matches found: {count})."
    except Exception as e:
        return f"Error replacing content in '{path}': {str(e)}"

def tool_move_file(source_path: str, destination_path: str) -> str:
    """Moves or renames a file or directory."""
    try:
        src = resolve_workspace_path(source_path)
        dst = resolve_workspace_path(destination_path)
        if not src.exists():
            return f"Error: Source '{source_path}' does not exist."
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return f"Successfully moved {src.name} to {destination_path}."
    except Exception as e:
        return f"Error moving file: {str(e)}"

def tool_delete_file(path: str) -> str:
    """Deletes a file or directory."""
    try:
        p = resolve_workspace_path(path)
        if not p.exists():
            return f"Error: Path '{path}' does not exist."
        if p == resolve_workspace_path("."):
            return "Error: Deleting the workspace root is never allowed."
        if p.is_file():
            p.unlink()
        else:
            shutil.rmtree(p)
        return f"Successfully deleted {p.name}."
    except Exception as e:
        return f"Error deleting path '{path}': {str(e)}"

def tool_grep_search(query: str, search_path: str = ".") -> str:
    """Searches for pattern/query in text files recursively."""
    try:
        p = resolve_workspace_path(search_path)
        if not p.exists():
            return f"Error: Search path '{search_path}' does not exist."
        
        matches = []
        regex = re.compile(query, re.IGNORECASE)
        
        for file_path in p.rglob("*"):
            if file_path.is_file() and not any(part.startswith(".") or part in ["node_modules", "__pycache__", "venv"] for part in file_path.parts):
                try:
                    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    for idx, line in enumerate(lines, 1):
                        if regex.search(line):
                            rel_path = file_path.relative_to(p)
                            matches.append(f"{rel_path}:{idx}: {line.strip()}")
                            if len(matches) >= 50:
                                break
                except Exception:
                    continue
            if len(matches) >= 50:
                break
                
        return "\n".join(matches) if matches else "No matches found."
    except Exception as e:
        return f"Error searching in '{search_path}': {str(e)}"

# JSON Schemas for Ollama Function Calling
CODING_TOOLS_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and subdirectories in a target folder",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute directory path (defaults to '.')"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_tree",
            "description": "Generates a clean visual tree hierarchy of workspace files and folders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Root directory path (default '.')."},
                    "max_depth": {"type": "integer", "description": "Maximum tree depth (default 3)."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_file",
            "description": "Read file lines with line numbers",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to target file"},
                    "start_line": {"type": "integer", "description": "Starting line number (1-indexed)"},
                    "end_line": {"type": "integer", "description": "Ending line number"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file or overwrite an existing file with complete content",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file"},
                    "content": {"type": "string", "description": "Content to write"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "replace_file_content",
            "description": "Replace a specific snippet in a file with new content",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to target file"},
                    "target": {"type": "string", "description": "Exact text substring to replace"},
                    "replacement": {"type": "string", "description": "Replacement text"}
                },
                "required": ["path", "target", "replacement"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": "Move or rename a file or directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {"type": "string", "description": "Source path"},
                    "destination_path": {"type": "string", "description": "Destination path"}
                },
                "required": ["source_path", "destination_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file or directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to delete"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "grep_search",
            "description": "Search for text or regex pattern across workspace files",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search pattern or word"},
                    "search_path": {"type": "string", "description": "Directory path to search"}
                },
                "required": ["query"]
            }
        }
    }
]
