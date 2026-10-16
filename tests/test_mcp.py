import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent.mcp.client import MCPClientManager, MCPProcessClient
from agent.mcp.registry import ToolRegistry
from servers.base import MCPServer
from servers.filesystem import (
    handle_edit_file,
    handle_list_directory,
    handle_read_file,
    handle_write_file,
)
from servers.terminal import _env_list, handle_run_command


class TestMCPServers(unittest.TestCase):
    def test_base_mcp_server_protocol(self):
        server = MCPServer(name="test_server", version="1.0.0")
        server.register_tool(
            name="hello",
            description="Says hello",
            input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            handler=lambda args: f"Hello, {args.get('name', 'world')}!",
        )

        responses = []
        server._send_response = lambda resp: responses.append(resp)

        # 1. Initialize
        server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "test_server")

        # 2. Tools list
        server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        self.assertEqual(len(responses), 2)
        tools = responses[1]["result"]["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "hello")

        # 3. Tool call
        server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "hello", "arguments": {"name": "Alice"}},
            }
        )
        self.assertEqual(len(responses), 3)
        self.assertFalse(responses[2]["result"]["isError"])
        self.assertEqual(responses[2]["result"]["content"][0]["text"], "Hello, Alice!")

    def test_filesystem_server_operations(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_ws = os.environ.get("WORKSPACE_DIR")
            try:
                os.environ["WORKSPACE_DIR"] = tmp_dir
                import servers.filesystem as fs_mod

                fs_mod.WORKSPACE_DIR = tmp_dir

                # Write file
                write_res = handle_write_file({"path": "sample.txt", "content": "Line 1\nLine 2"})
                self.assertIn("Successfully wrote", write_res)

                # Read file
                read_res = handle_read_file({"path": "sample.txt"})
                self.assertEqual(read_res, "Line 1\nLine 2")

                # Edit file
                edit_res = handle_edit_file(
                    {"path": "sample.txt", "content": "REPLACE: Line 2 WITH: Line Two"}
                )
                self.assertIn("Successfully edited", edit_res)
                self.assertEqual(handle_read_file({"path": "sample.txt"}), "Line 1\nLine Two")

                # List directory
                list_res = handle_list_directory({"path": "."})
                self.assertIn("sample.txt", list_res)

                # Jail check - outside path
                outside_res = handle_read_file({"path": "../secret.txt"})
                self.assertIn("outside allowed workspace", outside_res)
            finally:
                if old_ws is not None:
                    os.environ["WORKSPACE_DIR"] = old_ws
                else:
                    os.environ.pop("WORKSPACE_DIR", None)

    def test_terminal_server_safety(self):
        # Safe echo
        res_echo = handle_run_command({"command": "echo 'safe test'"})
        self.assertIn("safe test", res_echo)

        # Disallowed command
        res_bad = handle_run_command({"command": "curl http://example.com"})
        self.assertIn("is not in the allowed list", res_bad)

        # Dangerous flag
        res_danger = handle_run_command({"command": "ls -rf"})
        self.assertIn("Dangerous flag", res_danger)

    def test_terminal_policy_can_be_overridden_by_env(self):
        # Defaults apply when the env var is absent.
        self.assertEqual(_env_list("PYAGENT_ALLOWED_COMMANDS", ["ls"]), ["ls"])

        # A comma-separated env var (set by the parent agent from pyagent.toml) wins.
        with patch.dict(os.environ, {"PYAGENT_ALLOWED_COMMANDS": "python3, pytest ,,"}):
            self.assertEqual(_env_list("PYAGENT_ALLOWED_COMMANDS", ["ls"]), ["python3", "pytest"])


class TestMCPClientAndRegistry(unittest.TestCase):
    def test_end_to_end_mcp_client_and_registry(self):
        ws_dir = os.path.abspath(os.getcwd())
        client = MCPProcessClient(
            name="filesystem",
            command=sys.executable,
            args=["servers/filesystem.py"],
            cwd=ws_dir,
        )

        started = client.start()
        self.assertTrue(started, "Failed to start filesystem MCP server process.")

        try:
            tools = client.list_tools()
            self.assertTrue(len(tools) >= 4)
            tool_names = [t["name"] for t in tools]
            self.assertIn("read_file", tool_names)
            self.assertIn("write_file", tool_names)

            # Test through ToolRegistry
            client_manager = MCPClientManager(workspace_dir=ws_dir)
            client_manager.clients["filesystem"] = client

            registry = ToolRegistry(client_manager=client_manager)
            discovered_count = registry.discover_tools()
            self.assertTrue(discovered_count >= 4)
            self.assertIsNotNone(registry.get_tool("filesystem.read_file"))
            self.assertIsNotNone(registry.get_tool("read_file"))  # alias check

            # Execute via registry
            res = registry.execute("filesystem.read_file", {"path": "pyagent.toml"})
            self.assertIn("[agent]", res)

            # Tool definitions format check
            defs = registry.get_tool_definitions()
            self.assertTrue(any(d.name == "filesystem.read_file" for d in defs))
        finally:
            client.stop()


if __name__ == "__main__":
    unittest.main()
