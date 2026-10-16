import os
import tempfile
import unittest

from agent.session.store import SessionStore


class TestSessionStore(unittest.TestCase):
    def test_session_store_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SessionStore(session_id="sess_123", base_dir=tmp_dir)

            # Metadata save & load
            store.save_session_meta({"goal": "Test goal", "status": "running"})
            meta = store.load_session_meta()
            self.assertEqual(meta["goal"], "Test goal")
            self.assertEqual(meta["status"], "running")
            self.assertIn("updated_at", meta)

            # Plan save & load
            store.save_plan({"steps": [{"id": 1, "title": "Step 1", "status": "completed"}]})
            plan = store.load_plan()
            self.assertEqual(len(plan["steps"]), 1)
            self.assertEqual(plan["steps"][0]["title"], "Step 1")

            # Events append & load
            store.append_event("test_event", {"detail": "abc"})
            store.append_event("test_event2", {"detail": "def"})
            events = store.load_events()
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0]["type"], "test_event")
            self.assertEqual(events[1]["type"], "test_event2")

            # Artifacts
            art_ref = store.save_artifact("test_output.txt", "Full log content here")
            self.assertTrue(art_ref.startswith("artifacts/"))
            full_art_path = os.path.join(tmp_dir, art_ref)
            self.assertTrue(os.path.exists(full_art_path))
            with open(full_art_path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "Full log content here")

            # Markdown snapshots
            store.save_markdown_snapshots(current_md="# Current State", next_md="# Next Steps")
            self.assertTrue(os.path.exists(os.path.join(tmp_dir, "current.md")))
            self.assertTrue(os.path.exists(os.path.join(tmp_dir, "next.md")))


if __name__ == "__main__":
    unittest.main()
