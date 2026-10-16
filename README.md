# pyAgent — Autonomous Local Coding Helper & Runtime

pyAgent is a free, local, open-source coding agent designed to help developers build, modify, debug, test, and maintain software using a locally hosted LLM (Ollama default, with pluggable providers).

> **Core Philosophy**: Generating code is not completion. Functional validation is completion. The agent never claims "Done" without automated test or execution evidence.

---

## Key Features

- **MCP-First Architecture**: Built around the Model Context Protocol (MCP). The live tool catalog discovered from every server is advertised to the model via native tool calling, with single-turn JSON actions as a fallback. Out of the box, zero-external-dependency servers are provided for:
  - `filesystem`: workspace-confined atomic file read, write, targeted patch-editing, directory listing, and glob search.
  - `git`: working tree inspection, diffs, log history, branch management, and atomic commits.
  - `terminal`: sandboxed command runner with strict allowlists and dangerous flag filters (`-rf`, `sudo`).
- **Repository Profiling & Intelligence**: Automatically identifies languages (Python, TypeScript/JavaScript, Rust, Go), test runners (`pytest`, `vitest`, `cargo test`), linters, build systems, and active Git state before writing code.
- **Living Planner**: Dynamic, model-driven replanning. When tests fail or unexpected blockers arise, the agent diagnoses errors, injects targeted fix steps, and heals without manual intervention.
- **Autonomous Validation Engine**: Discovers and runs project tests and builds. Classifies failures (own changes vs. missing dependencies vs. environment) and feeds diagnostics back into the loop.
- **3-Tier Permission & Safety Model**:
  - `safe`: Read-only inspections only; mutations are blocked.
  - `ask`: Mutating tools prompt for confirmation.
  - `auto`: Fully autonomous execution confined to the project workspace.
- **Hardened Command Execution**: the `terminal` tool parses commands into an argument vector and runs them **without a shell**, so metacharacters (`;`, `&&`, `|`, backticks, `$()`, redirections) cannot chain commands past the allowlist. The first token must appear in `[safety].allowed_commands`, and `dangerous_flags` are rejected. The effective policy from `pyagent.toml` is propagated to the sandboxed MCP servers so both execution paths enforce identical rules.
- **Symlink-safe Workspace Confinement**: file paths are resolved with `realpath`, so a symlink inside the workspace cannot be used to read or write outside it.
- **Context Engine & Structured Persistence**:
  - Sliding context window budgeting with tool output compaction and artifact archiving.
  - Append-only event streaming in `history.jsonl`, living plans in `plan.json`, deterministic state snapshots in `current.md` & `next.md`, and uncompressed execution outputs in `artifacts/`.

---

## Installation & Setup

1. **Prerequisites**: Python 3.11+ and [Ollama](https://ollama.com/) running locally.
2. **Pull your preferred model**:
   ```bash
   ollama run gemma4:latest
   # or
   ollama run qwen2.5-coder:7b
   ```
3. **Install pyAgent**:
   ```bash
   pip install -e .
   ```

---

## Configuration (`pyagent.toml`)

All runtime settings can be managed via `pyagent.toml`:

```toml
[agent]
model = "gemma4:latest"
max_iterations = 50
approval_mode = "ask" # "safe" | "ask" | "auto"
workspace = "."

[llm]
provider = "ollama"
endpoint = "http://localhost:11434"
timeout = 120

[context]
max_tokens = 12000
history_limit = 30
auto_compact = true

[safety]
allow_network = false
allow_package_install = false
allow_git_push = false
allowed_commands = ["python", "python3", "pytest", "git", "ls", "cat", "echo", "npm", "cargo"]
dangerous_flags = ["-rf", "sudo"]

[mcp]
config = ".mcp/servers.json"
```

---

## CLI Usage

Run tasks directly:
```bash
pyagent "Add endpoint /health to the FastAPI app and write tests"
```

Interactive assistant mode:
```bash
pyagent
```

Inspect discovered MCP tools:
```bash
pyagent --tools
```

Test MCP server connectivity:
```bash
pyagent --mcp
```

Check session statuses:
```bash
pyagent --status
```

Resume a previous session:
```bash
pyagent --resume [session_id]
```

Run in dry-run / safe mode (no mutations):
```bash
pyagent --dry-run "Investigate why the test suite is failing"
```

Override approval mode:
```bash
pyagent --approval auto "Refactor utils.py"
```

---

## Running Tests

pyAgent comes with a full test suite covering all modules:

```bash
python -m unittest discover tests
```
