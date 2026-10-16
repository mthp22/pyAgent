import os
from typing import Any, Callable, Dict, Optional, Set

READ_ONLY_TOOLS: Set[str] = {
    "filesystem.read_file",
    "filesystem.list_directory",
    "filesystem.search_files",
    "git.status",
    "git.diff",
    "git.log",
    "git.branch",
    "read_file",
    "list_directory",
    "search_files",
    "status",
    "diff",
}

MUTATING_TOOLS: Set[str] = {
    "filesystem.write_file",
    "filesystem.edit_file",
    "git.commit",
    "git.checkout",
    "write_file",
    "edit_file",
    "commit",
    "checkout",
}

EXECUTION_TOOLS: Set[str] = {
    "terminal.run_command",
    "run_command",
}


class SafetyPolicy:
    """Enforces 3-tier permission model ('safe', 'ask', 'auto') and workspace confinement."""

    def __init__(
        self,
        mode: str = "ask",
        workspace_dir: Optional[str] = None,
        allow_network: bool = False,
        allow_package_install: bool = False,
        allow_git_push: bool = False,
    ):
        self.mode = mode.lower() if mode in ("safe", "ask", "auto") else "ask"
        self.workspace_dir = os.path.abspath(workspace_dir or os.getcwd())
        self.allow_network = allow_network
        self.allow_package_install = allow_package_install
        self.allow_git_push = allow_git_push

    def is_read_only(self, tool_name: str) -> bool:
        return tool_name in READ_ONLY_TOOLS

    def check_permission(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        confirm_fn: Optional[Callable[[str], bool]] = None,
    ) -> tuple[bool, str]:
        # Always allow completion / finish
        if tool_name in ("finish", "verify"):
            return True, "Allowed"

        # Check path confinement for file tools
        path_arg = arguments.get("path")
        if path_arg:
            resolved = path_arg if os.path.isabs(path_arg) else os.path.join(self.workspace_dir, path_arg)
            # realpath resolves symlinks so a link inside the workspace cannot escape it.
            abs_resolved = os.path.realpath(resolved)
            workspace_root = os.path.realpath(self.workspace_dir)
            try:
                if os.path.commonpath([abs_resolved, workspace_root]) != workspace_root:
                    return False, f"Safety violation: Path '{path_arg}' attempts to escape workspace."
            except ValueError:
                return False, f"Safety violation: Path '{path_arg}' is invalid."

        # Check git push restriction
        if tool_name in ("git.push", "push") and not self.allow_git_push:
            return False, "Safety policy: Git push is disabled by safety configuration."

        # SAFE mode: strictly read-only
        if self.mode == "safe":
            if not self.is_read_only(tool_name):
                return False, f"Safety mode 'safe' forbids mutating tool '{tool_name}'."
            return True, "Allowed in safe mode"

        # AUTO mode: permits operations inside workspace
        if self.mode == "auto":
            return True, "Allowed in auto mode"

        # ASK mode: prompt if mutating or executing
        if self.mode == "ask":
            if self.is_read_only(tool_name):
                return True, "Read-only allowed in ask mode"

            prompt_msg = f"Agent requests approval to execute '{tool_name}' with args {arguments}."
            if confirm_fn:
                approved = confirm_fn(prompt_msg)
                if not approved:
                    return False, f"User denied execution of '{tool_name}'."
                return True, "User approved"
            # If no interactive prompt function provided, allow but log
            return True, "Auto-approved in non-interactive ask mode"

        return True, "Allowed"
