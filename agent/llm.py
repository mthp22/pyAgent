import json
import requests
from typing import Dict, Any, Optional

from agent.config import LLM_ENDPOINT, MODEL_NAME, LLM_TIMEOUT

def query_llm(prompt: str, system_prompt: str = "", temperature: float = 0.2, json_mode: bool = True) -> str:
    """
    Queries the local CodeLlama via the Ollama HTTP API.
    """
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": temperature
        }
    }
    
    if json_mode:
        payload["format"] = "json"

    try:
        response = requests.post(LLM_ENDPOINT, json=payload, timeout=LLM_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "")
    except requests.exceptions.RequestException as e:
        print(f"[Error querying LLM]: {e}")
        return "{}" # Return empty JSON gracefully if error
