import tempfile
import unittest

from agent.safety.policy import SafetyPolicy


class TestSafetyPolicy(unittest.TestCase):
    def test_safe_mode_read_only(self):
        policy = SafetyPolicy(mode="safe")
        # Read-only allowed
        allowed, _ = policy.check_permission("filesystem.read_file", {"path": "main.py"})
        self.assertTrue(allowed)

        # Mutating blocked
        allowed, msg = policy.check_permission("filesystem.write_file", {"path": "main.py", "content": "..."})
        self.assertFalse(allowed)
        self.assertIn("forbids mutating tool", msg)

        allowed, msg = policy.check_permission("terminal.run_command", {"command": "ls"})
        self.assertFalse(allowed)

    def test_auto_mode(self):
        policy = SafetyPolicy(mode="auto")
        allowed, _ = policy.check_permission("filesystem.write_file", {"path": "main.py", "content": "..."})
        self.assertTrue(allowed)

        allowed, _ = policy.check_permission("terminal.run_command", {"command": "pytest"})
        self.assertTrue(allowed)

    def test_ask_mode_interactive_approval(self):
        policy = SafetyPolicy(mode="ask")

        # User approves
        allowed, msg = policy.check_permission("filesystem.write_file", {"path": "a.txt"}, confirm_fn=lambda _: True)
        self.assertTrue(allowed)

        # User denies
        allowed, msg = policy.check_permission("filesystem.write_file", {"path": "a.txt"}, confirm_fn=lambda _: False)
        self.assertFalse(allowed)
        self.assertIn("denied execution", msg)

    def test_workspace_escape_rejected(self):
        with tempfile.TemporaryDirectory() as ws:
            policy = SafetyPolicy(mode="auto", workspace_dir=ws)
            allowed, msg = policy.check_permission("filesystem.read_file", {"path": "../../../etc/passwd"})
            self.assertFalse(allowed)
            self.assertIn("attempts to escape workspace", msg)


if __name__ == "__main__":
    unittest.main()
