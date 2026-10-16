import unittest

from agent.validation.engine import ValidationEngine, ValidationResult


class TestValidationEngine(unittest.TestCase):
    def test_classify_failure_patterns(self):
        engine = ValidationEngine(workspace_dir=".")

        # Missing dependency
        cls1, diag1 = engine.classify_failure("ModuleNotFoundError: No module named 'fastapi'")
        self.assertEqual(cls1, "missing_dependency")
        self.assertIn("fastapi", diag1)

        # Syntax error
        cls2, diag2 = engine.classify_failure("SyntaxError: invalid syntax in main.py line 4")
        self.assertEqual(cls2, "own_changes")

        # Assertion error
        cls3, diag3 = engine.classify_failure("FAILED (failures=2) AssertionError: False is not True")
        self.assertEqual(cls3, "own_changes")

        # Permission error
        cls4, diag4 = engine.classify_failure("Permission denied: /var/run/test")
        self.assertEqual(cls4, "environment_issue")

    def test_run_validation_mock_executor(self):
        def fake_executor(tool_name, args):
            if "fail" in args.get("command", ""):
                return "[Exit code 1]\nAssertionError: expected 5 got 4"
            return "Ran 10 tests\nOK"

        engine = ValidationEngine(workspace_dir=".", tool_executor=fake_executor)

        # Pass
        res_pass = engine.run_validation("pytest tests/")
        self.assertTrue(res_pass.passed)
        self.assertIn("Validation passed", res_pass.summary_line())

        # Fail
        res_fail = engine.run_validation("pytest fail/")
        self.assertFalse(res_fail.passed)
        self.assertEqual(res_fail.failure_classification, "own_changes")

    def test_completion_report_generation(self):
        engine = ValidationEngine(workspace_dir=".")
        vr = ValidationResult(passed=True, command="pytest", output="OK", exit_code=0)
        report = engine.generate_completion_report(
            summary="Refactored database module",
            files_changed=["src/db.py", "tests/test_db.py"],
            validation_results=[vr],
        )
        self.assertIn("Task completed.", report)
        self.assertIn("Refactored database module", report)
        self.assertIn("Validation passed", report)
        self.assertIn("src/db.py", report)


if __name__ == "__main__":
    unittest.main()
