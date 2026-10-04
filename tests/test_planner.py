import os
import tempfile
import unittest

from agent.planner import Planner


class PlannerNormalizationTests(unittest.TestCase):
    def test_normalizes_numbered_dict_plan_from_llm(self):
        def fake_llm(prompt, system_prompt, json_mode=True):  # noqa: ARG001
            return '{"2": "Second step", "1": "First step"}'

        with tempfile.TemporaryDirectory() as workspace:
            planner = Planner(fake_llm, workspace)
            plan = planner.generate_plan("demo goal", force_refresh=True)
            self.assertEqual(plan, ["First step", "Second step"])

    def test_loads_existing_legacy_dict_style_plan_file(self):
        with tempfile.TemporaryDirectory() as workspace:
            plan_path = os.path.join(workspace, "plan.md")
            with open(plan_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "# Plan\n\n"
                    "1. {\n"
                    '  "1": "Create folder",\n'
                    '  "2": "Install dependencies"\n'
                    "}\n"
                )

            planner = Planner(lambda *_args, **_kwargs: "[]", workspace)
            self.assertEqual(planner.current_plan, ["Create folder", "Install dependencies"])

    def test_reuses_existing_plan_without_refresh(self):
        with tempfile.TemporaryDirectory() as workspace:
            call_count = {"count": 0}

            def fake_llm(prompt, system_prompt, json_mode=True):  # noqa: ARG001
                call_count["count"] += 1
                return '["Generate new plan"]'

            planner = Planner(fake_llm, workspace)
            planner.current_plan = ["Keep existing plan"]

            plan = planner.generate_plan(goal="", force_refresh=False)
            self.assertEqual(plan, ["Keep existing plan"])
            self.assertEqual(call_count["count"], 0)


if __name__ == "__main__":
    unittest.main()
