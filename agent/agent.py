import json
import traceback

from agent.llm import query_llm
from agent.memory import Memory
from agent.planner import Planner
from agent.tools import read_file, write_file, edit_file, run_command

SYSTEM_PROMPT = """You are an autonomous AI coding agent.
You must EXACTLY output valid JSON matching this schema:
{
    "action": "read_file" | "write_file" | "edit_file" | "run_command" | "finish",
    "path": "string (optional)",
    "content": "string (optional)",
    "command": "string (optional)",
    "summary": "string (only for finish)"
}
Do not output ANY other text. Just the JSON object.

Allowed Actions:
- read_file: Provide 'path'
- write_file: Provide 'path' and 'content'
- edit_file: Provide 'path' and 'content' (use REPLACE: <old> WITH: <new> format)
- run_command: Provide 'command'
- finish: Provide 'summary'
"""

class Agent:
    def __init__(self, goal: str, chat_id: str, workspace_dir: str):
        self.goal = goal
        self.workspace_dir = workspace_dir
        self.memory = Memory(chat_id=chat_id, workspace_dir=workspace_dir)
        self.planner = Planner(query_llm, workspace_dir=workspace_dir)
        self.max_iterations = 40

    def run(self):
        print(f"Goal: {self.goal}")
        print(f"Chat Session ID: {self.memory.chat_id}")
        print(f"Workspace Directory: {self.workspace_dir}")
        
        # 1. Generate Plan
        print("Generating plan...")
        plan = self.planner.generate_plan(self.goal)
        print("Plan:")
        print(self.planner.get_plan_str())
        print("-" * 40)

        # 2. Main Loop
        for i in range(self.max_iterations):
            print(f"\n--- Iteration {i+1} ---")
            action_obj = self._decide_next_action()
            
            if not action_obj:
                print("Failed to decide next action.")
                break
                
            action_type = action_obj.get("action", "unknown")
            print(f"Action: {action_type}")
            
            if action_type == "finish":
                summary = action_obj.get("summary", "Task complete.")
                print(f"Summary: {summary}")
                self.memory.add_action(action_obj, "Finished.")
                break
                
            result = self._execute_action(action_obj)
            print(f"Result:\n{result}")
            
            self.memory.add_action(action_obj, getattr(result, "strip", lambda: str(result))()[:500] + "...")
            
            # Periodically summarize if history gets too long
            # self.memory.summarize(query_llm) # can be disabled if local LLM is slow for summaries
            
        print("\nAgent finished execution.")

    def _get_file_content(self, filename: str) -> str:
        import os
        filepath = os.path.join(self.workspace_dir, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    return f.read()
            except Exception:
                pass
        return ""

    def _decide_next_action(self) -> dict:
        prompt = f"Goal: {self.goal}\n\n"
        prompt += f"Current Plan:\n{self.planner.get_plan_str()}\n\n"
        
        current_state = self._get_file_content("current.md")
        if current_state.strip() and current_state.strip() != "# Current":
            prompt += f"Current State from previous session:\n{current_state}\n\n"
            
        next_steps = self._get_file_content("next.md")
        if next_steps.strip() and next_steps.strip() != "# Next":
            prompt += f"Proposed Next Steps from previous session:\n{next_steps}\n\n"

        prompt += "Recent Actions:\n"
        
        recent = self.memory.get_recent_actions(3)
        if not recent:
            prompt += "None.\n"
        else:
            for r in recent:
                prompt += f"- Action: {r['action']}\n  Result: {r['result']}\n"
                
        prompt += "\nWhat is the next STRICT JSON action to take?"
        
        response_text = query_llm(prompt, SYSTEM_PROMPT, temperature=0.1, json_mode=True)
        
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            print("LLM did not return valid JSON.")
            print("Raw response:", response_text)
            return {"action": "finish", "summary": "Failed due to invalid JSON."}

    def _execute_action(self, action_obj: dict) -> str:
        action = action_obj.get("action")
        
        if action == "read_file":
            path = action_obj.get("path")
            if not path: return "Error: Missing 'path'"
            self.memory.add_known_file(path)
            return read_file(path, self.workspace_dir)
            
        elif action == "write_file":
            path = action_obj.get("path")
            content = action_obj.get("content")
            if not path or not content: return "Error: Missing 'path' or 'content'"
            self.memory.add_known_file(path)
            return write_file(path, content, self.workspace_dir)
            
        elif action == "edit_file":
            path = action_obj.get("path")
            content = action_obj.get("content")
            if not path or not content: return "Error: Missing 'path' or 'content' (for patch)"
            self.memory.add_known_file(path)
            return edit_file(path, content, self.workspace_dir)
            
        elif action == "run_command":
            cmd = action_obj.get("command")
            if not cmd: return "Error: Missing 'command'"
            return run_command(cmd, self.workspace_dir)
            
        return f"Error: Unknown action '{action}'"
        
    def save_state(self):
        """Save the current execution state to current.md and next.md"""
        print("\nSaving session state to current.md and next.md...")
        prompt = (
            f"Goal: {self.goal}\n\n"
            f"Current Plan:\n{self.planner.get_plan_str()}\n\n"
            "Recent Actions:\n"
        )
        recent = self.memory.get_recent_actions(10)
        if not recent:
            prompt += "None.\n"
        else:
            for r in recent:
                prompt += f"- Action: {r['action']}\n  Result: {r['result'][:200]}\n"
                
        prompt += (
            "\nSummarize the current progress based on the recent actions. "
            "Then output what the next immediate steps should be. "
            "Format your output EXACTLY as follows:\n"
            "CURRENT:\n<summary of what has been done>\n"
            "NEXT:\n<list of what needs to be done next>"
        )
        
        try:
            import os
            response = query_llm(prompt, "You are a helpful assistant summarizing state.", temperature=0.1, json_mode=False)
            
            current_content = "# Current\n\n"
            next_content = "# Next\n\n"
            
            if "NEXT:" in response:
                parts = response.split("NEXT:")
                curr_part = parts[0].replace("CURRENT:", "").strip()
                next_part = parts[1].strip()
                current_content += curr_part + "\n"
                next_content += next_part + "\n"
            else:
                current_content += response + "\n"
                
            with open(os.path.join(self.workspace_dir, "current.md"), "w") as f:
                f.write(current_content)
                
            with open(os.path.join(self.workspace_dir, "next.md"), "w") as f:
                f.write(next_content)
            print("Session state saved successfully.")
        except Exception as e:
            print(f"Failed to save state: {e}")
