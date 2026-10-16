import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from agent.llm.base import ToolDefinition
from agent.mcp.client import MCPClientManager

logger = logging.getLogger(__name__)


@dataclass
class RegisteredTool:
    namespaced_name: str  # e.g. "filesystem.read_file"
    raw_name: str  # e.g. "read_file"
    server: str  # e.g. "filesystem"
    description: str
    input_schema: Dict[str, Any]

    def to_tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.namespaced_name,
            description=f"[{self.server}] {self.description}",
            parameters=self.input_schema,
        )


class ToolRegistry:
    """Discovers, namespaces, filters, and routes tool calls across MCP servers."""

    def __init__(
        self,
        client_manager: MCPClientManager,
        allowlist: Optional[Set[str]] = None,
        denylist: Optional[Set[str]] = None,
    ):
        self.client_manager = client_manager
        self.allowlist = allowlist
        self.denylist = denylist or set()
        self.tools: Dict[str, RegisteredTool] = {}
        # Legacy name alias mapping (e.g. "read_file" -> "filesystem.read_file")
        self.legacy_aliases: Dict[str, str] = {
            "read_file": "filesystem.read_file",
            "write_file": "filesystem.write_file",
            "edit_file": "filesystem.edit_file",
            "list_directory": "filesystem.list_directory",
            "search_files": "filesystem.search_files",
            "run_command": "terminal.run_command",
            "status": "git.status",
            "diff": "git.diff",
        }

    def discover_tools(self) -> int:
        """Poll all active MCP clients, fetch their tool lists, and register them."""
        self.tools.clear()
        count = 0

        for server_name, client in self.client_manager.clients.items():
            raw_tools = client.list_tools()
            for t in raw_tools:
                raw_name = t.get("name", "")
                namespaced = f"{server_name}.{raw_name}"

                # Filtering: check allowlist and denylist
                if self.allowlist is not None:
                    if namespaced not in self.allowlist and raw_name not in self.allowlist:
                        continue

                if namespaced in self.denylist or raw_name in self.denylist:
                    continue

                reg_tool = RegisteredTool(
                    namespaced_name=namespaced,
                    raw_name=raw_name,
                    server=server_name,
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                )
                self.tools[namespaced] = reg_tool
                count += 1

        return count

    def get_tool(self, tool_name: str) -> Optional[RegisteredTool]:
        if tool_name in self.tools:
            return self.tools[tool_name]
        # Check alias
        aliased = self.legacy_aliases.get(tool_name)
        if aliased and aliased in self.tools:
            return self.tools[aliased]
        return None

    def get_tool_definitions(self) -> List[ToolDefinition]:
        return [tool.to_tool_definition() for tool in self.tools.values()]

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute a tool call by routing to the appropriate MCP server."""
        resolved = self.get_tool(tool_name)
        if not resolved:
            return f"Error: Tool '{tool_name}' is not recognized or permitted in the tool registry."

        client = self.client_manager.get_client(resolved.server)
        if not client:
            return f"Error: MCP server '{resolved.server}' is not currently running or available."

        return client.call_tool(resolved.raw_name, arguments)
