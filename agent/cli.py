import argparse
import json
import logging
import os
import subprocess
import sys
import uuid
from typing import Optional, Tuple

from agent.agent import Agent
from agent.config import CHAT_SESSIONS_DIR, SESSION_METADATA_FILE, load_config
from agent.mcp.client import MCPClientManager
from agent.mcp.registry import ToolRegistry
from agent.repo.profiler import RepoProfiler

logger = logging.getLogger(__name__)


def configure_logging(verbose: bool = False) -> None:
    """Configure root logging so warnings/errors are visible without spamming the console."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _write_atomic(path: str, content: str):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp_path, path)


def load_session_metadata(workspace_dir: str) -> dict:
    meta_path = os.path.join(workspace_dir, SESSION_METADATA_FILE)
    if not os.path.exists(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def initialize_or_update_session_metadata(workspace_dir: str, chat_id: str, goal: Optional[str]) -> dict:
    meta_path = os.path.join(workspace_dir, SESSION_METADATA_FILE)
    existing = load_session_metadata(workspace_dir)
    now = _now_iso()

    metadata = {
        "chat_id": chat_id,
        "goal": (goal or existing.get("goal", "")).strip(),
        "status": existing.get("status", "created"),
        "created_at": existing.get("created_at", now),
        "updated_at": now,
        "last_run_started_at": existing.get("last_run_started_at"),
        "last_run_finished_at": existing.get("last_run_finished_at"),
        "last_iteration": existing.get("last_iteration", 0),
        "max_iterations": existing.get("max_iterations", 40),
        "last_error": existing.get("last_error"),
        "plan_cursor": existing.get("plan_cursor", 0),
        "run_count": existing.get("run_count", 0),
        "last_action": existing.get("last_action"),
        "last_action_result": existing.get("last_action_result"),
    }

    _write_atomic(meta_path, json.dumps(metadata, indent=2))
    return metadata


def setup_new_workspace(chat_id: str):
    chat_dir = os.path.join(CHAT_SESSIONS_DIR, chat_id)
    os.makedirs(chat_dir, exist_ok=True)

    subprocess.run(["git", "init"], cwd=chat_dir, capture_output=True)

    gitignore_path = os.path.join(chat_dir, ".gitignore")
    if not os.path.exists(gitignore_path):
        with open(gitignore_path, "w", encoding="utf-8") as handle:
            handle.write("venv/\nenv/\n__pycache__/\n")

    for filename in ["plan.md", "current.md", "next.md"]:
        file_path = os.path.join(chat_dir, filename)
        if not os.path.exists(file_path):
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(f"# {filename.split('.')[0].capitalize()}\n")

    print("Setting up virtual environment...")
    subprocess.run([sys.executable, "-m", "venv", "venv"], cwd=chat_dir, capture_output=True)
    return chat_dir


def print_status():
    print("=== PyAgent Sessions Status ===")
    if not os.path.exists(CHAT_SESSIONS_DIR):
        print("No chat sessions directory found.")
        return

    chats = sorted(
        [entry for entry in os.listdir(CHAT_SESSIONS_DIR) if os.path.isdir(os.path.join(CHAT_SESSIONS_DIR, entry))]
    )
    if not chats:
        print("No chat sessions recorded.")
        return

    for c in chats:
        c_dir = os.path.join(CHAT_SESSIONS_DIR, c)
        meta = load_session_metadata(c_dir)
        status = meta.get("status", "unknown")
        goal = meta.get("goal", "(no goal)")
        updated = meta.get("updated_at", "-")
        print(f"- [{status.upper()}] ID: {c}")
        print(f"  Goal: {goal}")
        print(f"  Updated: {updated}")


def print_tools():
    print("=== Discovered MCP Tools ===")
    cfg = load_config()
    mgr = MCPClientManager(workspace_dir=os.getcwd())
    started = mgr.load_and_start(cfg.mcp.config)
    try:
        reg = ToolRegistry(client_manager=mgr)
        count = reg.discover_tools()
        print(f"Discovered {count} tools across {len(started)} MCP servers:\n")
        for tool_name, t in sorted(reg.tools.items()):
            print(f"- {tool_name} (from server '{t.server}'):")
            print(f"    {t.description}")
    finally:
        mgr.shutdown()


def test_mcp_servers():
    print("=== Testing MCP Servers Connectivity ===")
    cfg = load_config()
    mgr = MCPClientManager(workspace_dir=os.getcwd())
    results = mgr.load_and_start(cfg.mcp.config)
    try:
        for s_name, ok in results.items():
            status = "✓ ONLINE" if ok else "✗ FAILED"
            print(f"- Server '{s_name}': {status}")
    finally:
        mgr.shutdown()


def interactive_ui() -> Tuple[str, str, Optional[str], bool]:
    print("=== PyAgent Interactive Assistant ===")
    profiler = RepoProfiler(workspace_dir=os.getcwd())
    profile = profiler.profile()
    print(f"Working in repository: {os.getcwd()}")
    if profile.languages:
        print(f"Detected Languages: {', '.join(profile.languages)}")
    if profile.test_frameworks:
        print(f"Detected Test Frameworks: {', '.join(profile.test_frameworks)}")

    goal = input("\nWhat would you like me to work on? ").strip()
    if not goal:
        print("No goal specified. Exiting.")
        sys.exit(0)

    chat_id = str(uuid.uuid4())[:8]
    workspace_dir = os.getcwd()
    initialize_or_update_session_metadata(workspace_dir, chat_id, goal)
    return chat_id, workspace_dir, goal, True


def main():
    parser = argparse.ArgumentParser(description="pyAgent — Autonomous Local Coding Helper")
    parser.add_argument("goal", type=str, nargs="?", default=None, help="The goal for the agent to achieve")
    parser.add_argument("-start", action="store_true", help="Start the interactive UI")
    parser.add_argument("--resume", type=str, nargs="?", const="", default=None, help="Resume an existing session ID")
    parser.add_argument("--status", action="store_true", help="Display all known session statuses")
    parser.add_argument("--tools", action="store_true", help="List discovered MCP tools")
    parser.add_argument("--mcp", action="store_true", help="Test MCP server connectivity")
    parser.add_argument("--approval", type=str, choices=["safe", "ask", "auto"], default=None, help="Approval mode")
    parser.add_argument("--dry-run", action="store_true", help="Run with 'safe' approval mode (no mutating actions)")
    parser.add_argument("--workspace", type=str, default=None, help="Workspace directory to operate on")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose (debug) logging")

    args = parser.parse_args()

    configure_logging(verbose=args.verbose)

    if args.status:
        print_status()
        sys.exit(0)

    if args.tools:
        print_tools()
        sys.exit(0)

    if args.mcp:
        test_mcp_servers()
        sys.exit(0)

    workspace_dir = os.path.abspath(args.workspace) if args.workspace else os.getcwd()
    chat_id = None
    goal = args.goal
    explicit_goal = bool(goal)

    if args.approval:
        os.environ["APPROVAL_MODE"] = args.approval
    elif args.dry_run:
        os.environ["APPROVAL_MODE"] = "safe"

    if args.resume is not None:
        target_id = args.resume
        if not target_id:
            meta = load_session_metadata(workspace_dir)
            target_id = meta.get("chat_id")
        if not target_id:
            print("No active or specified session to resume.")
            sys.exit(1)
        chat_id = target_id
        meta = load_session_metadata(workspace_dir)
        goal = meta.get("goal", "")
        explicit_goal = False
        print(f"Resuming session: {chat_id} (Goal: {goal})")
    elif args.start or not goal:
        chat_id, workspace_dir, goal, explicit_goal = interactive_ui()
    else:
        chat_id = str(uuid.uuid4())[:8]
        print(f"Creating new session: {chat_id} in {workspace_dir}")
        initialize_or_update_session_metadata(workspace_dir, chat_id, goal)
        explicit_goal = True

    print(f"Initializing pyAgent on workspace: {workspace_dir}...")
    exit_code = 0
    agent = None

    try:
        agent = Agent(goal=goal or "", chat_id=chat_id, workspace_dir=workspace_dir, explicit_goal=explicit_goal)
        agent.run()
    except KeyboardInterrupt:
        print("\nAgent interrupted by user.")
        exit_code = 130
        if agent is not None:
            agent.mark_interrupted()
    except Exception as exc:
        print(f"\nAn error occurred: {exc}")
        import traceback

        traceback.print_exc()
        exit_code = 1
        if agent is not None:
            agent.mark_failed(str(exc))
    finally:
        if agent is not None:
            agent.save_state(reason="shutdown", enrich_with_llm=False)
        sys.exit(exit_code)
