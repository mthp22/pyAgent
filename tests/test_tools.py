import os
import tempfile
import unittest

from agent.tools import edit_file, run_command


class EditFileTests(unittest.TestCase):
    def test_multi_block_edit_applies_transactionally(self):
        with tempfile.TemporaryDirectory() as workspace:
            file_path = os.path.join(workspace, "sample.txt")
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write("alpha\nbeta\ngamma\n")

            patch = "REPLACE: alpha WITH: ALPHA\nREPLACE: gamma WITH: GAMMA"
            result = edit_file("sample.txt", patch, workspace)
            self.assertIn("Successfully edited", result)

            with open(file_path, "r", encoding="utf-8") as handle:
                updated = handle.read()
            self.assertEqual(updated, "ALPHA\nbeta\nGAMMA\n")

    def test_transaction_rolls_back_when_a_block_is_missing(self):
        with tempfile.TemporaryDirectory() as workspace:
            file_path = os.path.join(workspace, "sample.txt")
            original_content = "alpha\nbeta\ngamma\n"
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(original_content)

            patch = "REPLACE: alpha WITH: ALPHA\nREPLACE: does_not_exist WITH: x"
            result = edit_file("sample.txt", patch, workspace)
            self.assertIn("No changes were applied", result)

            with open(file_path, "r", encoding="utf-8") as handle:
                unchanged = handle.read()
            self.assertEqual(unchanged, original_content)

    def test_malformed_patch_rejected(self):
        with tempfile.TemporaryDirectory() as workspace:
            file_path = os.path.join(workspace, "sample.txt")
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write("alpha\n")

            result = edit_file("sample.txt", "REPLACE: alpha", workspace)
            self.assertTrue(result.startswith("Error:"))


class RunCommandTests(unittest.TestCase):
    def test_run_command_respects_safe_cwd(self):
        with tempfile.TemporaryDirectory() as workspace:
            scraper_dir = os.path.join(workspace, "Scrapper")
            os.makedirs(scraper_dir, exist_ok=True)
            with open(os.path.join(scraper_dir, "requirements.txt"), "w", encoding="utf-8") as handle:
                handle.write("requests\n")

            command = "python3 -c \"print(open('requirements.txt').read().strip())\""
            output = run_command(command, workspace_dir=workspace, cwd="Scrapper", timeout_secs=20)
            self.assertIn("requests", output)

    def test_run_command_rejects_outside_cwd(self):
        with tempfile.TemporaryDirectory() as workspace:
            output = run_command("ls", workspace_dir=workspace, cwd="../", timeout_secs=10)
            self.assertIn("outside allowed workspace", output)

    def test_run_command_timeout(self):
        with tempfile.TemporaryDirectory() as workspace:
            output = run_command(
                "python3 -c \"import time; time.sleep(2)\"",
                workspace_dir=workspace,
                timeout_secs=1,
            )
            self.assertIn("timed out", output.lower())


if __name__ == "__main__":
    unittest.main()
