import json
import logging
import os
import subprocess
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MCPProcessClient:
    """Manages an individual MCP server running over stdio."""

    def __init__(self, name: str, command: str, args: List[str], cwd: str, env: Optional[Dict[str, str]] = None):
        self.name = name
        self.command = command
        self.args = args
        self.cwd = cwd
        self.env = env or dict(os.environ)

        # Ensure cwd is in PYTHONPATH so server scripts can resolve imports
        existing_pp = self.env.get("PYTHONPATH", "")
        self.env["PYTHONPATH"] = f"{self.cwd}:{existing_pp}" if existing_pp else self.cwd
        self.env["WORKSPACE_DIR"] = self.cwd

        self.process: Optional[subprocess.Popen] = None
        self._req_id = 0
        self._lock = threading.Lock()

    def start(self) -> bool:
        cmd = [self.command] + self.args
        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=self.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=self.env,
            )
            return self._initialize()
        except Exception as e:
            logger.error(f"[MCP {self.name}] Failed to start process: {e}")
            return False

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Dict[str, Any]:
        with self._lock:
            if not self.process or self.process.poll() is not None:
                raise RuntimeError(f"Server '{self.name}' process is not running.")

            req_id = self._next_id()
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                payload["params"] = params

            msg = json.dumps(payload) + "\n"
            if not self.process.stdin:
                raise RuntimeError(f"Server '{self.name}' has no stdin.")

            self.process.stdin.write(msg)
            self.process.stdin.flush()

            line = self.process.stdout.readline() if self.process.stdout else ""
            if not line:
                stderr_output = ""
                try:
                    if self.process.stderr:
                        stderr_output = self.process.stderr.read()
                except Exception:
                    pass
                raise RuntimeError(f"Server '{self.name}' closed stdout unexpectedly. Stderr: {stderr_output}")

            try:
                data = json.loads(line)
                return data
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSON response from server '{self.name}': {line}") from exc

    def _send_notification(self, method: str, params: Optional[Dict[str, Any]] = None):
        with self._lock:
            if not self.process or self.process.poll() is not None:
                return
            payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                payload["params"] = params
            if self.process.stdin:
                self.process.stdin.write(json.dumps(payload) + "\n")
                self.process.stdin.flush()

    def _initialize(self) -> bool:
        try:
            resp = self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "pyagent", "version": "0.1.0"},
                },
                timeout=10,
            )
            if "result" in resp:
                self._send_notification("notifications/initialized")
                return True
            return False
        except Exception as e:
            logger.error(f"[MCP {self.name}] Initialization failed: {e}")
            return False

    def list_tools(self) -> List[Dict[str, Any]]:
        try:
            resp = self._send_request("tools/list", {})
            result = resp.get("result", {})
            return result.get("tools", [])
        except Exception as e:
            logger.error(f"[MCP {self.name}] tools/list failed: {e}")
            return []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        try:
            resp = self._send_request("tools/call", {"name": name, "arguments": arguments}, timeout=120)
            result = resp.get("result", {})
            is_error = result.get("isError", False)
            content_list = result.get("content", [])

            text_outputs = []
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_outputs.append(item.get("text", ""))
                else:
                    text_outputs.append(str(item))

            joined = "\n".join(text_outputs)
            if is_error and not joined.startswith("Error"):
                return f"Error: {joined}"
            return joined
        except Exception as e:
            return f"Error calling tool '{name}' on server '{self.name}': {e}"

    def stop(self):
        with self._lock:
            if self.process:
                for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                    if pipe and not pipe.closed:
                        try:
                            pipe.close()
                        except Exception:
                            pass
                if self.process.poll() is None:
                    try:
                        self.process.terminate()
                        self.process.wait(timeout=2)
                    except Exception:
                        try:
                            self.process.kill()
                        except Exception:
                            pass
                self.process = None


class MCPClientManager:
    """Manages connections to multiple MCP servers configured in servers.json."""

    def __init__(
        self,
        workspace_dir: str,
        allowed_commands: Optional[List[str]] = None,
        dangerous_flags: Optional[List[str]] = None,
    ):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.clients: Dict[str, MCPProcessClient] = {}
        self.allowed_commands = allowed_commands
        self.dangerous_flags = dangerous_flags

    def load_and_start(self, config_file: str) -> Dict[str, bool]:
        full_cfg_path = (
            config_file
            if os.path.isabs(config_file)
            else os.path.join(self.workspace_dir, config_file)
        )
        if not os.path.exists(full_cfg_path):
            logger.warning(f"MCP configuration file '{full_cfg_path}' not found.")
            return {}

        try:
            with open(full_cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to parse MCP config: {e}")
            return {}

        servers_cfg = data.get("servers", {})
        results: Dict[str, bool] = {}

        # Ensure environment has WORKSPACE_DIR set
        env = dict(os.environ)
        env["WORKSPACE_DIR"] = self.workspace_dir
        # Propagate the effective command policy so MCP servers enforce the same
        # allowlist and dangerous-flag rules as the in-process tools.
        if self.allowed_commands is not None:
            env["PYAGENT_ALLOWED_COMMANDS"] = ",".join(self.allowed_commands)
        if self.dangerous_flags is not None:
            env["PYAGENT_DANGEROUS_FLAGS"] = ",".join(self.dangerous_flags)

        for s_name, s_def in servers_cfg.items():
            cmd = s_def.get("command", "python3")
            args = s_def.get("args", [])
            client = MCPProcessClient(
                name=s_name,
                command=cmd,
                args=args,
                cwd=self.workspace_dir,
                env=env,
            )
            success = client.start()
            if success:
                self.clients[s_name] = client
            results[s_name] = success

        return results

    def get_client(self, server_name: str) -> Optional[MCPProcessClient]:
        return self.clients.get(server_name)

    def shutdown(self):
        for name, client in list(self.clients.items()):
            try:
                client.stop()
            except Exception:
                pass
        self.clients.clear()
