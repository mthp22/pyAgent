import os

# LLM Configuration
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://localhost:11434/api/generate")
# We will use CodeLlama via Ollama as requested
MODEL_NAME = os.environ.get("MODEL_NAME", "codellama")

# Timeouts
LLM_TIMEOUT = 120 # seconds
COMMAND_TIMEOUT = 30 # seconds

# Safety
ALLOWED_COMMANDS = ['python', 'pip', 'pytest', 'ls', 'cat', 'echo', 'mkdir', 'touch']
DANGEROUS_FLAGS = ['-rf', 'sudo']
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", os.getcwd()) # Constrain agent to current dir

# Directories
CHAT_SESSIONS_DIR = os.path.join(WORKSPACE_DIR, "chat_sessions")
