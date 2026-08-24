from __future__ import annotations
import json
import time
import urllib.error
import urllib.request
from typing import Any
from agent.config import Config
from agent.logging_setup import logger

class OllamaClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def _request(self, method: str, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.config.ollama_host + endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.config.read_timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {body}") from exc
        except Exception as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
        logger.info("OLLAMA RESPONSE %.2fs", time.monotonic() - started)
        logger.debug("OLLAMA RESPONSE: %s", body[:20000])
        result = json.loads(body)
        if not isinstance(result, dict):
            raise RuntimeError("Unexpected Ollama response")
        return result

    def version(self) -> dict[str, Any]:
        return self._request("GET", "/api/version")

    def model_available(self) -> bool:
        models = self._request("GET", "/api/tags").get("models", [])
        return any(isinstance(x, dict) and (x.get("name") == self.config.model or x.get("model") == self.config.model) for x in models)

    def generate(self, prompt: str, num_predict: int | None = None) -> str:
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.config.keep_alive,
            "options": {
                "num_ctx": self.config.num_ctx,
                "num_predict": num_predict or self.config.num_predict,
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "top_k": self.config.top_k,
                "repeat_penalty": 1.05,
            },
        }
        response = self._request("POST", "/api/generate", payload)
        return str(response.get("response", ""))
