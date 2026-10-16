import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.config import SESSION_METADATA_FILE, load_config
from agent.context.manager import ContextManager
from agent.llm import get_llm_provider, query_llm
from agent.llm.base import LLMMessage
from agent.mcp.client import MCPClientManager
from agent.mcp.registry import ToolRegistry
from agent.memory import Memory
from agent.planner import Planner
from agent.repo.profiler import RepoProfiler
from agent.safety.policy import SafetyPolicy
from agent.session.store import SessionStore
from agent.tools import edit_file, read_file, run_command, write_file
from agent.validation.engine import ValidationEngine, ValidationResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an autonomous AI coding agent.
You must EXACTLY output valid JSON matching this schema:
{
    "action": "read_file" | "write_file" | "edit_file" | "run_command" | "finish" | "filesystem.read_file" | "filesystem.write_file" | "filesystem.edit_file" | "git.status" | "git.diff" | "terminal.run_command",
    "path": "string (optional)",
    "content": "string (optional)",
    "command": "string (optional)",
    "cwd": "string (optional, only for run_command)",
    "timeout_secs": "integer (optional, only for run_command)",
    "summary": "string (only for finish)"
}
Do not output ANY other text. Just the JSON object.

Allowed Actions:
- read_file or filesystem.read_file: Provide 'path'
- write_file or filesystem.write_file: Provide 'path' and 'content'
- edit_file or filesystem.edit_file: Provide 'path' and 'content' (use REPLACE: <old> WITH: <new> format)
- run_command or terminal.run_command: Provide 'command', optional 'cwd', optional 'timeout_secs'
- git.status: Get git status
- git.diff: Inspect git diff
- finish: Provide 'summary'
"""


class Agent:
    def __init__(
        self,
        goal: str,
        chat_id: str,
        workspace_dir: str,
        explicit_goal: bool = False,
        llm_provider: Optional[Any] = None,
    ):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.config = load_config(workspace_dir=self.workspace_dir)
        self.max_iterations = self.config.agent.max_iterations
        self.explicit_goal = explicit_goal
        self.llm_provider = llm_provider or get_llm_provider()

        self.session_file = os.path.join(self.workspace_dir, SESSION_METADATA_FILE)
        self.session_meta = self._load_or_initialize_session_metadata(goal, chat_id)

        resolved_goal = goal if goal else self.session_meta.get("goal", "")
        self.goal = resolved_goal.strip() if isinstance(resolved_goal, str) else ""
        if self.goal != self.session_meta.get("goal", ""):
            self._update_session_metadata(goal=self.goal)

        # Core subsystems
        self.session_store = SessionStore(session_id=chat_id, base_dir=self.workspace_dir)
        self.context_manager = ContextManager(
            max_tokens=self.config.context.max_tokens,
            artifacts_dir=self.session_store.artifacts_dir,
        )
        self.repo_profiler = RepoProfiler(workspace_dir=self.workspace_dir)
        self.profile = self.repo_profiler.profile()

        self.safety_policy = SafetyPolicy(
            mode=self.config.agent.approval_mode,
            workspace_dir=self.workspace_dir,
            allow_network=self.config.safety.allow_network,
            allow_package_install=self.config.safety.allow_package_install,
            allow_git_push=self.config.safety.allow_git_push,
        )

        # MCP Layer
        self.mcp_manager = MCPClientManager(
            workspace_dir=self.workspace_dir,
            allowed_commands=self.config.safety.allowed_commands,
            dangerous_flags=self.config.safety.dangerous_flags,
        )
        mcp_cfg_path = os.path.join(self.workspace_dir, self.config.mcp.config)
        if os.path.exists(mcp_cfg_path):
            try:
                self.mcp_manager.load_and_start(self.config.mcp.config)
            except Exception as exc:
                logger.warning("Failed to start MCP servers from %s: %s", mcp_cfg_path, exc)
        else:
            logger.info("No MCP configuration found at %s; running with built-in tools only.", mcp_cfg_path)
        self.tool_registry = ToolRegistry(client_manager=self.mcp_manager)
        self.tool_registry.discover_tools()

        # Validation Engine
        self.validation_engine = ValidationEngine(
            workspace_dir=self.workspace_dir,
            profile=self.profile,
            tool_executor=self._execute_tool_via_registry_or_fallback,
        )

        self.memory = Memory(chat_id=chat_id, workspace_dir=self.workspace_dir)
        self.planner = Planner(query_llm, workspace_dir=self.workspace_dir)
        self.files_modified: List[str] = []

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
        exit_code_match = re.search(r"\[Exit code (\d+)\]", cleaned)
        if exit_code_match and int(exit_code_match.group(1)) != 0:
            return False
        return True

    def _advance_plan_cursor(self, total_steps: int):
        if total_steps <= 0:
            return
        current_cursor = int(self.session_meta.get("plan_cursor", 0) or 0)
        if current_cursor < total_steps:
            self._update_session_metadata(plan_cursor=current_cursor + 1)
        self.planner.living_plan.mark_current_completed()

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
        plan = self.planner.generate_plan(
            self.goal,
            project_summary=self.profile.to_prompt_summary(),
            force_refresh=self.explicit_goal,
        )
        print("Plan:")
        print(self.planner.get_plan_str())
        print("-" * 40)

        if int(self.session_meta.get("plan_cursor", 0) or 0) > len(plan):
            self._update_session_metadata(plan_cursor=len(plan))

        finished = False
        try:
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

                    # Functional validation check before declaring completion
                    val_cmd = self.validation_engine.get_default_validation_cmd()
                    val_results: List[ValidationResult] = []
                    if val_cmd:
                        print(f"Running validation check: {val_cmd}...")
                        v_res = self.validation_engine.run_validation(val_cmd)
                        val_results.append(v_res)
                        if not v_res.passed and iteration_idx < (self.max_iterations - 2):
                            print(f"Validation failed: {v_res.diagnostics}. Entering autonomous debugging...")
                            self.planner.replan_on_failure(v_res.diagnostics, v_res.output)
                            self.memory.add_action(
                                {"action": "validation_failure"},
                                f"Tests failed: {v_res.diagnostics}\n{v_res.output[:500]}",
                            )
                            continue

                    # Final verification report
                    report = self.validation_engine.generate_completion_report(
                        summary=summary,
                        files_changed=self.files_modified,
                        validation_results=val_results,
                    )
                    print(f"\n{report}")

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
                if successful and action_type in {
                    "write_file",
                    "edit_file",
                    "run_command",
                    "filesystem.write_file",
                    "filesystem.edit_file",
                    "terminal.run_command",
                }:
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
        finally:
            self.mcp_manager.shutdown()

    def _get_file_content(self, filename: str) -> str:
        filepath = os.path.join(self.workspace_dir, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as handle:
                    return handle.read()
            except Exception as exc:
                logger.debug("Could not read %s: %s", filepath, exc)
                return ""
        return ""

    def _decide_next_action(self) -> Optional[dict]:
        prompt = f"Goal: {self.goal}\n\n"
        prompt += f"Session Status: {self.session_meta.get('status', 'unknown')}\n"
        prompt += f"Current Plan:\n{self.planner.get_plan_str()}\n\n"

        current_task = self.planner.living_plan.get_current_task()
        if current_task:
            prompt += f"Active Task Step: {current_task.title}\n\n"

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

        prompt += "\nWhat is the next action to take? Call a tool, or return a JSON action."

        system_with_context = self.context_manager.build_system_prompt(
            base_prompt=self._system_prompt_with_tools(),
            project_summary=self.profile.to_prompt_summary(),
            plan_str=self.planner.get_plan_str(),
            current_task=current_task.title if current_task else "",
        )

        # Preferred path: native tool calling with the live MCP tool catalog.
        tool_defs = self.tool_registry.get_tool_definitions()
        if tool_defs:
            action = self._decide_action_via_tool_calling(prompt, system_with_context, tool_defs)
            if action is not None:
                return action

        # Fallback path: single-turn JSON action (used before MCP tools load, or if
        # the model/provider cannot produce a tool call).
        response_text = query_llm(prompt, system_with_context, temperature=0.1, json_mode=True)
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            logger.error("LLM did not return valid JSON. Raw response: %s", self._truncate(response_text, 500))
            return None
        if not isinstance(parsed, dict) or not parsed.get("action"):
            logger.error("LLM action was not a valid JSON action object: %s", self._truncate(str(parsed), 200))
            return None
        return parsed

    def _system_prompt_with_tools(self) -> str:
        tool_names = sorted(self.tool_registry.tools.keys())
        if not tool_names:
            return SYSTEM_PROMPT
        listing = "\n".join(f"- {name}" for name in tool_names)
        return SYSTEM_PROMPT + f"\n\nAvailable MCP tools (prefer calling these):\n{listing}\n"

    def _decide_action_via_tool_calling(
        self,
        prompt: str,
        system_prompt: str,
        tool_defs: List[Any],
    ) -> Optional[Dict[str, Any]]:
        try:
            response = self.llm_provider.chat(
                messages=[
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=prompt),
                ],
                tools=tool_defs,
                temperature=0.1,
            )
        except Exception as exc:
            logger.warning("Tool-calling decision failed, falling back to JSON actions: %s", exc)
            return None

        if response is not None and response.tool_calls:
            call = response.tool_calls[0]
            args = call.arguments if isinstance(call.arguments, dict) else {}
            action = {"action": call.name}
            action.update(args)
            return action

        # Some models return the JSON action in the message content even when
        # tools were supplied; accept it.
        content = (response.content or "").strip() if response is not None else ""
        if content:
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and parsed.get("action"):
                    return parsed
            except json.JSONDecodeError:
                pass
        return None

    def _execute_tool_via_registry_or_fallback(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        # Check MCP Tool Registry first
        if self.tool_registry.get_tool(tool_name):
            return self.tool_registry.execute(tool_name, arguments)

        # Fallback to local built-in tool implementations
        raw_tool = tool_name.split(".")[-1]
        if raw_tool == "read_file":
            return read_file(arguments.get("path", ""), self.workspace_dir)
        elif raw_tool == "write_file":
            return write_file(arguments.get("path", ""), arguments.get("content", ""), self.workspace_dir)
        elif raw_tool == "edit_file":
            return edit_file(arguments.get("path", ""), arguments.get("content", ""), self.workspace_dir)
        elif raw_tool == "run_command":
            return run_command(
                arguments.get("command", ""),
                self.workspace_dir,
                cwd=arguments.get("cwd"),
                timeout_secs=arguments.get("timeout_secs"),
                allowed_commands=self.config.safety.allowed_commands,
                dangerous_flags=self.config.safety.dangerous_flags,
            )
        return f"Error: Tool '{tool_name}' not recognized."

    def _execute_action(self, action_obj: dict) -> str:
        action = action_obj.get("action", "")

        # Safety policy check
        allowed, reason = self.safety_policy.check_permission(action, action_obj)
        if not allowed:
            return f"Error: Safety policy rejected action '{action}': {reason}"

        # Track modified files and relevant files
        path_arg = action_obj.get("path")
        if path_arg:
            self.context_manager.add_relevant_file(path_arg)
            if any(k in action for k in ("write", "edit")):
                self.files_modified.append(path_arg)

        # Execute
        raw_result = self._execute_tool_via_registry_or_fallback(action, action_obj)

        # Compact large output and persist full result to artifacts
        compacted = self.context_manager.compact_tool_result(
            tool_name=action,
            result_str=raw_result,
            artifact_saver=self.session_store.save_artifact,
        )

        # Record in structured event log
        self.session_store.append_event(
            event_type="tool_execution",
            data={"action": action_obj, "result": compacted[:1000]},
        )

        return compacted

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
                except Exception as exc:
                    logger.warning("LLM state enrichment failed; using deterministic state only: %s", exc)

            self._write_atomic(os.path.join(self.workspace_dir, "current.md"), current_content)
            self._write_atomic(os.path.join(self.workspace_dir, "next.md"), next_content)
            self.session_store.save_markdown_snapshots(
                current_md=current_content,
                next_md=next_content,
            )
            print("Session state saved successfully.")
        except Exception as exc:
            logger.exception("Failed to save session state")
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
