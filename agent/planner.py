import json
from typing import List

class Planner:
    def __init__(self, llm_query_fn):
        self.llm_query_fn = llm_query_fn
        self.current_plan: List[str] = []
        
    def generate_plan(self, goal: str) -> List[str]:
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
            
        return self.current_plan
    
    def update_plan(self, current_state_summary: str):
        """Allows planner to revise based on progress."""
        # Simple implementation: just keep current plan. 
        # In a more advanced version, we'd query the LLM to rewrite the plan.
        pass
        
    def get_plan_str(self) -> str:
        if not self.current_plan:
            return "No plan yet."
        return "\n".join([f"{i+1}. {step}" for i, step in enumerate(self.current_plan)])
