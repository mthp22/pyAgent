import tempfile
import unittest
from unittest.mock import patch

from agent.agent import Agent
from agent.llm.base import LLMResponse, ToolCall
from agent.mcp.registry import RegisteredTool


class FakeProvider:
    """Minimal LLM provider stub that returns canned responses."""

    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.last_tools = None

    def chat(self, messages, tools=None, temperature=0.2, json_mode=False):
        self.last_tools = tools
        if self._raises:
            raise self._raises
        return self._response


def _make_agent(workspace, provider):
    agent = Agent(goal="test goal", chat_id="tc", workspace_dir=workspace, explicit_goal=True, llm_provider=provider)
    # Register a fake MCP tool so the tool-calling path is exercised.
    agent.tool_registry.tools["filesystem.read_file"] = RegisteredTool(
        namespaced_name="filesystem.read_file",
        raw_name="read_file",
        server="filesystem",
        description="Read a file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    return agent


class ToolCallingDecisionTests(unittest.TestCase):
    def test_tool_call_is_converted_to_action(self):
        provider = FakeProvider(
            response=LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_1", name="filesystem.read_file", arguments={"path": "README.md"})],
            )
        )
        with tempfile.TemporaryDirectory() as workspace:
            agent = _make_agent(workspace, provider)
            action = agent._decide_next_action()

        self.assertEqual(action, {"action": "filesystem.read_file", "path": "README.md"})
        # The live MCP tool catalog must be advertised to the provider.
        self.assertIsNotNone(provider.last_tools)
        self.assertIn("filesystem.read_file", [t.name for t in provider.last_tools])

    def test_json_content_used_when_no_tool_call(self):
        provider = FakeProvider(response=LLMResponse(content='{"action":"finish","summary":"ok"}'))
        with tempfile.TemporaryDirectory() as workspace:
            agent = _make_agent(workspace, provider)
            action = agent._decide_next_action()

        self.assertEqual(action, {"action": "finish", "summary": "ok"})

    def test_provider_failure_falls_back_to_json_query(self):
        provider = FakeProvider(raises=RuntimeError("provider down"))
        with tempfile.TemporaryDirectory() as workspace:
            agent = _make_agent(workspace, provider)
            with patch("agent.agent.query_llm", return_value='{"action":"finish","summary":"fallback"}'):
                action = agent._decide_next_action()

        self.assertEqual(action, {"action": "finish", "summary": "fallback"})

    def test_invalid_json_returns_none(self):
        provider = FakeProvider(response=LLMResponse(content="not json at all"))
        with tempfile.TemporaryDirectory() as workspace:
            agent = _make_agent(workspace, provider)
            with patch("agent.agent.query_llm", return_value="still not json"):
                action = agent._decide_next_action()

        self.assertIsNone(action)


    def test_empty_provider_response_falls_back_to_json_query(self):
        # OllamaProvider returns "{}" content when a request fails rather than raising.
        provider = FakeProvider(response=LLMResponse(content="{}"))
        with tempfile.TemporaryDirectory() as workspace:
            agent = _make_agent(workspace, provider)
            with patch("agent.agent.query_llm", return_value='{"action":"finish","summary":"recovered"}'):
                action = agent._decide_next_action()

        self.assertEqual(action, {"action": "finish", "summary": "recovered"})


if __name__ == "__main__":
    unittest.main()
