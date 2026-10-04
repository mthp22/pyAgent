import json
import os
import re
from typing import Any, List


class Planner:
    def __init__(self, llm_query_fn, workspace_dir: str):
        self.llm_query_fn = llm_query_fn
        self.workspace_dir = workspace_dir
        self.plan_file = os.path.join(self.workspace_dir, "plan.md")
        self.current_plan: List[str] = []
        self.current_plan = self._load_existing_plan()

    def _load_existing_plan(self) -> List[str]:
        if not os.path.exists(self.plan_file):
            return []

        try:
            with open(self.plan_file, "r", encoding="utf-8") as handle:
                content = handle.read()
        except Exception:
            return []

        return self._extract_plan_from_text(content)

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
            match = re.match(r"^\d+\.\s+(.*)$", line.strip())
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

    def generate_plan(self, goal: str, force_refresh: bool = False) -> List[str]:
        """
        Generate a step-by-step plan.

        Reuses existing plan unless a new explicit goal requires refresh.
        """
        if self.current_plan and not force_refresh:
            return self.current_plan

        if not goal and self.current_plan:
            return self.current_plan

        if not goal:
            self.current_plan = ["Analyze current workspace state.", "Choose next safe implementation step.", "Execute and verify."]
            self._write_plan_to_file()
            return self.current_plan

        system_prompt = (
            "You are an expert software architect planning a list of steps to achieve a goal. "
            "Return ONLY a JSON array of strings, where each string is a clear, actionable step."
        )
        prompt = f"Goal: {goal}\n\nList the steps to achieve this goal."
        response_text = self.llm_query_fn(prompt, system_prompt, json_mode=True)

        parsed_obj: Any = None
        try:
            parsed_obj = json.loads(response_text)
        except json.JSONDecodeError:
            parsed_obj = response_text

        normalized = self._normalize_plan_object(parsed_obj)
        if not normalized:
            normalized = ["Analyze the goal.", "Execute necessary commands.", "Finish."]

        self.current_plan = normalized
        self._write_plan_to_file()
        return self.current_plan

    def _write_plan_to_file(self):
        with open(self.plan_file, "w", encoding="utf-8") as handle:
            handle.write("# Plan\n\n")
            handle.write(self.get_plan_str() + "\n")

    def update_plan(self, current_state_summary: str):
        """Placeholder for plan revision."""
        _ = current_state_summary

    def get_plan_str(self) -> str:
        if not self.current_plan:
            return "No plan yet."

        formatted_plan = []
        for idx, step in enumerate(self.current_plan):
            normalized_step = step.strip()
            if not normalized_step:
                continue
            if re.match(r"^\d+\.\s+", normalized_step):
                formatted_plan.append(normalized_step)
            else:
                formatted_plan.append(f"{idx + 1}. {normalized_step}")
        return "\n".join(formatted_plan) if formatted_plan else "No plan yet."
