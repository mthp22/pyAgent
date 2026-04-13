# pyAgent: Local AI Coding Agent

A Python-based autonomous coding agent that uses CodeLlama (via Ollama) to accept a natural language goal, plan steps, and iteratively execute commands/edit files.

## Features
- Local LLM via Ollama API
- Goal-based planning and iterative execution
- Tool calling via strict JSON schema (read_file, write_file, edit_file, run_command, finish)
- Safe execution environment (restricts arbitrary paths, dangerous commands)
- Context management with `chat_sessions` history persistence

## Setup Instructions

1. Ensure you have Python 3.10+ installed.
2. Install [Ollama](https://ollama.com/) and download CodeLlama if you haven't already:
   ```bash
   ollama run codellama
   ```
   (Wait for it to download and run, then you can exit or leave the process running in the background depending on your OS).
   
3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## How to Run

Pass your goal as a quoted string to `main.py`:

```bash
python main.py "Create a Flask app with a /hello endpoint"
```

The agent will textually explain its planned steps and its exact JSON-based actions it is taking.
All actions/history are saved automatically in `chat_sessions/`.

### Configuration
You can edit `agent/config.py` or use environment variables:
- `LLM_ENDPOINT`: Set if your Ollama endpoint differs from `http://localhost:11434/api/generate`
- `MODEL_NAME`: Default is `codellama`.
- `WORKSPACE_DIR`: Default is your current working directory. The agent is locked to this directory.
