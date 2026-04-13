import os
import time
import uuid

from agent.config import CHAT_SESSIONS_DIR

class Memory:
    def __init__(self, chat_id: str = None):
        if not os.path.exists(CHAT_SESSIONS_DIR):
            os.makedirs(CHAT_SESSIONS_DIR)
            
        self.chat_id = chat_id or str(uuid.uuid4())
        self.chat_dir = os.path.join(CHAT_SESSIONS_DIR, self.chat_id)
        
        if not os.path.exists(self.chat_dir):
            os.makedirs(self.chat_dir)
            
        self.history_file = os.path.join(self.chat_dir, "history.txt")
        self.summary_file = os.path.join(self.chat_dir, "summary.txt")
        
        self.actions = []
        self.known_files = set()
        
    def add_action(self, action: dict, result: str):
        record = {
            "timestamp": time.time(),
            "action": action,
            "result": result
        }
        self.actions.append(record)
        self._persist_history(f"ACTION: {action}\nRESULT: {result}\n---\n")
        
    def add_known_file(self, filepath: str):
        self.known_files.add(filepath)
        
    def _persist_history(self, text: str):
        with open(self.history_file, 'a') as f:
            f.write(text)
            
    def get_recent_actions(self, limit: int = 5) -> list:
        return self.actions[-limit:]
        
    def summarize(self, llm_query_fn):
        """
        Periodically summarize actions to avoid token limit overflow.
        """
        if len(self.actions) < 10:
            return
            
        # Condense history for next time
        summary_prompt = "Summarize the following actions and results into a simple progress report:\n"
        for a in self.actions:
            summary_prompt += f"Action: {a['action']}, Result: {a['result'][:100]}\n"
            
        summary = llm_query_fn(prompt=summary_prompt, system_prompt="You summarize agent progress concisely.", json_mode=False)
        
        with open(self.summary_file, 'w') as f:
            f.write(f"SUMMARY: {summary}\n")
            
        # Keep only the last 3 actions, but rely on summary for context
        self.actions = self.actions[-3:]
