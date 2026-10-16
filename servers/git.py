import os
import subprocess
import sys
from typing import Any, Dict

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


def _run_git(args: list[str], timeout: int = 15) -> tuple[int, str, str]:
    res = subprocess.run(
        ["git"] + args,
        cwd=WORKSPACE_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def handle_status(args: Dict[str, Any]) -> str:
    code, stdout, stderr = _run_git(["status", "-s"])
    if code != 0:
        return f"Git error ({code}): {stderr or stdout}"
    return stdout if stdout else "Working tree clean."


def handle_diff(args: Dict[str, Any]) -> str:
    staged = bool(args.get("staged", False))
    cmd = ["diff", "--cached"] if staged else ["diff"]
    path = args.get("path")
    if path:
        cmd.extend(["--", path])
    code, stdout, stderr = _run_git(cmd)
    if code != 0:
        return f"Git error ({code}): {stderr or stdout}"
    return stdout if stdout else "(no diff)"


def handle_log(args: Dict[str, Any]) -> str:
    max_count = int(args.get("max_count", 5))
    code, stdout, stderr = _run_git(["log", f"-n{max_count}", "--oneline"])
    if code != 0:
        return f"Git error ({code}): {stderr or stdout}"
    return stdout if stdout else "(no commits)"


def handle_branch(args: Dict[str, Any]) -> str:
    code, stdout, stderr = _run_git(["branch", "-a"])
    if code != 0:
        return f"Git error ({code}): {stderr or stdout}"
    return stdout if stdout else "(no branch info)"


def handle_checkout(args: Dict[str, Any]) -> str:
    branch_name = args.get("branch")
    create = bool(args.get("create", False))
    if not branch_name:
        return "Error: branch name is required."

    cmd = ["checkout", "-b", branch_name] if create else ["checkout", branch_name]
    code, stdout, stderr = _run_git(cmd)
    if code != 0:
        return f"Git error ({code}): {stderr or stdout}"
    return stdout or f"Switched to branch '{branch_name}'"


def handle_commit(args: Dict[str, Any]) -> str:
    message = args.get("message")
    if not message:
        return "Error: commit message is required."

    # Stage all tracked / modified files if requested
    stage_all = bool(args.get("all", True))
    if stage_all:
        _run_git(["add", "-A"])

    code, stdout, stderr = _run_git(["commit", "-m", message])
    if code != 0:
        return f"Git error ({code}): {stderr or stdout}"
    return stdout or "Committed changes successfully."


def create_server() -> MCPServer:
    server = MCPServer(name="git", version="1.0.0")

    server.register_tool(
        name="status",
        description="Get current git status (modified, untracked, staged files).",
        input_schema={"type": "object", "properties": {}},
        handler=handle_status,
    )

    server.register_tool(
        name="diff",
        description="Inspect git diff for unstaged or staged changes.",
        input_schema={
            "type": "object",
            "properties": {
                "staged": {"type": "boolean", "description": "Show staged diff if true"},
                "path": {"type": "string", "description": "Optional specific file path"},
            },
        },
        handler=handle_diff,
    )

    server.register_tool(
        name="log",
        description="Show recent git commit history.",
        input_schema={
            "type": "object",
            "properties": {
                "max_count": {"type": "integer", "description": "Number of commits to show (default 5)"}
            },
        },
        handler=handle_log,
    )

    server.register_tool(
        name="branch",
        description="List repository branches.",
        input_schema={"type": "object", "properties": {}},
        handler=handle_branch,
    )

    server.register_tool(
        name="checkout",
        description="Checkout an existing branch or create a new branch.",
        input_schema={
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Name of the branch"},
                "create": {"type": "boolean", "description": "Create new branch (-b) if true"},
            },
            "required": ["branch"],
        },
        handler=handle_checkout,
    )

    server.register_tool(
        name="commit",
        description="Commit changes to git with a commit message.",
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
                "all": {"type": "boolean", "description": "Stage all changes before committing (default true)"},
            },
            "required": ["message"],
        },
        handler=handle_commit,
    )

    return server


if __name__ == "__main__":
    create_server().run()
