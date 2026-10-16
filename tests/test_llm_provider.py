import unittest
from unittest.mock import patch

from agent.config import LLMConfig
from agent.llm import (
    LLMMessage,
    OllamaProvider,
    ToolCall,
    ToolDefinition,
    get_llm_provider,
)


class TestLLMProvider(unittest.TestCase):
    def test_message_and_tool_serialization(self):
        tool = ToolDefinition(
            name="filesystem.read_file",
            description="Reads file content",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
        ollama_tool = tool.to_ollama_format()
        self.assertEqual(ollama_tool["type"], "function")
        self.assertEqual(ollama_tool["function"]["name"], "filesystem.read_file")

        msg = LLMMessage(
            role="assistant",
            content="I will read the file.",
            tool_calls=[ToolCall(id="call_1", name="filesystem.read_file", arguments={"path": "main.py"})],
        )
        msg_dict = msg.to_dict()
        self.assertEqual(msg_dict["role"], "assistant")
        self.assertEqual(len(msg_dict["tool_calls"]), 1)
        self.assertEqual(msg_dict["tool_calls"][0]["function"]["name"], "filesystem.read_file")

    @patch.object(OllamaProvider, "_http_post")
    def test_ollama_generate(self, mock_http_post):
        mock_http_post.return_value = {"response": "Hello world from Ollama"}

        provider = OllamaProvider(model="test-model", endpoint="http://localhost:11434")
        result = provider.generate("Hi")

        self.assertEqual(result, "Hello world from Ollama")
        mock_http_post.assert_called_once()

    @patch.object(OllamaProvider, "_http_post")
    def test_ollama_chat_with_tool_calls(self, mock_http_post):
        mock_http_post.return_value = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "filesystem.read_file",
                            "arguments": {"path": "README.md"},
                        }
                    }
                ],
            },
            "done_reason": "stop",
        }

        provider = OllamaProvider(model="test-model")
        messages = [LLMMessage(role="user", content="Read README.md")]
        tools = [
            ToolDefinition(
                name="filesystem.read_file",
                description="Read a file",
                parameters={"type": "object"},
            )
        ]

        response = provider.chat(messages=messages, tools=tools)

        self.assertTrue(response.has_tool_calls)
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(response.tool_calls[0].name, "filesystem.read_file")
        self.assertEqual(response.tool_calls[0].arguments, {"path": "README.md"})

    def test_get_llm_provider_factory(self):
        cfg = LLMConfig(provider="ollama", endpoint="http://localhost:11434", timeout=60)
        provider = get_llm_provider(model="custom:latest", config=cfg)

        self.assertIsInstance(provider, OllamaProvider)
        self.assertEqual(provider.model, "custom:latest")
        self.assertEqual(provider.timeout, 60)


if __name__ == "__main__":
    unittest.main()
