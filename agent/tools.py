import os
import subprocess
import shlex
import re
from agent.config import ALLOWED_COMMANDS, DANGEROUS_FLAGS, COMMAND_TIMEOUT, WORKSPACE_DIR

def is_safe_path(path: str) -> bool:
    """Ensure path is within workspace."""
    abs_path = os.path.abspath(path)
    # Allows read/write only inside the workspace
    return abs_path.startswith(os.path.abspath(WORKSPACE_DIR))

def read_file(path: str) -> str:
    if not is_safe_path(path):
        return f"Error: Path {path} is outside allowed workspace."
    try:
        with open(path, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

def write_file(path: str, content: str) -> str:
    if not is_safe_path(path):
        return f"Error: Path {path} is outside allowed workspace."
    try:
        # Create directories if they don't exist
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing file: {e}"

def edit_file(path: str, patch: str) -> str:
    """
    Very simple diff/replacement. 
    Expects patch to be a string where it tells what to replace exactly.
    Format could be custom, e.g., REPLACE: <old> WITH: <new>
    For simplicity, let's implement a rudimentary string replacement block.
    """
    if not is_safe_path(path):
        return f"Error: Path {path} is outside allowed workspace."
    try:
        with open(path, 'r') as f:
            content = f.read()
            
        # Simple extraction logic for the patch format
        if "REPLACE:" in patch and "WITH:" in patch:
            parts = patch.split("WITH:")
            old_str = parts[0].replace("REPLACE:", "").strip()
            new_str = parts[1].strip()
            if old_str in content:
                new_content = content.replace(old_str, new_str)
                with open(path, 'w') as f:
                    f.write(new_content)
                return f"Successfully edited {path}"
            else:
                return "Error: Old string not found in file."
        else:
            # Fallback if the patch format is not recognized, maybe just append?
            return "Error: Patch format not understood. Use 'REPLACE: <exact_text> WITH: <new_text>'"
    except Exception as e:
        return f"Error editing file: {e}"

def run_command(command: str) -> str:
    """
    Executes a shell command.
    Applies safety checks.
    """
    # Safety Check 1: No dangerous flags
    for flag in DANGEROUS_FLAGS:
        if flag in command:
            return f"Error: Command contains forbidden flag '{flag}'."
            
    # Safety Check 2: Must start with allowed commands (simple heuristic)
    cmd_parts = shlex.split(command)
    if not cmd_parts:
        return "Error: Empty command."
        
    base_cmd = cmd_parts[0]
    if base_cmd not in ALLOWED_COMMANDS:
        return f"Error: Command '{base_cmd}' is not in the allowed list: {ALLOWED_COMMANDS}"
        
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT
        )
        output = result.stdout + "\n" + result.stderr
        return output.strip() if output.strip() else "Success (No output)"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {COMMAND_TIMEOUT} seconds."
    except Exception as e:
        return f"Error executing command: {e}"
