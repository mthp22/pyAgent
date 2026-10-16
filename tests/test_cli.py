import io
import os
import tempfile
import unittest
from unittest.mock import patch

from agent.cli import print_status, print_tools, test_mcp_servers


class TestCLI(unittest.TestCase):
    def test_status_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp_dir)
                captured = io.StringIO()
                with patch("sys.stdout", captured):
                    print_status()
                self.assertIn("Sessions Status", captured.getvalue())
            finally:
                os.chdir(old_cwd)

    def test_mcp_test_connectivity(self):
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            test_mcp_servers()
        output = captured.getvalue()
        self.assertIn("Testing MCP Servers Connectivity", output)
        self.assertIn("filesystem", output)
        self.assertIn("git", output)
        self.assertIn("terminal", output)

    def test_print_tools_discovery(self):
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            print_tools()
        output = captured.getvalue()
        self.assertIn("Discovered MCP Tools", output)
        self.assertIn("filesystem.read_file", output)
        self.assertIn("terminal.run_command", output)


if __name__ == "__main__":
    unittest.main()
