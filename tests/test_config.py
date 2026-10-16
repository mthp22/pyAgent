import os
import tempfile
import unittest

from agent.config import (
    load_config,
)


class TestConfig(unittest.TestCase):
    def test_default_config(self):
        config = load_config(config_path="/non_existent_path.toml")
        self.assertEqual(config.agent.model, "gemma4:latest")
        self.assertEqual(config.agent.approval_mode, "ask")
        self.assertEqual(config.llm.provider, "ollama")
        self.assertEqual(config.llm.endpoint, "http://localhost:11434")
        self.assertEqual(config.context.max_tokens, 12000)
        self.assertTrue(config.context.auto_compact)
        self.assertIn("pytest", config.safety.allowed_commands)
        self.assertIn("-rf", config.safety.dangerous_flags)
        self.assertEqual(config.mcp.config, ".mcp/servers.json")

    def test_custom_toml_loading(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            toml_content = """
[agent]
model = "deepseek-coder:6.7b"
max_iterations = 25
approval_mode = "safe"
workspace = "/custom/path"

[llm]
provider = "ollama"
endpoint = "http://127.0.0.1:11434"
timeout = 60

[context]
max_tokens = 8000
history_limit = 15
auto_compact = false

[safety]
allow_network = true
allow_package_install = false
allow_git_push = false
allowed_commands = ["git", "pytest"]
dangerous_flags = ["sudo"]

[mcp]
config = "custom_mcp.json"
"""
            toml_path = os.path.join(tmp_dir, "pyagent.toml")
            with open(toml_path, "w", encoding="utf-8") as f:
                f.write(toml_content)

            config = load_config(config_path=toml_path)
            self.assertEqual(config.agent.model, "deepseek-coder:6.7b")
            self.assertEqual(config.agent.max_iterations, 25)
            self.assertEqual(config.agent.approval_mode, "safe")
            self.assertEqual(config.agent.workspace, "/custom/path")
            self.assertEqual(config.llm.timeout, 60)
            self.assertEqual(config.context.max_tokens, 8000)
            self.assertFalse(config.context.auto_compact)
            self.assertTrue(config.safety.allow_network)
            self.assertEqual(config.safety.allowed_commands, ["git", "pytest"])
            self.assertEqual(config.mcp.config, "custom_mcp.json")

    def test_env_var_override(self):
        os.environ["PYAGENT_MODEL"] = "qwen2.5-coder:7b"
        try:
            config = load_config()
            self.assertEqual(config.agent.model, "qwen2.5-coder:7b")
        finally:
            os.environ.pop("PYAGENT_MODEL", None)


if __name__ == "__main__":
    unittest.main()
