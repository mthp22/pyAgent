import argparse
import json
import os
import subprocess
import sys
import uuid
from typing import Optional, Tuple

from agent.agent import Agent
from agent.config import CHAT_SESSIONS_DIR, SESSION_METADATA_FILE


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


def interactive_ui() -> Tuple[str, str, Optional[str], bool]:
    print("=== PyAgent Interactive UI ===")
    if not os.path.exists(CHAT_SESSIONS_DIR):
        os.makedirs(CHAT_SESSIONS_DIR)

    chats = sorted(
        [entry for entry in os.listdir(CHAT_SESSIONS_DIR) if os.path.isdir(os.path.join(CHAT_SESSIONS_DIR, entry))]
    )

    if not chats:
        print("No previous chat sessions found.")
    else:
        print("Existing chats:")
        for idx, chat in enumerate(chats, start=1):
            print(f"[{idx}] {chat}")

    print("\nOptions:")
    print("[N] Create a new chat session")
    print("[Q] Quit")

    while True:
        choice = input("\nSelect a chat to continue, or choose an option: ").strip().lower()
        if choice == "q":
            sys.exit(0)

        if choice == "n":
            chat_id = input("Enter a name for the new chat session (or press enter for random): ").strip()
            if not chat_id:
                chat_id = str(uuid.uuid4())[:8]

            goal = input("Enter the goal for the new session: ").strip()
            if not goal:
                print("Goal is required for a new session.")
                continue

            workspace_dir = setup_new_workspace(chat_id)
            initialize_or_update_session_metadata(workspace_dir, chat_id, goal)
            return chat_id, workspace_dir, goal, True

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(chats):
                chat_id = chats[idx]
                workspace_dir = os.path.join(CHAT_SESSIONS_DIR, chat_id)
                metadata = load_session_metadata(workspace_dir)
                restored_goal = metadata.get("goal") if isinstance(metadata.get("goal"), str) else None
                initialize_or_update_session_metadata(workspace_dir, chat_id, restored_goal)
                return chat_id, workspace_dir, restored_goal, False
        except ValueError:
            pass

        print("Invalid choice, try again.")


def main():
    parser = argparse.ArgumentParser(description="Local AI Coding Agent")
    parser.add_argument("goal", type=str, nargs="?", default=None, help="The goal for the agent to achieve")
    parser.add_argument("-start", action="store_true", help="Start the interactive UI")
    args = parser.parse_args()

    chat_id = None
    workspace_dir = None
    goal = args.goal
    explicit_goal = bool(goal)

    if args.start:
        chat_id, workspace_dir, goal, explicit_goal = interactive_ui()
    elif goal:
        chat_id = str(uuid.uuid4())[:8]
        print(f"Creating new chat session: {chat_id}")
        workspace_dir = setup_new_workspace(chat_id)
        initialize_or_update_session_metadata(workspace_dir, chat_id, goal)
        explicit_goal = True
    else:
        parser.print_help()
        sys.exit(1)

    print("Initializing Agent...")
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
            agent.save_state(reason="shutdown", enrich_with_llm=True)
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
