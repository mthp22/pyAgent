import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agent.agent import Agent


class AgentIntegrationTests(unittest.TestCase):
    def test_agent_can_run_command_in_subfolder_cwd(self):
        responses = [
            '["Create requirements file", "Run verification command", "Finish"]',
            '{"action":"write_file","path":"Scrapper/requirements.txt","content":"requests\\nbeautifulsoup4\\n"}',
            '{"action":"run_command","command":"python3 -c \\"print(open(\'requirements.txt\').read().strip())\\"","cwd":"Scrapper","timeout_secs":20}',
            '{"action":"finish","summary":"done"}',
        ]

        with tempfile.TemporaryDirectory() as workspace:
            chat_id = "testchat1"

            def fake_query_llm(*_args, **_kwargs):
                if responses:
                    return responses.pop(0)
                return '{"action":"finish","summary":"done"}'

            with patch("agent.agent.query_llm", side_effect=fake_query_llm):
                agent = Agent(goal="test goal", chat_id=chat_id, workspace_dir=workspace, explicit_goal=True)
                agent.run()

            current_path = os.path.join(workspace, "current.md")
            next_path = os.path.join(workspace, "next.md")
            self.assertTrue(os.path.exists(current_path))
            self.assertTrue(os.path.exists(next_path))

            with open(os.path.join(workspace, "session.json"), "r", encoding="utf-8") as handle:
                session = json.load(handle)
            self.assertEqual(session.get("status"), "completed")

            recent = agent.memory.get_recent_actions(5)
            run_actions = [entry for entry in recent if entry.get("action", {}).get("action") == "run_command"]
            self.assertTrue(run_actions)
            self.assertIn("requests", run_actions[-1].get("result", ""))

    def test_timeout_updates_state_files(self):
        responses = [
            '["Run a command that times out", "Finish"]',
            '{"action":"run_command","command":"python3 -c \\"import time; time.sleep(2)\\"","timeout_secs":1}',
            '{"action":"finish","summary":"done"}',
        ]

        with tempfile.TemporaryDirectory() as workspace:
            chat_id = "testchat2"

            def fake_query_llm(*_args, **_kwargs):
                if responses:
                    return responses.pop(0)
                return '{"action":"finish","summary":"done"}'

            with patch("agent.agent.query_llm", side_effect=fake_query_llm):
                agent = Agent(goal="test timeout", chat_id=chat_id, workspace_dir=workspace, explicit_goal=True)
                agent.run()
                agent.save_state(reason="test-timeout", enrich_with_llm=False)

            with open(os.path.join(workspace, "current.md"), "r", encoding="utf-8") as handle:
                current_text = handle.read()
            with open(os.path.join(workspace, "next.md"), "r", encoding="utf-8") as handle:
                next_text = handle.read()

            self.assertIn("timed out", current_text.lower())
            self.assertTrue(len(next_text.strip()) > 0)

    def test_mark_interrupted_updates_session_metadata(self):
        with tempfile.TemporaryDirectory() as workspace:
            with patch("agent.agent.query_llm", return_value='["Step one"]'):
                agent = Agent(goal="interrupt goal", chat_id="testchat3", workspace_dir=workspace, explicit_goal=True)

            agent.mark_interrupted()
            agent.save_state(reason="interrupted", enrich_with_llm=False)

            with open(os.path.join(workspace, "session.json"), "r", encoding="utf-8") as handle:
                session = json.load(handle)
            self.assertEqual(session.get("status"), "interrupted")
            self.assertTrue(os.path.exists(os.path.join(workspace, "current.md")))
            self.assertTrue(os.path.exists(os.path.join(workspace, "next.md")))


if __name__ == "__main__":
    unittest.main()
