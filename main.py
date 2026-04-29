import argparse
import sys
import os
import subprocess
import uuid
from agent.agent import Agent
from agent.config import CHAT_SESSIONS_DIR

def setup_new_workspace(chat_id):
    chat_dir = os.path.join(CHAT_SESSIONS_DIR, chat_id)
    os.makedirs(chat_dir, exist_ok=True)
    
    # Initialize git
    subprocess.run(["git", "init"], cwd=chat_dir, capture_output=True)
    
    # Create .gitignore for venv
    gitignore_path = os.path.join(chat_dir, ".gitignore")
    with open(gitignore_path, "w") as f:
        f.write("venv/\nenv/\n__pycache__/\n")
        
    # Create plan.md, current.md, next.md
    for f_name in ["plan.md", "current.md", "next.md"]:
        with open(os.path.join(chat_dir, f_name), "w") as f:
            f.write(f"# {f_name.split('.')[0].capitalize()}\n")
            
    # Setup venv
    print("Setting up virtual environment...")
    subprocess.run([sys.executable, "-m", "venv", "venv"], cwd=chat_dir, capture_output=True)
    
    return chat_dir

def interactive_ui():
    print("=== PyAgent Interactive UI ===")
    if not os.path.exists(CHAT_SESSIONS_DIR):
        os.makedirs(CHAT_SESSIONS_DIR)
        
    chats = [d for d in os.listdir(CHAT_SESSIONS_DIR) if os.path.isdir(os.path.join(CHAT_SESSIONS_DIR, d))]
    
    if not chats:
        print("No previous chat sessions found.")
    else:
        print("Existing chats:")
        for i, chat in enumerate(chats):
            print(f"[{i+1}] {chat}")
            
    print("\nOptions:")
    print("[N] Create a new chat session")
    print("[Q] Quit")
    
    while True:
        choice = input("\nSelect a chat to continue, or choose an option: ").strip().lower()
        if choice == 'q':
            sys.exit(0)
        elif choice == 'n':
            chat_id = input("Enter a name for the new chat session (or press enter for random): ").strip()
            if not chat_id:
                chat_id = str(uuid.uuid4())[:8]
            goal = input("Enter the goal for the new session: ").strip()
            if not goal:
                print("Goal is required for a new session.")
                continue
            workspace_dir = setup_new_workspace(chat_id)
            return chat_id, workspace_dir, goal
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(chats):
                    chat_id = chats[idx]
                    workspace_dir = os.path.join(CHAT_SESSIONS_DIR, chat_id)
                    goal = None # Will be read from plan.md by the agent
                    return chat_id, workspace_dir, goal
            except ValueError:
                pass
            print("Invalid choice, try again.")

def main():
    parser = argparse.ArgumentParser(description="Local AI Coding Agent")
    parser.add_argument("goal", type=str, nargs='?', default=None, help="The goal for the agent to achieve")
    parser.add_argument("-start", action="store_true", help="Start the interactive UI")
    
    args = parser.parse_args()
    
    chat_id = None
    workspace_dir = None
    goal = args.goal
    
    if args.start:
        chat_id, workspace_dir, goal = interactive_ui()
    elif goal:
        # Create a new session automatically
        chat_id = str(uuid.uuid4())[:8]
        print(f"Creating new chat session: {chat_id}")
        workspace_dir = setup_new_workspace(chat_id)
    else:
        parser.print_help()
        sys.exit(1)
        
    print("Initializing Agent...")
    exit_code = 0
    try:
        agent = Agent(goal=goal, chat_id=chat_id, workspace_dir=workspace_dir)
        agent.run()
    except KeyboardInterrupt:
        print("\nAgent interrupted by user.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        import traceback
        traceback.print_exc()
        exit_code = 1
    finally:
        if 'agent' in locals():
            agent.save_state()
        sys.exit(exit_code)

if __name__ == "__main__":
    main()
