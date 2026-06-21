"""
asomien/llm/client.py

NVIDIA NIM API client using the OpenAI-compatible SDK.
Model: nvidia/nemotron-3-ultra-550b-a55b

Wraps the OpenAI client pointed at the NIM base URL.
All calls go through the NIMRateLimiter token bucket (35 req/min soft cap).

Blueprint reference: Section 5 (NIMClient), Section 12 Step 4.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from openai import OpenAI

from asomien.core.rate_limiter import NIMRateLimiter

logger = logging.getLogger(__name__)

# ── Default model per blueprint ────────────────────────────────────────────────
DEFAULT_MODEL = "meta/llama-3.1-70b-instruct"
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"


class NIMClient:
    """
    NVIDIA NIM API client.

    Uses the OpenAI-compatible interface.
    Every request goes through the NIMRateLimiter to stay under 40 req/min.

    Usage:
        client = NIMClient(api_key="nvapi-...")
        response = client.complete(
            system_prompt="you are...",
            user_prompt="write a post about...",
        )
        print(response)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        max_calls_per_minute: int = 35,
        temperature: float = 0.85,
        max_tokens: int = 1024,
    ) -> None:
        """
        Args:
            api_key:              NIM API key. Falls back to NVIDIA_NIM_API_KEY env var.
            model:                Model identifier. Default: meta/llama-3.1-70b-instruct.
            base_url:             NIM API base URL.
            max_calls_per_minute: Rate limit soft cap (default: 35).
            temperature:          Default temperature for generation. 0.85 for creative content.
            max_tokens:           Default max tokens per response.
        """
        resolved_key = api_key or os.environ.get("NVIDIA_NIM_API_KEY", "")
        if not resolved_key:
            logger.warning(
                "[NIMClient] NVIDIA_NIM_API_KEY not set. "
                "API calls will fail until a key is provided."
            )

        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        self._client = OpenAI(
            api_key=resolved_key or "MISSING",
            base_url=base_url,
            timeout=120.0,
        )
        self._limiter = NIMRateLimiter(max_calls_per_minute=max_calls_per_minute)

        logger.info(
            f"[NIMClient] initialized. model={model}, "
            f"rate_limit={max_calls_per_minute} req/min"
        )

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
    ) -> str:
        """
        Send a chat completion request to NIM.

        Acquires a rate-limit token before making the API call.
        Blocks if the rate limit is currently exhausted.

        Args:
            system_prompt: The system message (persona/instructions).
            user_prompt:   The user message (the actual request).
            temperature:   Override temperature for this call.
            max_tokens:    Override max_tokens for this call.
            stop:          Optional stop sequences.

        Returns:
            The generated text content as a string.

        Raises:
            RuntimeError: If the rate limiter times out.
            openai.APIError: On API-level errors (auth, quota, etc.).
        """
        # Block until a rate-limit token is available
        self._limiter.acquire()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ]

        kwargs: dict[str, Any] = {
            "model":       self.model,
            "messages":    messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens":  max_tokens  if max_tokens  is not None else self.max_tokens,
        }
        if stop:
            kwargs["stop"] = stop

        logger.debug(
            f"[NIMClient] sending request. model={self.model}, "
            f"tokens_remaining={self._limiter.get_remaining()}"
        )

        response = self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""

        logger.debug(
            f"[NIMClient] response received. "
            f"finish_reason={response.choices[0].finish_reason}, "
            f"content_length={len(content)}"
        )

        return content

    def get_remaining_tokens(self) -> int:
        """Returns the number of API calls remaining in the current rate-limit window."""
        return self._limiter.get_remaining()

    def estimate_wait_seconds(self) -> float:
        """Estimate how long until the next token is available (0.0 if immediate)."""
        return self._limiter.estimate_wait()

    @property
    def rate_limiter(self) -> NIMRateLimiter:
        """Direct access to the underlying rate limiter (for testing/monitoring)."""
        return self._limiter
