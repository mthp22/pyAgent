import os
import shlex
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

_DEFAULT_ALLOWED_COMMANDS = [
    "python",
    "python3",
    "pip",
    "pip3",
    "pytest",
    "ls",
    "cat",
    "echo",
    "mkdir",
    "touch",
    "git",
    "source",
    "cd",
    "ruff",
    "mypy",
    "npm",
    "pnpm",
    "yarn",
    "cargo",
    "go",
]
_DEFAULT_DANGEROUS_FLAGS = ["-rf", "sudo"]


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# The effective policy is supplied by the parent agent via env vars (from pyagent.toml),
# falling back to the safe defaults when the server is run standalone.
ALLOWED_COMMANDS = _env_list("PYAGENT_ALLOWED_COMMANDS", _DEFAULT_ALLOWED_COMMANDS)
DANGEROUS_FLAGS = _env_list("PYAGENT_DANGEROUS_FLAGS", _DEFAULT_DANGEROUS_FLAGS)
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 600


def _is_subpath(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root)
    except ValueError:
        return False


def _resolve_working_dir(cwd: str) -> str | None:
    if not cwd or cwd == ".":
        return WORKSPACE_DIR
    target = os.path.abspath(os.path.join(WORKSPACE_DIR, cwd)) if not os.path.isabs(cwd) else os.path.abspath(cwd)
    return target if _is_subpath(target, WORKSPACE_DIR) and os.path.isdir(target) else None


def handle_run_command(args: Dict[str, Any]) -> str:
    command_str = args.get("command", "").strip()
    if not command_str:
        return "Error: Command cannot be empty."

    cwd_arg = args.get("cwd", ".")
    resolved_cwd = _resolve_working_dir(cwd_arg)
    if not resolved_cwd:
        return f"Error: Invalid or non-existent working directory '{cwd_arg}' outside workspace."

    timeout = int(args.get("timeout_secs", DEFAULT_TIMEOUT))
    if timeout <= 0 or timeout > MAX_TIMEOUT:
        timeout = DEFAULT_TIMEOUT

    # Safety checks
    try:
        tokens = shlex.split(command_str)
    except ValueError:
        return f"Error: Invalid command syntax: {command_str}"

    if not tokens:
        return "Error: Command cannot be empty."

    primary_cmd = os.path.basename(tokens[0])
    if primary_cmd not in ALLOWED_COMMANDS:
        return (
            f"Error: Command '{primary_cmd}' is not in the allowed list of safe commands "
            f"({', '.join(ALLOWED_COMMANDS)})."
        )

    for flag in DANGEROUS_FLAGS:
        if any(flag in token for token in tokens):
            return f"Error: Dangerous flag or token '{flag}' is not permitted."

    try:
        # Execute the parsed argv WITHOUT a shell so metacharacters (;, &&, |,
        # backticks, $(), redirections) cannot chain commands past the allowlist.
        res = subprocess.run(
            tokens,
            cwd=resolved_cwd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = res.stdout
        if res.stderr:
            output += ("\n" if output else "") + res.stderr
        output = output.strip()
        if not output and res.returncode == 0:
            return "(Command completed with no output, exit code 0)"
        if res.returncode != 0:
            return f"[Exit code {res.returncode}]\n{output}"
        return output
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds in cwd '{cwd_arg}'."
    except Exception as exc:
        return f"Error executing command: {exc}"


def create_server() -> MCPServer:
    server = MCPServer(name="terminal", version="1.0.0")

    server.register_tool(
        name="run_command",
        description="Run an allowed shell command in the project workspace.",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command string to execute"},
                "cwd": {"type": "string", "description": "Working directory (default '.')"},
                "timeout_secs": {"type": "integer", "description": "Timeout in seconds (max 600)"},
            },
            "required": ["command"],
        },
        handler=handle_run_command,
    )

    return server


if __name__ == "__main__":
    create_server().run()
