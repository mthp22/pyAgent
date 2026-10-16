from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set


def estimate_tokens(text: str) -> int:
    """Rough estimation of token count (~4 chars per token)."""
    return max(1, len(text) // 4)


@dataclass
class ContextBudget:
    max_tokens: int = 12000
    system_ratio: float = 0.15
    project_and_plan_ratio: float = 0.25
    history_ratio: float = 0.40
    headroom_ratio: float = 0.20


class ContextManager:
    """Manages LLM context window budgeting, output compaction, and structured prompt assembly."""

    def __init__(
        self,
        max_tokens: int = 12000,
        artifacts_dir: Optional[str] = None,
        max_tool_output_chars: int = 2000,
    ):
        self.max_tokens = max_tokens
        self.artifacts_dir = artifacts_dir
        self.max_tool_output_chars = max_tool_output_chars
        self.relevant_files: Set[str] = set()

    def add_relevant_file(self, filepath: str):
        if filepath and not filepath.startswith(".") and not filepath.startswith("Error"):
            self.relevant_files.add(filepath)

    def compact_tool_result(self, tool_name: str, result_str: str, artifact_saver: Optional[Callable[[str, str], str]] = None) -> str:
        """Truncate overly large tool outputs and archive the complete text as an artifact."""
        if len(result_str) <= self.max_tool_output_chars:
            return result_str

        artifact_ref = ""
        if artifact_saver:
            artifact_name = f"{tool_name.replace('.', '_')}_output.txt"
            artifact_ref = artifact_saver(artifact_name, result_str)

        half = self.max_tool_output_chars // 2
        head = result_str[:half]
        tail = result_str[-half:]
        omitted = len(result_str) - (half * 2)

        note = f"\n... [{omitted} characters truncated"
        if artifact_ref:
            note += f"; full content saved to {artifact_ref}"
        note += "] ...\n"

        return head + note + tail

    def build_system_prompt(
        self,
        base_prompt: str,
        project_summary: str = "",
        plan_str: str = "",
        current_task: str = "",
    ) -> str:
        sections = [base_prompt.strip()]

        if project_summary:
            sections.append(f"--- PROJECT PROFILE ---\n{project_summary.strip()}")

        if self.relevant_files:
            file_list = ", ".join(sorted(list(self.relevant_files))[-15:])
            sections.append(f"--- RELEVANT FILES ---\n{file_list}")

        if plan_str:
            sections.append(f"--- LIVING PLAN ---\n{plan_str.strip()}")

        if current_task:
            sections.append(f"--- CURRENT TASK ---\n{current_task.strip()}")

        return "\n\n".join(sections)

    def compact_history(self, history_records: List[Dict[str, Any]], max_chars: int = 16000) -> List[Dict[str, Any]]:
        """Keep recent history within token bounds, dropping oldest turns if needed."""
        if not history_records:
            return []

        # Start from most recent and accumulate backwards
        accumulated: List[Dict[str, Any]] = []
        total_len = 0

        for record in reversed(history_records):
            rec_str = str(record.get("action", "")) + str(record.get("result", ""))
            if total_len + len(rec_str) > max_chars and len(accumulated) >= 2:
                break
            accumulated.append(record)
            total_len += len(rec_str)

        return list(reversed(accumulated))
