import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from agent.config import LLMConfig
from agent.llm.base import BaseLLMProvider, LLMMessage, LLMResponse, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)

# Transient connection failures are retried with a short linear backoff.
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECS = 0.5


class OllamaProvider(BaseLLMProvider):
    def __init__(
        self,
        model: str = "qwen2.5-coder:7b",
        endpoint: str = "http://localhost:11434",
        timeout: int = 120,
    ):
        self.model = model
        # Base endpoint without trailing slash or path suffixes
        clean_endpoint = endpoint.rstrip("/")
        for suffix in ("/api/generate", "/api/chat", "/api"):
            if clean_endpoint.endswith(suffix):
                clean_endpoint = clean_endpoint[: -len(suffix)]
        self.base_url = clean_endpoint
        self.generate_url = f"{self.base_url}/api/generate"
        self.chat_url = f"{self.base_url}/api/chat"
        self.timeout = timeout

    @classmethod
    def from_config(cls, model: str, config: LLMConfig) -> "OllamaProvider":
        return cls(
            model=model,
            endpoint=config.endpoint,
            timeout=config.timeout,
        )

    def _http_post(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data_bytes = json.dumps(payload).encode("utf-8")
        last_error: Optional[Exception] = None
        for attempt in range(1, _MAX_RETRIES + 1):
            req = urllib.request.Request(
                url,
                data=data_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_bytes = resp.read()
                    return json.loads(resp_bytes.decode("utf-8"))
            except urllib.error.HTTPError as e:
                # Client/protocol errors are not retryable; surface immediately.
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8")
                except Exception:
                    pass
                logger.error(f"[Ollama HTTP error {e.code}]: {err_body or e.reason}")
                raise RuntimeError(f"Ollama HTTP error {e.code}: {err_body or e.reason}") from e
            except Exception as e:
                # Connection/read timeouts and resets are transient; retry.
                last_error = e
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "[Ollama request attempt %d/%d failed]: %s; retrying in %.1fs",
                        attempt,
                        _MAX_RETRIES,
                        e,
                        _RETRY_BACKOFF_SECS,
                    )
                    time.sleep(_RETRY_BACKOFF_SECS)
        logger.error(f"[Ollama connection error after {_MAX_RETRIES} attempts]: {last_error}")
        raise RuntimeError(f"Failed to connect to Ollama at {url}: {last_error}") from last_error

    def ping(self) -> bool:
        req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> str:
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"

        try:
            data = self._http_post(self.generate_url, payload)
            return data.get("response", "")
        except Exception as e:
            logger.error(f"[Ollama generate failed]: {e}")
            return "{}" if json_mode else ""

    def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> LLMResponse:
        formatted_messages = []
        for msg in messages:
            m_dict: Dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                m_dict["tool_calls"] = [
                    {
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        }
                    }
                    for tc in msg.tool_calls
                ]
            formatted_messages.append(m_dict)

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "stream": False,
            "options": {"temperature": temperature},
        }

        if tools:
            payload["tools"] = [t.to_ollama_format() for t in tools]

        if json_mode and not tools:
            payload["format"] = "json"

        try:
            data = self._http_post(self.chat_url, payload)
        except Exception as e:
            logger.error(f"[Ollama chat failed]: {e}")
            return LLMResponse(content="{}" if json_mode else "", raw=str(e))

        message = data.get("message", {})
        content = message.get("content", "")
        tool_calls: List[ToolCall] = []

        raw_calls = message.get("tool_calls", [])
        if raw_calls:
            for idx, raw_tc in enumerate(raw_calls):
                fn = raw_tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                tc_id = raw_tc.get("id", f"call_{idx}")
                tool_calls.append(ToolCall(id=tc_id, name=name, arguments=args))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            raw=data,
            finish_reason=data.get("done_reason"),
        )
