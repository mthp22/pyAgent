import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """Manages structured, append-only, deterministic session persistence."""

    def __init__(self, session_id: str, base_dir: str):
        self.session_id = session_id
        self.session_dir = os.path.abspath(base_dir)
        self.artifacts_dir = os.path.join(self.session_dir, "artifacts")

        os.makedirs(self.session_dir, exist_ok=True)
        os.makedirs(self.artifacts_dir, exist_ok=True)

        self.session_file = os.path.join(self.session_dir, "session.json")
        self.plan_file = os.path.join(self.session_dir, "plan.json")
        self.history_jsonl_file = os.path.join(self.session_dir, "history.jsonl")
        self.current_md_file = os.path.join(self.session_dir, "current.md")
        self.next_md_file = os.path.join(self.session_dir, "next.md")
        self.summary_md_file = os.path.join(self.session_dir, "summary.md")

    def _write_atomic(self, filepath: str, content: str) -> None:
        tmp_path = f"{filepath}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, filepath)

    def append_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        event = {
            "type": event_type,
            "timestamp": now_iso(),
            **data,
        }
        with open(self.history_jsonl_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def load_events(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.history_jsonl_file):
            return []
        events = []
        try:
            with open(self.history_jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except Exception:
                            pass
        except Exception:
            return []
        return events

    def save_session_meta(self, meta: Dict[str, Any]) -> None:
        meta["updated_at"] = now_iso()
        self._write_atomic(self.session_file, json.dumps(meta, indent=2, ensure_ascii=False))

    def load_session_meta(self) -> Dict[str, Any]:
        if not os.path.exists(self.session_file):
            return {}
        try:
            with open(self.session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Could not read session metadata from %s: %s", self.session_file, exc)
            return {}

    def save_plan(self, plan_data: Dict[str, Any]) -> None:
        plan_data["updated_at"] = now_iso()
        self._write_atomic(self.plan_file, json.dumps(plan_data, indent=2, ensure_ascii=False))

    def load_plan(self) -> Dict[str, Any]:
        if not os.path.exists(self.plan_file):
            return {}
        try:
            with open(self.plan_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Could not read plan from %s: %s", self.plan_file, exc)
            return {}

    def save_markdown_snapshots(self, current_md: str, next_md: str, summary_md: Optional[str] = None) -> None:
        self._write_atomic(self.current_md_file, current_md)
        self._write_atomic(self.next_md_file, next_md)
        if summary_md is not None:
            self._write_atomic(self.summary_md_file, summary_md)

    def save_artifact(self, filename: str, content: str) -> str:
        safe_name = os.path.basename(filename)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target_name = f"{timestamp}_{safe_name}"
        target_path = os.path.join(self.artifacts_dir, target_name)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        return os.path.join("artifacts", target_name)
