import fnmatch
import os
import re
import sys
from typing import Any, Dict, Optional

# Ensure script and parent directory are on sys.path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_SCRIPT_DIR)
for _p in (_SCRIPT_DIR, _PARENT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from servers.base import MCPServer
except ImportError:
    from base import MCPServer  # type: ignore

WORKSPACE_DIR = os.path.abspath(os.environ.get("WORKSPACE_DIR", os.getcwd()))

PATCH_BLOCK_RE = re.compile(
    r"REPLACE:\s*(.*?)\s*WITH:\s*(.*?)(?=(?:\n\s*REPLACE:)|\Z)",
    re.DOTALL,
)


def _is_subpath(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root)
    except ValueError:
        return False


def get_safe_abs_path(path: str) -> Optional[str]:
    resolved = path
    if not os.path.isabs(resolved):
        resolved = os.path.join(WORKSPACE_DIR, resolved)
    abs_path = os.path.realpath(resolved)
    if not _is_subpath(abs_path, WORKSPACE_DIR):
        return None
    return abs_path


def _write_atomic(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    tmp_path = os.path.join(directory, f".{os.path.basename(path)}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp_path, path)


def handle_read_file(args: Dict[str, Any]) -> str:
    path = args.get("path", "")
    safe_path = get_safe_abs_path(path)
    if not safe_path:
        return f"Error: Path '{path}' is outside allowed workspace."
    if not os.path.exists(safe_path):
        return f"Error: File '{path}' does not exist."
    try:
        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as exc:
        return f"Error reading file: {exc}"


def handle_write_file(args: Dict[str, Any]) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    safe_path = get_safe_abs_path(path)
    if not safe_path:
        return f"Error: Path '{path}' is outside allowed workspace."
    try:
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        _write_atomic(safe_path, content)
        return f"Successfully wrote to {path}"
    except Exception as exc:
        return f"Error writing file: {exc}"


def handle_edit_file(args: Dict[str, Any]) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    safe_path = get_safe_abs_path(path)
    if not safe_path:
        return f"Error: Path '{path}' is outside allowed workspace."
    if not os.path.exists(safe_path):
        return f"Error: File '{path}' does not exist to edit."

    try:
        with open(safe_path, "r", encoding="utf-8") as handle:
            file_text = handle.read()
    except Exception as exc:
        return f"Error reading file before editing: {exc}"

    if "REPLACE:" in content and "WITH:" in content:
        matches = list(PATCH_BLOCK_RE.finditer(content))
        if not matches:
            return "Error: Malformed patch. Could not parse REPLACE/WITH blocks."

        updated_text = file_text
        for match in matches:
            old_str = match.group(1)
            new_str = match.group(2)
            if old_str not in updated_text:
                return f"Error: Target block to replace not found in {path}."
            updated_text = updated_text.replace(old_str, new_str, 1)

        _write_atomic(safe_path, updated_text)
        return f"Successfully edited {path}"
    else:
        _write_atomic(safe_path, content)
        return f"Successfully updated {path}"


def handle_list_directory(args: Dict[str, Any]) -> str:
    path = args.get("path", ".")
    safe_path = get_safe_abs_path(path)
    if not safe_path:
        return f"Error: Path '{path}' is outside allowed workspace."
    if not os.path.isdir(safe_path):
        return f"Error: '{path}' is not a directory."

    try:
        entries = sorted(os.listdir(safe_path))
        lines = []
        for e in entries:
            full = os.path.join(safe_path, e)
            kind = "[DIR]" if os.path.isdir(full) else "[FILE]"
            lines.append(f"{kind} {e}")
        return "\n".join(lines) if lines else "(empty directory)"
    except Exception as exc:
        return f"Error listing directory: {exc}"


def handle_search_files(args: Dict[str, Any]) -> str:
    pattern = args.get("pattern", "*")
    directory = args.get("directory", ".")
    safe_path = get_safe_abs_path(directory)
    if not safe_path:
        return f"Error: Directory '{directory}' is outside allowed workspace."

    matches = []
    try:
        for root, dirs, files in os.walk(safe_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".venv")]
            for filename in files:
                if fnmatch.fnmatch(filename, pattern):
                    rel = os.path.relpath(os.path.join(root, filename), WORKSPACE_DIR)
                    matches.append(rel)
                    if len(matches) >= 100:
                        break
            if len(matches) >= 100:
                break
        return "\n".join(matches) if matches else "No files matched."
    except Exception as exc:
        return f"Error searching files: {exc}"


def create_server() -> MCPServer:
    server = MCPServer(name="filesystem", version="1.0.0")

    server.register_tool(
        name="read_file",
        description="Read the contents of a file within the workspace.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Relative path to the file"}},
            "required": ["path"],
        },
        handler=handle_read_file,
    )

    server.register_tool(
        name="write_file",
        description="Write full content to a file (creating parent directories if needed).",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file"},
                "content": {"type": "string", "description": "Text content to write"},
            },
            "required": ["path", "content"],
        },
        handler=handle_write_file,
    )

    server.register_tool(
        name="edit_file",
        description="Edit a file using REPLACE: <old_text> WITH: <new_text> blocks.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file"},
                "content": {"type": "string", "description": "REPLACE: ... WITH: ... patch"},
            },
            "required": ["path", "content"],
        },
        handler=handle_edit_file,
    )

    server.register_tool(
        name="list_directory",
        description="List files and directories at the specified path.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to directory (default '.')"}
            },
        },
        handler=handle_list_directory,
    )

    server.register_tool(
        name="search_files",
        description="Search for files matching a glob pattern (e.g. '*.py').",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match"},
                "directory": {"type": "string", "description": "Directory to search from (default '.')"},
            },
            "required": ["pattern"],
        },
        handler=handle_search_files,
    )

    return server


if __name__ == "__main__":
    create_server().run()
