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

    def _request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.config.ollama_host + endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.config.read_timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {body}") from exc
        except Exception as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

        elapsed = time.monotonic() - started
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise RuntimeError("Unexpected Ollama response")

        logger.info("OLLAMA RESPONSE %.2fs", elapsed)
        if endpoint == "/api/generate":
            prompt_count = result.get("prompt_eval_count")
            prompt_ns = result.get("prompt_eval_duration")
            eval_count = result.get("eval_count")
            eval_ns = result.get("eval_duration")
            prompt_ms = (float(prompt_ns) / 1_000_000) if isinstance(prompt_ns, (int, float)) else None
            eval_ms = (float(eval_ns) / 1_000_000) if isinstance(eval_ns, (int, float)) else None
            logger.info(
                "OLLAMA METRICS prompt_tokens=%s prompt_ms=%s eval_tokens=%s eval_ms=%s",
                prompt_count,
                f"{prompt_ms:.1f}" if prompt_ms is not None else "?",
                eval_count,
                f"{eval_ms:.1f}" if eval_ms is not None else "?",
            )
            # Do not log Ollama's huge `context` token array. It adds substantial
            # disk I/O and obscures useful diagnostics.
            logger.debug(
                "OLLAMA GENERATED: %s",
                str(result.get("response", ""))[:12000],
            )
        else:
            logger.debug("OLLAMA RESPONSE KEYS: %s", sorted(result))
        return result

    def version(self) -> dict[str, Any]:
        return self._request("GET", "/api/version")

    def model_available(self) -> bool:
        models = self._request("GET", "/api/tags").get("models", [])
        return any(
            isinstance(item, dict)
            and (item.get("name") == self.config.model or item.get("model") == self.config.model)
            for item in models
        )

    def _generate(self, prompt: str, num_predict: int, json_mode: bool) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.config.keep_alive,
            "options": {
                "num_ctx": self.config.num_ctx,
                "num_predict": num_predict,
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "top_k": self.config.top_k,
            },
        }
        if json_mode:
            payload["format"] = "json"
        response = self._request("POST", "/api/generate", payload)
        text = response.get("response", "")
        return text if isinstance(text, str) else str(text)

    def generate(self, prompt: str, num_predict: int | None = None) -> str:
        """Generate one controller action in Ollama JSON mode."""
        return self._generate(prompt, num_predict or self.config.action_num_predict, json_mode=True)

    def generate_text(self, prompt: str, num_predict: int | None = None) -> str:
        """Generate transformation content without the action protocol."""
        return self._generate(prompt, num_predict or self.config.transform_num_predict, json_mode=False)
