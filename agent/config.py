import os
from dataclasses import dataclass, field
from typing import List, Optional

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None  # type: ignore


# Legacy constant exports for backwards compatibility
MODEL_NAME = os.environ.get("PYAGENT_MODEL", os.environ.get("MODEL_NAME", "gemma4:latest"))
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))
COMMAND_TIMEOUT = 30
SLOW_COMMAND_TIMEOUT = 180
MAX_COMMAND_TIMEOUT = 600
MAX_ITERATIONS = 40
CHAT_SESSIONS_DIR = "Chats"
SESSION_METADATA_FILE = "session.json"
DEFAULT_TIMEOUT_SECS = 30
MAX_TIMEOUT_SECS = 600

ALLOWED_COMMANDS = [
    "python",
    "python3",
    "pip",
    "pip3",
    "pytest",
    "ls",
    "cat",
    "echo",
    "mkdir",
    "touch",
    "git",
    "source",
    "cd",
    "ruff",
    "mypy",
    "npm",
    "pnpm",
    "yarn",
    "cargo",
    "go",
]

DANGEROUS_FLAGS = ["-rf", "sudo"]


@dataclass
class AgentConfig:
    model: str = "gemma4:latest"
    max_iterations: int = 50
    approval_mode: str = "ask"  # "safe", "ask", "auto"
    workspace: str = "."


@dataclass
class LLMConfig:
    provider: str = "ollama"
    endpoint: str = "http://localhost:11434"
    timeout: int = 120


@dataclass
class ContextConfig:
    max_tokens: int = 12000
    history_limit: int = 30
    auto_compact: bool = True


@dataclass
class SafetyConfig:
    allow_network: bool = False
    allow_package_install: bool = False
    allow_git_push: bool = False
    allowed_commands: List[str] = field(default_factory=lambda: list(ALLOWED_COMMANDS))
    dangerous_flags: List[str] = field(default_factory=lambda: list(DANGEROUS_FLAGS))


@dataclass
class MCPConfig:
    config: str = ".mcp/servers.json"


@dataclass
class PyAgentConfig:
    agent: AgentConfig = field(default_factory=AgentConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)


def _parse_toml_file(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    if tomllib is not None:
        try:
            with open(path, "rb") as f:
                return tomllib.load(f)
        except Exception:
            return {}
    return {}


def load_config(config_path: Optional[str] = None, workspace_dir: Optional[str] = None) -> PyAgentConfig:
    workspace = workspace_dir or os.environ.get("WORKSPACE_DIR", os.getcwd())
    cfg_file = config_path or os.path.join(workspace, "pyagent.toml")

    parsed: dict = {}
    if os.path.exists(cfg_file):
        parsed = _parse_toml_file(cfg_file)

    agent_data = parsed.get("agent", {})
    llm_data = parsed.get("llm", {})
    ctx_data = parsed.get("context", {})
    safety_data = parsed.get("safety", {})
    mcp_data = parsed.get("mcp", {})

    agent_model = os.environ.get(
        "PYAGENT_MODEL",
        os.environ.get("MODEL_NAME", agent_data.get("model", "gemma4:latest")),
    )
    agent_cfg = AgentConfig(
        model=agent_model,
        max_iterations=int(os.environ.get("MAX_ITERATIONS", agent_data.get("max_iterations", 50))),
        approval_mode=os.environ.get("APPROVAL_MODE", agent_data.get("approval_mode", "ask")),
        workspace=os.environ.get("WORKSPACE_DIR", agent_data.get("workspace", workspace)),
    )

    llm_endpoint = os.environ.get(
        "LLM_ENDPOINT",
        os.environ.get("OLLAMA_HOST", llm_data.get("endpoint", "http://localhost:11434")),
    )
    llm_cfg = LLMConfig(
        provider=os.environ.get("LLM_PROVIDER", llm_data.get("provider", "ollama")),
        endpoint=llm_endpoint,
        timeout=int(os.environ.get("LLM_TIMEOUT", llm_data.get("timeout", 120))),
    )

    ctx_cfg = ContextConfig(
        max_tokens=int(ctx_data.get("max_tokens", 12000)),
        history_limit=int(ctx_data.get("history_limit", 30)),
        auto_compact=bool(ctx_data.get("auto_compact", True)),
    )

    safety_cfg = SafetyConfig(
        allow_network=bool(safety_data.get("allow_network", False)),
        allow_package_install=bool(safety_data.get("allow_package_install", False)),
        allow_git_push=bool(safety_data.get("allow_git_push", False)),
        allowed_commands=safety_data.get("allowed_commands", list(ALLOWED_COMMANDS)),
        dangerous_flags=safety_data.get("dangerous_flags", list(DANGEROUS_FLAGS)),
    )

    mcp_cfg = MCPConfig(
        config=os.environ.get("MCP_CONFIG", mcp_data.get("config", ".mcp/servers.json")),
    )

    return PyAgentConfig(
        agent=agent_cfg,
        llm=llm_cfg,
        context=ctx_cfg,
        safety=safety_cfg,
        mcp=mcp_cfg,
    )
