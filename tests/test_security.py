import os
import tempfile
import unittest

from agent.safety.policy import SafetyPolicy
from agent.tools import get_safe_abs_path, read_file, run_command, write_file


class CommandInjectionTests(unittest.TestCase):
    """The command runner must never let shell metacharacters chain extra commands."""

    def test_semicolon_chain_is_not_executed(self):
        with tempfile.TemporaryDirectory() as workspace:
            marker = os.path.join(workspace, "pwned")
            # If the shell were used, this would create the marker file.
            output = run_command(f"echo hi; touch {marker}", workspace)
            self.assertFalse(os.path.exists(marker))
            self.assertIn("touch", output)  # treated as a literal argument

    def test_pipe_is_not_interpreted(self):
        with tempfile.TemporaryDirectory() as workspace:
            output = run_command("echo hi | sh", workspace)
            self.assertIn("|", output)

    def test_backticks_are_literal(self):
        with tempfile.TemporaryDirectory() as workspace:
            output = run_command("echo `id`", workspace)
            self.assertIn("id", output)
            self.assertNotIn("uid=", output)

    def test_disallowed_binary_rejected(self):
        with tempfile.TemporaryDirectory() as workspace:
            output = run_command("curl http://example.com", workspace)
            self.assertTrue(output.startswith("Error:"))
            self.assertIn("not in the allowed list", output)

    def test_dangerous_flag_rejected(self):
        with tempfile.TemporaryDirectory() as workspace:
            output = run_command("ls -rf /", workspace)
            self.assertTrue(output.startswith("Error:"))
            self.assertIn("forbidden flag", output)

    def test_custom_allowlist_is_enforced(self):
        with tempfile.TemporaryDirectory() as workspace:
            # 'ls' is normally allowed, but a restricted allowlist should reject it.
            output = run_command("ls", workspace, allowed_commands=["python3"])
            self.assertTrue(output.startswith("Error:"))
            self.assertIn("not in the allowed list", output)

    def test_nonzero_exit_code_is_reported(self):
        with tempfile.TemporaryDirectory() as workspace:
            output = run_command('python3 -c "import sys; sys.exit(3)"', workspace)
            self.assertIn("[Exit code 3]", output)


class WorkspaceConfinementTests(unittest.TestCase):
    def test_traversal_path_rejected(self):
        with tempfile.TemporaryDirectory() as workspace:
            self.assertIsNone(get_safe_abs_path("../../etc/passwd", workspace))
            self.assertTrue(read_file("../../etc/passwd", workspace).startswith("Error:"))

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            secret = os.path.join(outside, "secret.txt")
            with open(secret, "w", encoding="utf-8") as handle:
                handle.write("top secret")
            link = os.path.join(workspace, "escape_link")
            os.symlink(secret, link)

            self.assertIsNone(get_safe_abs_path("escape_link", workspace))
            self.assertTrue(read_file("escape_link", workspace).startswith("Error:"))
            self.assertTrue(write_file("escape_link", "overwrite", workspace).startswith("Error:"))

    def test_safety_policy_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            secret = os.path.join(outside, "secret.txt")
            with open(secret, "w", encoding="utf-8") as handle:
                handle.write("top secret")
            os.symlink(secret, os.path.join(workspace, "escape_link"))

            policy = SafetyPolicy(mode="auto", workspace_dir=workspace)
            allowed, msg = policy.check_permission("filesystem.read_file", {"path": "escape_link"})
            self.assertFalse(allowed)
            self.assertIn("escape workspace", msg)


if __name__ == "__main__":
    unittest.main()
