from typing import Optional

from agent.config import LLM_ENDPOINT, LLM_TIMEOUT, MODEL_NAME, LLMConfig
from agent.llm.base import (
    BaseLLMProvider,
    LLMMessage,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)
from agent.llm.ollama import OllamaProvider

__all__ = [
    "BaseLLMProvider",
    "OllamaProvider",
    "LLMMessage",
    "LLMResponse",
    "ToolCall",
    "ToolDefinition",
    "get_llm_provider",
    "query_llm",
]


def get_llm_provider(
    provider_name: str = "ollama",
    model: Optional[str] = None,
    config: Optional[LLMConfig] = None,
) -> BaseLLMProvider:
    resolved_model = model or MODEL_NAME
    if config:
        if config.provider == "ollama":
            return OllamaProvider.from_config(model=resolved_model, config=config)
    return OllamaProvider(model=resolved_model, endpoint=LLM_ENDPOINT, timeout=LLM_TIMEOUT)


def query_llm(
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.2,
    json_mode: bool = True,
) -> str:
    """Legacy query_llm adapter for backward compatibility."""
    provider = OllamaProvider(model=MODEL_NAME, endpoint=LLM_ENDPOINT, timeout=LLM_TIMEOUT)
    return provider.generate(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        json_mode=json_mode,
    )
