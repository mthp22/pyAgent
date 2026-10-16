import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    id: int
    title: str
    status: str = "pending"  # "pending", "in_progress", "completed", "failed", "blocked"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LivingPlan:
    def __init__(self, steps: Optional[List[PlanStep]] = None):
        self.steps: List[PlanStep] = steps or []

    @classmethod
    def from_string_list(cls, titles: List[str]) -> "LivingPlan":
        steps = [PlanStep(id=idx + 1, title=title.strip()) for idx, title in enumerate(titles) if title.strip()]
        if steps:
            steps[0].status = "in_progress"
        return cls(steps=steps)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LivingPlan":
        raw_steps = data.get("steps", [])
        steps = [
            PlanStep(
                id=s.get("id", idx + 1),
                title=s.get("title", ""),
                status=s.get("status", "pending"),
                notes=s.get("notes", ""),
            )
            for idx, s in enumerate(raw_steps)
        ]
        return cls(steps=steps)

    def to_dict(self) -> Dict[str, Any]:
        return {"steps": [s.to_dict() for s in self.steps]}

    def get_current_task(self) -> Optional[PlanStep]:
        for step in self.steps:
            if step.status == "in_progress":
                return step
        for step in self.steps:
            if step.status == "pending":
                step.status = "in_progress"
                return step
        return None

    def mark_current_completed(self, notes: str = "") -> None:
        curr = self.get_current_task()
        if curr:
            curr.status = "completed"
            if notes:
                curr.notes = notes
            # advance to next pending step
            for step in self.steps:
                if step.status == "pending":
                    step.status = "in_progress"
                    break

    def mark_current_failed(self, error_summary: str) -> None:
        curr = self.get_current_task()
        if curr:
            curr.status = "failed"
            curr.notes = error_summary

    def insert_diagnostic_step(self, title: str) -> None:
        curr = self.get_current_task()
        new_id = (curr.id + 1) if curr else (len(self.steps) + 1)
        # Shift subsequent step IDs
        for step in self.steps:
            if curr and step.id > curr.id:
                step.id += 1

        new_step = PlanStep(id=new_id, title=f"Fix / Diagnose: {title}", status="in_progress")
        if curr:
            curr_idx = self.steps.index(curr)
            self.steps.insert(curr_idx + 1, new_step)
        else:
            self.steps.append(new_step)

    def to_markdown(self) -> str:
        if not self.steps:
            return "No plan steps defined."
        lines = []
        status_icons = {
            "completed": "✓",
            "in_progress": "▶",
            "failed": "✗",
            "blocked": "⊘",
            "pending": "○",
        }
        for s in self.steps:
            icon = status_icons.get(s.status, "○")
            line = f"{s.id}. [{icon}] {s.title}"
            if s.notes:
                line += f" ({s.notes})"
            lines.append(line)
        return "\n".join(lines)


class Planner:
    """Dynamic Living Planner supporting step-by-step progress, plan adjustments, and replanning."""

    def __init__(self, llm_query_fn: Callable[..., str], workspace_dir: str):
        self.llm_query_fn = llm_query_fn
        self.workspace_dir = workspace_dir
        self.plan_file = os.path.join(self.workspace_dir, "plan.md")
        self.plan_json_file = os.path.join(self.workspace_dir, "plan.json")
        self.living_plan = self._load_existing_plan()
        self.current_plan: List[str] = [s.title for s in self.living_plan.steps]

    def _load_existing_plan(self) -> LivingPlan:
        # Check plan.json first
        if os.path.exists(self.plan_json_file):
            try:
                with open(self.plan_json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return LivingPlan.from_dict(data)
            except Exception as exc:
                logger.warning("Could not load plan.json (%s); trying plan.md", exc)

        # Check plan.md legacy
        if os.path.exists(self.plan_file):
            try:
                with open(self.plan_file, "r", encoding="utf-8") as f:
                    content = f.read()
                steps_str = self._extract_plan_from_text(content)
                if steps_str:
                    return LivingPlan.from_string_list(steps_str)
            except Exception as exc:
                logger.warning("Could not load plan.md: %s", exc)

        return LivingPlan()

    def _extract_plan_from_text(self, content: str) -> List[str]:
        lines = [line.rstrip() for line in content.splitlines() if line.strip()]
        body_lines = [line for line in lines if not line.strip().startswith("#")]
        if not body_lines:
            return []

        body = "\n".join(body_lines).strip()
        candidates = [body]
        if body_lines and re.match(r"^\d+\.\s*\{$", body_lines[0].strip()):
            candidates.append("{\n" + "\n".join(body_lines[1:]))

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                normalized = self._normalize_plan_object(parsed)
                if normalized:
                    return normalized
            except json.JSONDecodeError:
                continue

        numbered_steps: List[str] = []
        for line in body_lines:
            match = re.match(r"^\d+\.\s+(?:\[.*?\]\s+)?(.*)$", line.strip())
            if match:
                text = match.group(1).strip()
                if text and text not in {"{", "}", "[", "]"}:
                    numbered_steps.append(text)
        if numbered_steps:
            return numbered_steps

        fallback_steps = []
        for line in body_lines:
            cleaned = line.strip().rstrip(",")
            if cleaned in {"{", "}", "[", "]"}:
                continue
            if cleaned:
                fallback_steps.append(cleaned)
        return fallback_steps

    def _normalize_plan_object(self, plan_obj: Any) -> List[str]:
        if isinstance(plan_obj, list):
            result = []
            for item in plan_obj:
                normalized_item = self._normalize_plan_object(item)
                if normalized_item:
                    result.extend(normalized_item)
            return [step for step in result if step]

        if isinstance(plan_obj, dict):
            if "steps" in plan_obj:
                return self._normalize_plan_object(plan_obj["steps"])

            keys = list(plan_obj.keys())
            if keys and all(str(key).strip().isdigit() for key in keys):
                ordered_keys = sorted(keys, key=lambda key: int(str(key).strip()))
            else:
                ordered_keys = sorted(keys, key=lambda key: str(key))

            normalized_steps = []
            for key in ordered_keys:
                value_steps = self._normalize_plan_object(plan_obj[key])
                if value_steps:
                    normalized_steps.extend(value_steps)
            return [step for step in normalized_steps if step]

        if isinstance(plan_obj, str):
            text = plan_obj.strip()
            if not text:
                return []
            if text.startswith("[") or text.startswith("{"):
                try:
                    return self._normalize_plan_object(json.loads(text))
                except json.JSONDecodeError:
                    pass
            return [text]

        if plan_obj is None:
            return []
        return [str(plan_obj).strip()]

    def generate_plan(self, goal: str, project_summary: str = "", force_refresh: bool = False) -> List[str]:
        if self.current_plan and not force_refresh:
            return self.current_plan

        if not goal and self.current_plan:
            return self.current_plan

        if not goal:
            self.living_plan = LivingPlan.from_string_list(
                ["Analyze current workspace state.", "Choose next safe implementation step.", "Execute and verify."]
            )
            self.current_plan = [s.title for s in self.living_plan.steps]
            self._write_plan_to_file()
            return self.current_plan

        system_prompt = (
            "You are an expert software architect planning a list of steps to achieve a goal. "
            "Return ONLY a JSON array of strings, where each string is a clear, actionable step."
        )
        prompt = f"Goal: {goal}"
        if project_summary:
            prompt += f"\n\nProject Profile:\n{project_summary}"
        prompt += "\n\nList the steps to achieve this goal."

        response_text = self.llm_query_fn(prompt, system_prompt, json_mode=True)

        parsed_obj: Any = None
        try:
            parsed_obj = json.loads(response_text)
        except json.JSONDecodeError:
            parsed_obj = response_text

        normalized = self._normalize_plan_object(parsed_obj)
        if not normalized:
            normalized = ["Analyze the goal.", "Execute necessary commands.", "Finish."]

        self.living_plan = LivingPlan.from_string_list(normalized)
        self.current_plan = [s.title for s in self.living_plan.steps]
        self._write_plan_to_file()
        return self.current_plan

    def replan_on_failure(self, error_message: str, current_state: str) -> None:
        """Dynamically insert diagnostic or fix steps into the living plan."""
        curr = self.living_plan.get_current_task()
        if curr:
            curr.status = "failed"
            curr.notes = error_message[:100]

        fix_title = f"Fix error in '{curr.title if curr else 'step'}': {error_message[:60]}"
        self.living_plan.insert_diagnostic_step(fix_title)
        self.current_plan = [s.title for s in self.living_plan.steps]
        self._write_plan_to_file()

    def _write_plan_to_file(self):
        try:
            with open(self.plan_file, "w", encoding="utf-8") as handle:
                handle.write("# Plan\n\n")
                handle.write(self.living_plan.to_markdown() + "\n")
        except Exception as exc:
            logger.warning("Could not write plan.md: %s", exc)

        try:
            with open(self.plan_json_file, "w", encoding="utf-8") as handle:
                json.dump(self.living_plan.to_dict(), handle, indent=2)
        except Exception as exc:
            logger.warning("Could not write plan.json: %s", exc)

    def update_plan(self, current_state_summary: str):
        _ = current_state_summary

    def get_plan_str(self) -> str:
        return self.living_plan.to_markdown()
