import json
import os
import tempfile
import unittest

from agent.repo.profiler import RepoProfiler


class TestRepoProfiler(unittest.TestCase):
    def test_current_workspace_profiling(self):
        profiler = RepoProfiler(workspace_dir=os.getcwd())
        profile = profiler.profile()

        self.assertEqual(profile.primary_language, "python")
        self.assertIn("python", profile.languages)
        self.assertIn("agent", profile.source_dirs)
        self.assertIn("tests", profile.test_dirs)
        self.assertIn(profile.test_framework, ["unittest", "pytest"])

        prompt_summary = profile.to_prompt_summary()
        self.assertIn("Language: python", prompt_summary)
        self.assertIn("Test Framework:", prompt_summary)

    def test_synthetic_fastapi_python_repo(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.makedirs(os.path.join(tmp_dir, "app"))
            os.makedirs(os.path.join(tmp_dir, "tests"))

            req_path = os.path.join(tmp_dir, "requirements.txt")
            with open(req_path, "w", encoding="utf-8") as f:
                f.write("fastapi>=0.100.0\nuvicorn\npytest>=7.0.0\nruff\n")

            profiler = RepoProfiler(workspace_dir=tmp_dir)
            profile = profiler.profile()

            self.assertEqual(profile.primary_language, "python")
            self.assertIn("fastapi", profile.frameworks)
            self.assertEqual(profile.package_manager, "pip")
            self.assertEqual(profile.test_framework, "pytest")
            self.assertEqual(profile.recommended_test_cmd, "pytest")
            self.assertEqual(profile.recommended_lint_cmd, "ruff check .")
            self.assertIn("app", profile.source_dirs)
            self.assertIn("tests", profile.test_dirs)

    def test_synthetic_node_repo(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.makedirs(os.path.join(tmp_dir, "src"))
            os.makedirs(os.path.join(tmp_dir, "__tests__"))

            pkg_data = {
                "name": "sample-node-app",
                "scripts": {
                    "test": "vitest run",
                    "lint": "eslint .",
                },
                "dependencies": {
                    "react": "^18.0.0",
                    "next": "^14.0.0",
                },
                "devDependencies": {
                    "vitest": "^1.0.0",
                    "typescript": "^5.0.0",
                },
            }
            with open(os.path.join(tmp_dir, "package.json"), "w", encoding="utf-8") as f:
                json.dump(pkg_data, f)
            with open(os.path.join(tmp_dir, "tsconfig.json"), "w", encoding="utf-8") as f:
                f.write("{}")

            profiler = RepoProfiler(workspace_dir=tmp_dir)
            profile = profiler.profile()

            self.assertEqual(profile.primary_language, "typescript")
            self.assertIn("nextjs", profile.frameworks)
            self.assertEqual(profile.test_framework, "vitest")
            self.assertEqual(profile.recommended_test_cmd, "npm test")
            self.assertEqual(profile.recommended_lint_cmd, "npm run lint")
            self.assertIn("src", profile.source_dirs)
            self.assertIn("__tests__", profile.test_dirs)

    def test_synthetic_rust_repo(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.makedirs(os.path.join(tmp_dir, "src"))
            with open(os.path.join(tmp_dir, "Cargo.toml"), "w", encoding="utf-8") as f:
                f.write('[package]\nname = "test_crate"\nversion = "0.1.0"\n')

            profiler = RepoProfiler(workspace_dir=tmp_dir)
            profile = profiler.profile()

            self.assertEqual(profile.primary_language, "rust")
            self.assertEqual(profile.package_manager, "cargo")
            self.assertEqual(profile.recommended_test_cmd, "cargo test")


if __name__ == "__main__":
    unittest.main()
