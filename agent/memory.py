import ast
import json
import os
import time
from typing import Any, Dict, List


class Memory:
    def __init__(self, chat_id: str, workspace_dir: str):
        self.chat_id = chat_id
        self.chat_dir = workspace_dir

        if not os.path.exists(self.chat_dir):
            os.makedirs(self.chat_dir)

        self.history_file = os.path.join(self.chat_dir, "history.txt")
        self.history_jsonl_file = os.path.join(self.chat_dir, "history.jsonl")
        self.summary_file = os.path.join(self.chat_dir, "summary.txt")

        self.known_files = set()
        self.actions: List[Dict[str, Any]] = self._load_persisted_actions(limit=500)

    def _load_persisted_actions(self, limit: int = 500) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        if os.path.exists(self.history_jsonl_file):
            try:
                with open(self.history_jsonl_file, "r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            parsed = json.loads(line)
                            if isinstance(parsed, dict):
                                records.append(parsed)
                        except json.JSONDecodeError:
                            continue
            except Exception:
                records = []

        if not records and os.path.exists(self.history_file):
            records = self._load_legacy_history()

        return records[-limit:]

    def _load_legacy_history(self) -> List[Dict[str, Any]]:
        try:
            with open(self.history_file, "r", encoding="utf-8") as handle:
                content = handle.read()
        except Exception:
            return []

        records = []
        blocks = [block.strip() for block in content.split("\n---\n") if block.strip()]
        for block in blocks:
            action_obj: Any = {}
            result_text = ""
            for line in block.splitlines():
                if line.startswith("ACTION:"):
                    raw_action = line[len("ACTION:"):].strip()
                    try:
                        action_obj = ast.literal_eval(raw_action)
                    except Exception:
                        action_obj = {"raw": raw_action}
                elif line.startswith("RESULT:"):
                    result_text = line[len("RESULT:"):].strip()

            if action_obj:
                records.append(
                    {
                        "timestamp": time.time(),
                        "action": action_obj,
                        "result": result_text,
                    }
                )
        return records

    def add_action(self, action: dict, result: str):
        record = {
            "timestamp": time.time(),
            "action": action,
            "result": result,
        }
        self.actions.append(record)
        self._persist_history_text(action, result)
        self._persist_history_jsonl(record)

    def add_known_file(self, filepath: str):
        self.known_files.add(filepath)

    def _persist_history_text(self, action: dict, result: str):
        with open(self.history_file, "a", encoding="utf-8") as handle:
            handle.write(f"ACTION: {action}\nRESULT: {result}\n---\n")

    def _persist_history_jsonl(self, record: Dict[str, Any]):
        with open(self.history_jsonl_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    def get_recent_actions(self, limit: int = 5) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        return self.actions[-limit:]

    def get_action_count(self) -> int:
        return len(self.actions)

    def summarize(self, llm_query_fn):
        """
        Periodically summarize actions to avoid token limit overflow.
        """
        if len(self.actions) < 10:
            return

        summary_prompt = "Summarize the following actions and results into a simple progress report:\n"
        for action_record in self.actions:
            summary_prompt += (
                f"Action: {action_record['action']}, "
                f"Result: {str(action_record['result'])[:100]}\n"
            )

        summary = llm_query_fn(
            prompt=summary_prompt,
            system_prompt="You summarize agent progress concisely.",
            json_mode=False,
        )

        with open(self.summary_file, "w", encoding="utf-8") as handle:
            handle.write(f"SUMMARY: {summary}\n")

        self.actions = self.actions[-3:]
