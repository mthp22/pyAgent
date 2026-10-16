import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from agent.repo.profiler import ProjectProfile


@dataclass
class ValidationResult:
    passed: bool
    command: str
    output: str
    exit_code: int
    failure_classification: Optional[str] = None  # "own_changes", "missing_dependency", "environment_issue", "pre_existing", "unknown"
    diagnostics: str = ""

    def summary_line(self) -> str:
        if self.passed:
            return f"✓ Validation passed ('{self.command}')"
        else:
            return f"✗ Validation failed ('{self.command}'): [{self.failure_classification}] {self.diagnostics}"


class ValidationEngine:
    """Orchestrates tests, linters, and runtime validation before reporting completion."""

    def __init__(
        self,
        workspace_dir: str,
        profile: Optional[ProjectProfile] = None,
        tool_executor: Optional[Callable[[str, Dict[str, Any]], str]] = None,
    ):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.profile = profile
        self.tool_executor = tool_executor

    def get_default_validation_cmd(self) -> Optional[str]:
        if self.profile and self.profile.recommended_test_cmd:
            return self.profile.recommended_test_cmd
        # Fallbacks based on files
        if os.path.exists(os.path.join(self.workspace_dir, "pytest.ini")) or os.path.exists(
            os.path.join(self.workspace_dir, "tests")
        ):
            return "python3 -m unittest discover tests"
        return None

    def classify_failure(self, output: str) -> tuple[str, str]:
        lower = output.lower()

        # Missing dependency detection
        dep_patterns = [
            r"modulenotfounderror: no module named ['\"]([^'\"]+)['\"]",
            r"importerror: cannot import name ['\"]([^'\"]+)['\"]",
            r"cannot find module ['\"]([^'\"]+)['\"]",
            r"command not found: ([^\s]+)",
        ]
        for pat in dep_patterns:
            m = re.search(pat, output, re.IGNORECASE)
            if m:
                missing = m.group(1)
                return "missing_dependency", f"Missing dependency or package '{missing}'"

        # Syntax / Compilation errors in changes
        if "syntaxerror" in lower or "indentationerror" in lower:
            return "own_changes", "Syntax or indentation error in modified source code"

        # Test assertion failures
        if "assertionerror" in lower or "failed (failures=" in lower or "fail:" in lower or "assert " in lower:
            return "own_changes", "Assertion failure or failed test case"

        # Permission / environment
        if "permission denied" in lower or "eacces" in lower:
            return "environment_issue", "Permission denied in execution environment"

        return "unknown", "Unclassified execution error or test failure"

    def run_validation(self, custom_command: Optional[str] = None) -> ValidationResult:
        cmd = custom_command or self.get_default_validation_cmd()
        if not cmd:
            return ValidationResult(
                passed=False,
                command="none",
                output="No validation command configured or discovered.",
                exit_code=-1,
                failure_classification="environment_issue",
                diagnostics="No test runner detected in the workspace.",
            )

        # Run command via tool executor if available, or direct subprocess
        if self.tool_executor:
            raw_res = self.tool_executor("terminal.run_command", {"command": cmd, "timeout_secs": 60})
            exit_code = 0
            if "[Exit code" in raw_res:
                match = re.search(r"\[Exit code (\d+)\]", raw_res)
                if match:
                    exit_code = int(match.group(1))
            passed = (exit_code == 0) and not raw_res.startswith("Error:")

            diag = ""
            classification = None
            if not passed:
                classification, diag = self.classify_failure(raw_res)

            return ValidationResult(
                passed=passed,
                command=cmd,
                output=raw_res,
                exit_code=exit_code,
                failure_classification=classification,
                diagnostics=diag,
            )

        try:
            res = subprocess.run(
                cmd,
                cwd=self.workspace_dir,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            comb = res.stdout + ("\n" + res.stderr if res.stderr else "")
            passed = res.returncode == 0
            classification = None
            diag = ""
            if not passed:
                classification, diag = self.classify_failure(comb)

            return ValidationResult(
                passed=passed,
                command=cmd,
                output=comb.strip(),
                exit_code=res.returncode,
                failure_classification=classification,
                diagnostics=diag,
            )
        except subprocess.TimeoutExpired:
            return ValidationResult(
                passed=False,
                command=cmd,
                output="Validation command timed out after 60 seconds.",
                exit_code=124,
                failure_classification="environment_issue",
                diagnostics="Timeout executing test command.",
            )
        except Exception as e:
            return ValidationResult(
                passed=False,
                command=cmd,
                output=str(e),
                exit_code=1,
                failure_classification="environment_issue",
                diagnostics=f"Exception running validation: {e}",
            )

    def generate_completion_report(
        self,
        summary: str,
        files_changed: List[str],
        validation_results: List[ValidationResult],
        caveats: Optional[List[str]] = None,
    ) -> str:
        report_lines = [
            "Task completed.",
            "",
            "Implemented:",
            f"- {summary.strip()}",
            "",
            "Validation:",
        ]

        if validation_results:
            for vr in validation_results:
                report_lines.append(f"  {vr.summary_line()}")
        else:
            report_lines.append("  ⚠ No automated tests could be discovered or executed.")

        if files_changed:
            report_lines.append("")
            report_lines.append("Files changed:")
            for f in sorted(set(files_changed)):
                report_lines.append(f"- {f}")

        if caveats:
            report_lines.append("")
            report_lines.append("Caveats & Limitations:")
            for c in caveats:
                report_lines.append(f"⚠ {c}")
        else:
            report_lines.append("")
            report_lines.append("No known issues remain.")

        return "\n".join(report_lines)
