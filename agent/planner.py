import json
import os
from typing import List

class Planner:
    def __init__(self, llm_query_fn, workspace_dir: str):
        self.llm_query_fn = llm_query_fn
        self.workspace_dir = workspace_dir
        self.plan_file = os.path.join(self.workspace_dir, "plan.md")
        self.current_plan: List[str] = []
        
        # Load existing plan if present
        if os.path.exists(self.plan_file):
            with open(self.plan_file, "r") as f:
                content = f.read()
                lines = [l.strip() for l in content.split('\n') if l.strip()]
                # Skip markdown headers when loading
                self.current_plan = [l for l in lines if not l.startswith('#')]
        
    def generate_plan(self, goal: str) -> List[str]:
        # If goal is None, use the existing plan if available
        if not goal and self.current_plan:
            return self.current_plan
            
        """Generates a step-by-step plan."""
        system_prompt = (
            "You are an expert software architect planning a list of steps to achieve a goal. "
            "Return ONLY a JSON array of strings, where each string is a clear, actionable step."
        )
        prompt = f"Goal: {goal}\n\nList the steps to achieve this goal."
        
        response_text = self.llm_query_fn(prompt, system_prompt, json_mode=True)
        try:
            plan = json.loads(response_text)
            if isinstance(plan, list):
                self.current_plan = plan
            elif isinstance(plan, dict) and "steps" in plan:
                self.current_plan = plan["steps"]
            else:
                self.current_plan = [response_text] # Fallback
        except json.JSONDecodeError:
            self.current_plan = ["Analyze the goal.", "Execute necessary commands.", "Finish."]
            
        self._write_plan_to_file()
        return self.current_plan
    
    def _write_plan_to_file(self):
        with open(self.plan_file, "w") as f:
            f.write("# Plan\n\n")
            f.write(self.get_plan_str() + "\n")

    def update_plan(self, current_state_summary: str):
        """Allows planner to revise based on progress."""
        # Simple implementation: just keep current plan. 
        pass
        
    def get_plan_str(self) -> str:
        if not self.current_plan:
            return "No plan yet."
        # Don't re-number if they already start with numbers
        formatted_plan = []
        for i, step in enumerate(self.current_plan):
            if step[0].isdigit() and ". " in step:
                formatted_plan.append(step)
            else:
                formatted_plan.append(f"{i+1}. {step}")
        return "\n".join(formatted_plan)
