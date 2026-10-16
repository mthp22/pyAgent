import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class ProjectProfile:
    workspace_dir: str
    primary_language: str = "unknown"
    languages: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    package_manager: Optional[str] = None
    test_framework: Optional[str] = None
    recommended_test_cmd: Optional[str] = None
    recommended_lint_cmd: Optional[str] = None
    is_git_repo: bool = False
    git_branch: Optional[str] = None
    git_clean: Optional[bool] = None
    has_docker: bool = False
    source_dirs: List[str] = field(default_factory=list)
    test_dirs: List[str] = field(default_factory=list)
    key_files: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_prompt_summary(self) -> str:
        parts = [
            f"Language: {self.primary_language}" + (f" ({', '.join(self.languages)})" if len(self.languages) > 1 else ""),
            f"Frameworks: {', '.join(self.frameworks) if self.frameworks else 'None detected'}",
            f"Package Manager: {self.package_manager or 'None'}",
            f"Test Framework: {self.test_framework or 'None'}",
            f"Recommended Test Command: {self.recommended_test_cmd or 'None'}",
            f"Recommended Lint Command: {self.recommended_lint_cmd or 'None'}",
            f"Git: {'Yes (branch: ' + str(self.git_branch) + ', clean: ' + str(self.git_clean) + ')' if self.is_git_repo else 'No'}",
            f"Key Directories: source=[{', '.join(self.source_dirs)}], tests=[{', '.join(self.test_dirs)}]",
        ]
        return "\n".join(parts)


class RepoProfiler:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = os.path.abspath(workspace_dir)

    def profile(self) -> ProjectProfile:
        languages: Set[str] = set()
        frameworks: Set[str] = set()
        key_files: List[str] = []
        source_dirs: List[str] = []
        test_dirs: List[str] = []

        # Check for Git
        is_git, branch, is_clean = self._inspect_git()

        # Check for Docker
        has_docker = os.path.exists(os.path.join(self.workspace_dir, "Dockerfile")) or os.path.exists(
            os.path.join(self.workspace_dir, "docker-compose.yml")
        )

        # Inspect root directory files
        try:
            entries = os.listdir(self.workspace_dir)
        except Exception:
            entries = []

        package_manager = None
        test_framework = None
        recommended_test_cmd = None
        recommended_lint_cmd = None

        # Check Python
        pyproject_path = os.path.join(self.workspace_dir, "pyproject.toml")
        reqs_path = os.path.join(self.workspace_dir, "requirements.txt")
        setup_py = os.path.join(self.workspace_dir, "setup.py")
        uv_lock = os.path.join(self.workspace_dir, "uv.lock")
        poetry_lock = os.path.join(self.workspace_dir, "poetry.lock")

        has_python_files = any(f.endswith(".py") for f in entries) or os.path.exists(pyproject_path) or os.path.exists(reqs_path)
        if has_python_files:
            languages.add("python")
            if os.path.exists(uv_lock):
                package_manager = "uv"
            elif os.path.exists(poetry_lock):
                package_manager = "poetry"
            elif os.path.exists(reqs_path):
                package_manager = "pip"

            # Inspect requirements / pyproject for frameworks
            file_contents = ""
            for p in (pyproject_path, reqs_path, setup_py):
                if os.path.exists(p):
                    key_files.append(os.path.basename(p))
                    try:
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            file_contents += "\n" + f.read()
                    except Exception:
                        pass

            content_lower = file_contents.lower()
            if "fastapi" in content_lower:
                frameworks.add("fastapi")
            if "flask" in content_lower:
                frameworks.add("flask")
            if "django" in content_lower:
                frameworks.add("django")
            if "pytest" in content_lower or os.path.exists(os.path.join(self.workspace_dir, "pytest.ini")):
                test_framework = "pytest"
                recommended_test_cmd = "pytest"
            else:
                test_framework = "unittest"
                recommended_test_cmd = "python -m unittest discover tests"

            if "ruff" in content_lower:
                recommended_lint_cmd = "ruff check ."
            elif "flake8" in content_lower:
                recommended_lint_cmd = "flake8 ."

        # Check JavaScript / TypeScript
        pkg_json_path = os.path.join(self.workspace_dir, "package.json")
        if os.path.exists(pkg_json_path):
            key_files.append("package.json")
            if os.path.exists(os.path.join(self.workspace_dir, "tsconfig.json")):
                languages.add("typescript")
                key_files.append("tsconfig.json")
            else:
                languages.add("javascript")

            if os.path.exists(os.path.join(self.workspace_dir, "pnpm-lock.yaml")):
                package_manager = "pnpm"
            elif os.path.exists(os.path.join(self.workspace_dir, "yarn.lock")):
                package_manager = "yarn"
            elif os.path.exists(os.path.join(self.workspace_dir, "bun.lockb")):
                package_manager = "bun"
            else:
                package_manager = package_manager or "npm"

            try:
                with open(pkg_json_path, "r", encoding="utf-8", errors="ignore") as f:
                    pkg_data = json.load(f)
                    scripts = pkg_data.get("scripts", {})
                    deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}

                    if "next" in deps:
                        frameworks.add("nextjs")
                    elif "react" in deps:
                        frameworks.add("react")
                    elif "express" in deps:
                        frameworks.add("express")

                    if "test" in scripts:
                        recommended_test_cmd = f"{package_manager or 'npm'} test"
                        if "vitest" in deps:
                            test_framework = "vitest"
                        elif "jest" in deps:
                            test_framework = "jest"
                        else:
                            test_framework = "npm test"

                    if "lint" in scripts:
                        recommended_lint_cmd = f"{package_manager or 'npm'} run lint"
            except Exception:
                pass

        # Check Rust
        cargo_path = os.path.join(self.workspace_dir, "Cargo.toml")
        if os.path.exists(cargo_path):
            languages.add("rust")
            key_files.append("Cargo.toml")
            package_manager = "cargo"
            test_framework = "cargo test"
            recommended_test_cmd = "cargo test"
            recommended_lint_cmd = "cargo clippy"

        # Check Go
        go_mod_path = os.path.join(self.workspace_dir, "go.mod")
        if os.path.exists(go_mod_path):
            languages.add("go")
            key_files.append("go.mod")
            package_manager = "go"
            test_framework = "go test"
            recommended_test_cmd = "go test ./..."
            recommended_lint_cmd = "golangci-lint run"

        # Identify source and test directories
        for entry in entries:
            full = os.path.join(self.workspace_dir, entry)
            if os.path.isdir(full) and not entry.startswith(".") and entry != "__pycache__" and entry != "node_modules" and entry != ".venv":
                lower = entry.lower()
                if lower in ("tests", "test", "__tests__", "spec"):
                    test_dirs.append(entry)
                elif lower in ("src", "app", "lib", "pkg", "agent", "pyagent", "servers"):
                    source_dirs.append(entry)

        # Primary language heuristic
        sorted_languages = sorted(list(languages))
        primary_lang = sorted_languages[0] if sorted_languages else "unknown"
        if "python" in languages:
            primary_lang = "python"
        elif "typescript" in languages:
            primary_lang = "typescript"
        elif "javascript" in languages:
            primary_lang = "javascript"
        elif "rust" in languages:
            primary_lang = "rust"
        elif "go" in languages:
            primary_lang = "go"

        return ProjectProfile(
            workspace_dir=self.workspace_dir,
            primary_language=primary_lang,
            languages=sorted(list(languages)),
            frameworks=sorted(list(frameworks)),
            package_manager=package_manager,
            test_framework=test_framework,
            recommended_test_cmd=recommended_test_cmd,
            recommended_lint_cmd=recommended_lint_cmd,
            is_git_repo=is_git,
            git_branch=branch,
            git_clean=is_clean,
            has_docker=has_docker,
            source_dirs=sorted(source_dirs),
            test_dirs=sorted(test_dirs),
            key_files=sorted(key_files),
        )

    def _inspect_git(self) -> tuple[bool, Optional[str], Optional[bool]]:
        git_dir = os.path.join(self.workspace_dir, ".git")
        if not os.path.exists(git_dir):
            return False, None, None

        branch = None
        is_clean = None
        try:
            res_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res_branch.returncode == 0:
                branch = res_branch.stdout.strip()

            res_status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res_status.returncode == 0:
                is_clean = len(res_status.stdout.strip()) == 0
        except Exception:
            pass

        return True, branch, is_clean
