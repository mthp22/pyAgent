import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.config import SESSION_METADATA_FILE
from agent.llm import query_llm
from agent.memory import Memory
from agent.planner import Planner
from agent.tools import edit_file, read_file, run_command, write_file

SYSTEM_PROMPT = """You are an autonomous AI coding agent.
You must EXACTLY output valid JSON matching this schema:
{
    "action": "read_file" | "write_file" | "edit_file" | "run_command" | "finish",
    "path": "string (optional)",
    "content": "string (optional)",
    "command": "string (optional)",
    "cwd": "string (optional, only for run_command)",
    "timeout_secs": "integer (optional, only for run_command)",
    "summary": "string (only for finish)"
}
Do not output ANY other text. Just the JSON object.

Allowed Actions:
- read_file: Provide 'path'
- write_file: Provide 'path' and 'content'
- edit_file: Provide 'path' and 'content' (use REPLACE: <old> WITH: <new> format)
- run_command: Provide 'command', optional 'cwd', optional 'timeout_secs'
- finish: Provide 'summary'
"""


class Agent:
    def __init__(self, goal: str, chat_id: str, workspace_dir: str, explicit_goal: bool = False):
        self.workspace_dir = workspace_dir
        self.max_iterations = 40
        self.explicit_goal = explicit_goal

        self.session_file = os.path.join(self.workspace_dir, SESSION_METADATA_FILE)
        self.session_meta = self._load_or_initialize_session_metadata(goal, chat_id)

        resolved_goal = goal if goal else self.session_meta.get("goal", "")
        self.goal = resolved_goal.strip() if isinstance(resolved_goal, str) else ""
        if self.goal != self.session_meta.get("goal", ""):
            self._update_session_metadata(goal=self.goal)

        self.memory = Memory(chat_id=chat_id, workspace_dir=workspace_dir)
        self.planner = Planner(query_llm, workspace_dir=workspace_dir)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _write_atomic(self, filepath: str, content: str):
        tmp_path = f"{filepath}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, filepath)

    def _default_session_meta(self, goal: Optional[str], chat_id: str) -> Dict[str, Any]:
        now = self._now_iso()
        return {
            "chat_id": chat_id,
            "goal": (goal or "").strip(),
            "status": "created",
            "created_at": now,
            "updated_at": now,
            "last_run_started_at": None,
            "last_run_finished_at": None,
            "last_iteration": 0,
            "max_iterations": self.max_iterations,
            "last_error": None,
            "plan_cursor": 0,
            "run_count": 0,
            "last_action": None,
            "last_action_result": None,
        }

    def _load_or_initialize_session_metadata(self, goal: Optional[str], chat_id: str) -> Dict[str, Any]:
        default_meta = self._default_session_meta(goal=goal, chat_id=chat_id)
        loaded_meta: Dict[str, Any] = {}

        if os.path.exists(self.session_file):
            try:
                with open(self.session_file, "r", encoding="utf-8") as handle:
                    parsed = json.load(handle)
                if isinstance(parsed, dict):
                    loaded_meta = parsed
            except Exception:
                loaded_meta = {}

        merged = {**default_meta, **loaded_meta}
        if goal:
            merged["goal"] = goal.strip()
        merged["updated_at"] = self._now_iso()
        self._write_atomic(self.session_file, json.dumps(merged, indent=2))
        return merged

    def _update_session_metadata(self, **updates):
        self.session_meta.update(updates)
        self.session_meta["updated_at"] = self._now_iso()
        self.session_meta["max_iterations"] = self.max_iterations
        self._write_atomic(self.session_file, json.dumps(self.session_meta, indent=2))

    def _truncate(self, text: Any, limit: int = 500) -> str:
        as_text = str(text).strip()
        if len(as_text) <= limit:
            return as_text
        return as_text[:limit] + "..."

    def _is_successful_result(self, result: str) -> bool:
        cleaned = str(result).strip()
        if not cleaned:
            return True
        if cleaned.startswith("Error:"):
            return False
        if "Traceback (most recent call last)" in cleaned:
            return False
        return True

    def _advance_plan_cursor(self, total_steps: int):
        if total_steps <= 0:
            return
        current_cursor = int(self.session_meta.get("plan_cursor", 0) or 0)
        if current_cursor < total_steps:
            self._update_session_metadata(plan_cursor=current_cursor + 1)

    def run(self):
        print(f"Goal: {self.goal}")
        print(f"Chat Session ID: {self.memory.chat_id}")
        print(f"Workspace Directory: {self.workspace_dir}")

        run_count = int(self.session_meta.get("run_count", 0) or 0) + 1
        self._update_session_metadata(
            status="running",
            last_error=None,
            last_run_started_at=self._now_iso(),
            run_count=run_count,
        )

        print("Generating plan...")
        plan = self.planner.generate_plan(self.goal, force_refresh=self.explicit_goal)
        print("Plan:")
        print(self.planner.get_plan_str())
        print("-" * 40)

        if int(self.session_meta.get("plan_cursor", 0) or 0) > len(plan):
            self._update_session_metadata(plan_cursor=len(plan))

        finished = False
        for iteration_idx in range(self.max_iterations):
            print(f"\n--- Iteration {iteration_idx + 1} ---")
            action_obj = self._decide_next_action()
            if not action_obj:
                print("Failed to decide next action.")
                self._update_session_metadata(
                    status="blocked",
                    last_iteration=iteration_idx + 1,
                    last_error="Failed to decide next action.",
                )
                self.save_state(reason="decision-failure", enrich_with_llm=False)
                break

            action_type = action_obj.get("action", "unknown")
            print(f"Action: {action_type}")

            if action_type == "finish":
                summary = action_obj.get("summary", "Task complete.")
                print(f"Summary: {summary}")
                self.memory.add_action(action_obj, "Finished.")
                self._update_session_metadata(
                    status="completed",
                    last_iteration=iteration_idx + 1,
                    last_error=None,
                    plan_cursor=len(plan),
                    last_action="finish",
                    last_action_result=self._truncate(summary, limit=300),
                )
                self.save_state(reason="finished", enrich_with_llm=False)
                finished = True
                break

            result = self._execute_action(action_obj)
            print(f"Result:\n{result}")

            result_text = str(result).strip()
            self.memory.add_action(action_obj, result_text[:2000])

            successful = self._is_successful_result(result_text)
            if successful and action_type in {"write_file", "edit_file", "run_command"}:
                self._advance_plan_cursor(total_steps=len(plan))

            self._update_session_metadata(
                last_iteration=iteration_idx + 1,
                status="running",
                last_error=None if successful else self._truncate(result_text, limit=500),
                last_action=action_type,
                last_action_result=self._truncate(result_text, limit=300),
            )

            self.save_state(reason=f"iteration-{iteration_idx + 1}", enrich_with_llm=False)

        if not finished:
            final_status = self.session_meta.get("status", "running")
            if final_status == "running":
                final_status = "paused"
            self._update_session_metadata(
                status=final_status,
                last_run_finished_at=self._now_iso(),
            )
        else:
            self._update_session_metadata(last_run_finished_at=self._now_iso())

        print("\nAgent finished execution.")

    def _get_file_content(self, filename: str) -> str:
        filepath = os.path.join(self.workspace_dir, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as handle:
                    return handle.read()
            except Exception:
                return ""
        return ""

    def _decide_next_action(self) -> dict:
        prompt = f"Goal: {self.goal}\n\n"
        prompt += f"Session Status: {self.session_meta.get('status', 'unknown')}\n"
        prompt += f"Current Plan:\n{self.planner.get_plan_str()}\n\n"

        current_state = self._get_file_content("current.md")
        if current_state.strip() and current_state.strip() != "# Current":
            prompt += f"Current State from previous session:\n{current_state}\n\n"

        next_steps = self._get_file_content("next.md")
        if next_steps.strip() and next_steps.strip() != "# Next":
            prompt += f"Proposed Next Steps from previous session:\n{next_steps}\n\n"

        prompt += "Recent Actions (persisted across sessions):\n"
        recent = self.memory.get_recent_actions(6)
        if not recent:
            prompt += "None.\n"
        else:
            for record in recent:
                action = record.get("action", {})
                result = record.get("result", "")
                prompt += f"- Action: {action}\n  Result: {self._truncate(result, limit=350)}\n"

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
            if not path:
                return "Error: Missing 'path'"
            self.memory.add_known_file(path)
            return read_file(path, self.workspace_dir)

        if action == "write_file":
            path = action_obj.get("path")
            content = action_obj.get("content")
            if path is None or content is None:
                return "Error: Missing 'path' or 'content'"
            self.memory.add_known_file(path)
            return write_file(path, content, self.workspace_dir)

        if action == "edit_file":
            path = action_obj.get("path")
            content = action_obj.get("content")
            if path is None or content is None:
                return "Error: Missing 'path' or 'content' (for patch)"
            self.memory.add_known_file(path)
            return edit_file(path, content, self.workspace_dir)

        if action == "run_command":
            command = action_obj.get("command")
            cwd = action_obj.get("cwd")
            timeout_secs = action_obj.get("timeout_secs")
            if not command:
                return "Error: Missing 'command'"
            return run_command(command, self.workspace_dir, cwd=cwd, timeout_secs=timeout_secs)

        return f"Error: Unknown action '{action}'"

    def _deterministic_state(self, reason: str) -> Dict[str, str]:
        plan_steps = self.planner.current_plan
        total_steps = len(plan_steps)
        plan_cursor = int(self.session_meta.get("plan_cursor", 0) or 0)
        if total_steps == 0:
            plan_cursor = 0
        else:
            plan_cursor = max(0, min(plan_cursor, total_steps))

        completed_steps = plan_steps[:plan_cursor]
        pending_steps = plan_steps[plan_cursor:]

        recent = self.memory.get_recent_actions(10)
        action_count = self.memory.get_action_count()
        recent_lines = []
        for record in recent[-5:]:
            action = record.get("action", {})
            action_name = action.get("action", "unknown") if isinstance(action, dict) else "unknown"
            result = record.get("result", "")
            status = "ok" if self._is_successful_result(str(result)) else "error"
            recent_lines.append(f"- {action_name} ({status}): {self._truncate(result, limit=180)}")

        current_lines = [
            "# Current",
            "",
            f"Goal: {self.goal or '(not set)'}",
            f"Session status: {self.session_meta.get('status', 'unknown')}",
            f"State reason: {reason}",
            f"Last updated (UTC): {self._now_iso()}",
            f"Plan progress (heuristic): {plan_cursor}/{total_steps} steps",
            f"Total recorded actions: {action_count}",
            f"Last iteration: {self.session_meta.get('last_iteration', 0)}",
        ]

        if recent_lines:
            current_lines.append("")
            current_lines.append("Recent actions:")
            current_lines.extend(recent_lines)

        last_error = self.session_meta.get("last_error")
        if last_error:
            current_lines.append("")
            current_lines.append(f"Last error: {last_error}")

        next_lines = ["# Next", ""]
        status = self.session_meta.get("status")
        if status == "completed":
            next_lines.append("1. Confirm outputs and archive or start a new goal.")
            next_lines.append("2. If needed, run final validation commands.")
        else:
            idx = 1
            if last_error:
                next_lines.append(f"{idx}. Resolve the last error before proceeding: {self._truncate(last_error, 220)}")
                idx += 1
            if pending_steps:
                next_lines.append(f"{idx}. Continue with plan step {plan_cursor + 1}: {pending_steps[0]}")
                idx += 1
                for extra_step in pending_steps[1:3]:
                    next_lines.append(f"{idx}. Then continue with: {extra_step}")
                    idx += 1
            else:
                next_lines.append(f"{idx}. Re-evaluate remaining work and validate completion.")
                idx += 1
            next_lines.append(f"{idx}. Execute focused verification commands in the correct working directory.")

        if completed_steps:
            next_lines.append("")
            next_lines.append("Completed plan steps (heuristic):")
            for step in completed_steps[-3:]:
                next_lines.append(f"- {step}")

        return {
            "current": "\n".join(current_lines).rstrip() + "\n",
            "next": "\n".join(next_lines).rstrip() + "\n",
        }

    def _llm_enrichment(self, current_text: str, next_text: str) -> Dict[str, Optional[str]]:
        prompt = (
            "You are helping refine deterministic execution state for a coding agent.\n"
            "Return concise additions only.\n"
            "Format exactly:\n"
            "CURRENT_ADD:\n"
            "<extra notes>\n"
            "NEXT_ADD:\n"
            "<extra next-step notes>\n\n"
            f"{current_text}\n\n{next_text}\n"
        )
        response = query_llm(
            prompt,
            "You improve state files without changing facts. Keep it concise.",
            temperature=0.1,
            json_mode=False,
        )

        if "NEXT_ADD:" not in response:
            return {"current_add": None, "next_add": None}

        parts = response.split("NEXT_ADD:", 1)
        current_add = parts[0].replace("CURRENT_ADD:", "").strip()
        next_add = parts[1].strip()
        return {
            "current_add": current_add or None,
            "next_add": next_add or None,
        }

    def save_state(self, reason: str = "manual", enrich_with_llm: bool = False):
        """Save deterministic current.md and next.md, optionally enriched by LLM."""
        print("\nSaving session state to current.md and next.md...")
        try:
            state = self._deterministic_state(reason=reason)
            current_content = state["current"]
            next_content = state["next"]

            if enrich_with_llm:
                try:
                    additions = self._llm_enrichment(current_content, next_content)
                    if additions.get("current_add"):
                        current_content += "\n## LLM Notes\n" + additions["current_add"].strip() + "\n"
                    if additions.get("next_add"):
                        next_content += "\n## LLM Notes\n" + additions["next_add"].strip() + "\n"
                except Exception:
                    # Keep deterministic files as source-of-truth even if LLM enrichment fails.
                    pass

            self._write_atomic(os.path.join(self.workspace_dir, "current.md"), current_content)
            self._write_atomic(os.path.join(self.workspace_dir, "next.md"), next_content)
            print("Session state saved successfully.")
        except Exception as exc:
            print(f"Failed to save state: {exc}")

    def mark_interrupted(self):
        self._update_session_metadata(
            status="interrupted",
            last_error="Interrupted by user.",
            last_run_finished_at=self._now_iso(),
        )

    def mark_failed(self, error_message: str):
        self._update_session_metadata(
            status="failed",
            last_error=self._truncate(error_message, limit=800),
            last_run_finished_at=self._now_iso(),
        )
