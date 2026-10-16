import unittest

from agent.context.manager import ContextManager, estimate_tokens


class TestContextManager(unittest.TestCase):
    def test_estimate_tokens(self):
        text = "Hello world! This is a test."
        tokens = estimate_tokens(text)
        self.assertTrue(tokens > 0)
        self.assertEqual(estimate_tokens(""), 1)

    def test_compact_tool_result_small(self):
        cm = ContextManager(max_tool_output_chars=500)
        short_res = "Short result text."
        self.assertEqual(cm.compact_tool_result("read_file", short_res), short_res)

    def test_compact_tool_result_large(self):
        cm = ContextManager(max_tool_output_chars=100)
        saved_artifacts = {}

        def fake_saver(filename, content):
            saved_artifacts[filename] = content
            return f"artifacts/{filename}"

        large_res = "A" * 300
        compacted = cm.compact_tool_result("terminal.run_command", large_res, artifact_saver=fake_saver)
        self.assertIn("truncated", compacted)
        self.assertIn("artifacts/terminal_run_command_output.txt", compacted)
        self.assertIn("terminal_run_command_output.txt", saved_artifacts)

    def test_build_system_prompt(self):
        cm = ContextManager()
        cm.add_relevant_file("src/main.py")
        prompt = cm.build_system_prompt(
            base_prompt="Base prompt",
            project_summary="Python project",
            plan_str="1. Step one",
            current_task="Step one",
        )
        self.assertIn("Base prompt", prompt)
        self.assertIn("--- PROJECT PROFILE ---", prompt)
        self.assertIn("--- RELEVANT FILES ---", prompt)
        self.assertIn("src/main.py", prompt)
        self.assertIn("--- LIVING PLAN ---", prompt)
        self.assertIn("--- CURRENT TASK ---", prompt)

    def test_compact_history(self):
        cm = ContextManager()
        history = [
            {"action": {"action": "tool1"}, "result": "Result 1" * 100},
            {"action": {"action": "tool2"}, "result": "Result 2" * 100},
            {"action": {"action": "tool3"}, "result": "Result 3" * 100},
        ]
        compacted = cm.compact_history(history, max_chars=1800)
        self.assertTrue(len(compacted) <= 3)
        self.assertEqual(compacted[-1]["action"]["action"], "tool3")


if __name__ == "__main__":
    unittest.main()
