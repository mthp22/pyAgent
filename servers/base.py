import json
import sys
from typing import Any, Callable, Dict


class MCPServer:
    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.version = version
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable[[Dict[str, Any]], Any],
    ):
        self.tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
        }
        self.handlers[name] = handler

    def _send_response(self, response: Dict[str, Any]):
        out_line = json.dumps(response, ensure_ascii=False)
        sys.stdout.write(out_line + "\n")
        sys.stdout.flush()

    def handle_request(self, req: Dict[str, Any]):
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        # Handle notifications (no id)
        if req_id is None:
            return

        if method == "initialize":
            self._send_response(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": self.name, "version": self.version},
                    },
                }
            )
        elif method == "tools/list":
            self._send_response(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": list(self.tools.values())},
                }
            )
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if tool_name not in self.handlers:
                self._send_response(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": f"Error: Tool '{tool_name}' not found."}],
                            "isError": True,
                        },
                    }
                )
                return

            try:
                res = self.handlers[tool_name](arguments)
                text_result = str(res) if res is not None else ""
                self._send_response(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": text_result}],
                            "isError": False,
                        },
                    }
                )
            except Exception as e:
                self._send_response(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": f"Error executing '{tool_name}': {str(e)}"}],
                            "isError": True,
                        },
                    }
                )
        elif method == "ping":
            self._send_response({"jsonrpc": "2.0", "id": req_id, "result": {}})
        else:
            self._send_response(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )

    def run(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                if isinstance(req, dict):
                    self.handle_request(req)
            except Exception:
                pass
