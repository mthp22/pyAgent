import os
import re
import shlex
import subprocess
from typing import List, Optional, Tuple

from agent.config import (
    ALLOWED_COMMANDS,
    COMMAND_TIMEOUT,
    DANGEROUS_FLAGS,
    MAX_COMMAND_TIMEOUT,
    SLOW_COMMAND_TIMEOUT,
)


PATCH_BLOCK_RE = re.compile(
    r"REPLACE:\s*(.*?)\s*WITH:\s*(.*?)(?=(?:\n\s*REPLACE:)|\Z)",
    re.DOTALL,
)


def _is_subpath(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


def get_safe_abs_path(path: str, workspace_dir: str) -> Optional[str]:
    """Resolve path against workspace_dir and ensure it stays inside it."""
    resolved = path
    if not os.path.isabs(resolved):
        resolved = os.path.join(workspace_dir, resolved)
    abs_path = os.path.abspath(resolved)
    if not _is_subpath(abs_path, workspace_dir):
        return None
    return abs_path


def _write_atomic(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    tmp_path = os.path.join(directory, f".{os.path.basename(path)}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp_path, path)


def read_file(path: str, workspace_dir: str) -> str:
    safe_path = get_safe_abs_path(path, workspace_dir)
    if not safe_path:
        return f"Error: Path {path} is outside allowed workspace."

    try:
        with open(safe_path, "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception as exc:
        return f"Error reading file: {exc}"


def write_file(path: str, content: str, workspace_dir: str) -> str:
    safe_path = get_safe_abs_path(path, workspace_dir)
    if not safe_path:
        return f"Error: Path {path} is outside allowed workspace."

    try:
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        _write_atomic(safe_path, content)
        return f"Successfully wrote to {safe_path}"
    except Exception as exc:
        return f"Error writing file: {exc}"


def _parse_replace_blocks(patch: str) -> Tuple[Optional[List[Tuple[str, str]]], Optional[str]]:
    if not patch.strip():
        return None, "Error: Patch is empty."

    if "REPLACE:" not in patch or "WITH:" not in patch:
        return None, "Error: Patch format not understood. Use 'REPLACE: <exact_text> WITH: <new_text>'."

    matches = list(PATCH_BLOCK_RE.finditer(patch))
    if not matches:
        return None, "Error: Malformed patch. Could not parse REPLACE/WITH blocks."

    replace_token_count = len(re.findall(r"\bREPLACE:", patch))
    if replace_token_count != len(matches):
        return None, "Error: Malformed patch. Every REPLACE block must include a corresponding WITH block."

    blocks: List[Tuple[str, str]] = []
    previous_end = 0
    for idx, match in enumerate(matches, start=1):
        between = patch[previous_end:match.start()]
        if between.strip():
            return None, f"Error: Malformed patch near block {idx}. Unexpected text between blocks."

        old_text = match.group(1)
        new_text = match.group(2)
        if not old_text.strip():
            return None, f"Error: Malformed patch in block {idx}. REPLACE content cannot be empty."

        blocks.append((old_text, new_text))
        previous_end = match.end()

    if patch[previous_end:].strip():
        return None, "Error: Malformed patch. Unexpected trailing content."

    return blocks, None


def edit_file(path: str, patch: str, workspace_dir: str) -> str:
    """
    Transactional multi-block replacement.

    Expected patch format:
    REPLACE: <old text> WITH: <new text>
    REPLACE: <old text 2> WITH: <new text 2>
    """
    safe_path = get_safe_abs_path(path, workspace_dir)
    if not safe_path:
        return f"Error: Path {path} is outside allowed workspace."

    try:
        with open(safe_path, "r", encoding="utf-8") as handle:
            original_content = handle.read()

        blocks, parse_error = _parse_replace_blocks(patch)
        if parse_error:
            return parse_error

        assert blocks is not None
        updated_content = original_content
        for idx, (old_text, new_text) in enumerate(blocks, start=1):
            if old_text not in updated_content:
                return f"Error: Block {idx} old string not found in file. No changes were applied."
            updated_content = updated_content.replace(old_text, new_text, 1)

        _write_atomic(safe_path, updated_content)
        return f"Successfully edited {safe_path}"
    except Exception as exc:
        return f"Error editing file: {exc}"


def _is_slow_command(command: str) -> bool:
    lowered = command.lower()
    slow_patterns = (
        "pip install",
        "pip3 install",
        "python -m pip install",
        "python3 -m pip install",
        "pytest",
        "python -m pytest",
        "python3 -m pytest",
    )
    return any(pattern in lowered for pattern in slow_patterns)


def _resolve_timeout(command: str, timeout_secs: Optional[int]) -> Tuple[Optional[int], Optional[str]]:
    if timeout_secs is not None:
        try:
            requested = int(timeout_secs)
        except (TypeError, ValueError):
            return None, "Error: timeout_secs must be an integer."

        if requested <= 0:
            return None, "Error: timeout_secs must be greater than 0."
        return min(requested, MAX_COMMAND_TIMEOUT), None

    if _is_slow_command(command):
        return max(COMMAND_TIMEOUT, SLOW_COMMAND_TIMEOUT), None
    return COMMAND_TIMEOUT, None


def _resolve_cwd(cwd: Optional[str], workspace_dir: str) -> Tuple[Optional[str], Optional[str]]:
    if not cwd:
        return workspace_dir, None

    safe_cwd = get_safe_abs_path(cwd, workspace_dir)
    if not safe_cwd:
        return None, f"Error: cwd '{cwd}' is outside allowed workspace."
    if not os.path.isdir(safe_cwd):
        return None, f"Error: cwd '{cwd}' is not a directory."
    return safe_cwd, None


def run_command(
    command: str,
    workspace_dir: str,
    cwd: Optional[str] = None,
    timeout_secs: Optional[int] = None,
) -> str:
    """
    Execute a shell command with safety checks and configurable timeout/cwd.
    """
    for flag in DANGEROUS_FLAGS:
        if flag in command:
            return f"Error: Command contains forbidden flag '{flag}'."

    try:
        cmd_parts = shlex.split(command)
    except ValueError as exc:
        return f"Error: Invalid command syntax: {exc}"

    if not cmd_parts:
        return "Error: Empty command."

    base_cmd = cmd_parts[0]
    if base_cmd not in ALLOWED_COMMANDS:
        return f"Error: Command '{base_cmd}' is not in the allowed list: {ALLOWED_COMMANDS}"

    command_cwd, cwd_error = _resolve_cwd(cwd, workspace_dir)
    if cwd_error:
        return cwd_error

    timeout, timeout_error = _resolve_timeout(command, timeout_secs)
    if timeout_error:
        return timeout_error

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=command_cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout or "") + ("\n" if result.stdout and result.stderr else "") + (result.stderr or "")
        output = output.strip()
        if output:
            return output
        return "Success (No output)"
    except subprocess.TimeoutExpired:
        rel_cwd = os.path.relpath(command_cwd, workspace_dir) if command_cwd else "."
        return (
            f"Error: Command timed out after {timeout} seconds in cwd '{rel_cwd}'. "
            f"Retry with a smaller command or timeout_secs <= {MAX_COMMAND_TIMEOUT}."
        )
    except Exception as exc:
        return f"Error executing command: {exc}"
