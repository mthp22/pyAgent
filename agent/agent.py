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
    def __init__(self, goal: str):
        self.goal = goal
        self.memory = Memory()
        self.planner = Planner(query_llm)
        self.max_iterations = 20

    def run(self):
        print(f"Goal: {self.goal}")
        print(f"Chat Session ID: {self.memory.chat_id}")
        
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

    def _decide_next_action(self) -> dict:
        prompt = f"Goal: {self.goal}\n\n"
        prompt += f"Current Plan:\n{self.planner.get_plan_str()}\n\n"
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
            return read_file(path)
            
        elif action == "write_file":
            path = action_obj.get("path")
            content = action_obj.get("content")
            if not path or not content: return "Error: Missing 'path' or 'content'"
            self.memory.add_known_file(path)
            return write_file(path, content)
            
        elif action == "edit_file":
            path = action_obj.get("path")
            content = action_obj.get("content")
            if not path or not content: return "Error: Missing 'path' or 'content' (for patch)"
            self.memory.add_known_file(path)
            return edit_file(path, content)
            
        elif action == "run_command":
            cmd = action_obj.get("command")
            if not cmd: return "Error: Missing 'command'"
            return run_command(cmd)
            
        return f"Error: Unknown action '{action}'"
