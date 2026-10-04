import os

# LLM Configuration
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://localhost:11434/api/generate")
MODEL_NAME = os.environ.get("MODEL_NAME", "qwen2.5-coder:7b")

# Timeouts in seconds
LLM_TIMEOUT = 120
COMMAND_TIMEOUT = 30
SLOW_COMMAND_TIMEOUT = 300
MAX_COMMAND_TIMEOUT = 600

# Safety
ALLOWED_COMMANDS = [
    'python',
    'python3',
    'pip',
    'pip3',
    'pytest',
    'ls',
    'cat',
    'echo',
    'mkdir',
    'touch',
    'git',
    'source',
    'cd',
]
DANGEROUS_FLAGS = ['-rf', 'sudo']
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", os.getcwd()) # Constrain agent to current dir

CHAT_SESSIONS_DIR = os.path.join(WORKSPACE_DIR, "Chats")

SESSION_METADATA_FILE = "session.json"