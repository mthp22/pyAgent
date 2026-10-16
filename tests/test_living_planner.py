import unittest

from agent.planner import LivingPlan


class TestLivingPlanner(unittest.TestCase):
    def test_living_plan_transitions(self):
        plan = LivingPlan.from_string_list(["Inspect repo", "Write tests", "Implement feature"])
        self.assertEqual(len(plan.steps), 3)

        curr = plan.get_current_task()
        self.assertIsNotNone(curr)
        self.assertEqual(curr.title, "Inspect repo")
        self.assertEqual(curr.status, "in_progress")

        # Mark completed -> advances to next step
        plan.mark_current_completed("Done inspection")
        self.assertEqual(plan.steps[0].status, "completed")
        self.assertEqual(plan.steps[0].notes, "Done inspection")

        next_curr = plan.get_current_task()
        self.assertEqual(next_curr.title, "Write tests")
        self.assertEqual(next_curr.status, "in_progress")

    def test_insert_diagnostic_step(self):
        plan = LivingPlan.from_string_list(["Setup", "Execute", "Verify"])
        plan.get_current_task()  # "Setup" is in_progress
        plan.mark_current_completed()

        # Currently at "Execute"
        curr = plan.get_current_task()
        self.assertEqual(curr.title, "Execute")

        plan.insert_diagnostic_step("Fix missing import in execute")
        self.assertEqual(len(plan.steps), 4)

        # Check markdown output format
        md = plan.to_markdown()
        self.assertIn("Fix / Diagnose: Fix missing import in execute", md)


if __name__ == "__main__":
    unittest.main()
