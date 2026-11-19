"""Optional LLM call for AI-written status updates. Falls back to templates if unavailable.

Configure with environment variables (no key set = template drafts only):
  ANTHROPIC_API_KEY   -> Anthropic Messages API   (model: LLM_MODEL, default claude-sonnet-5-5)
  OPENAI_API_KEY      -> OpenAI-compatible chat API (model: LLM_MODEL, default gpt-4o-mini,
                         base URL: OPENAI_BASE_URL, default https://api.openai.com/v1)
"""
from __future__ import annotations

import os

import httpx


def llm_configured() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))


def llm_complete(system: str, prompt: str, timeout: float = 25.0) -> str | None:
    """Return generated text, or None if no provider is configured or the call fails."""
    try:
        if os.getenv("ANTHROPIC_API_KEY"):
            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": os.getenv("LLM_MODEL", "claude-sonnet-5-5"),
                    "max_tokens": 400,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=timeout,
            )
            r.raise_for_status()
            parts = r.json().get("content", [])
            text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
            return text or None
        if os.getenv("OPENAI_API_KEY"):
            base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
            r = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                json={
                    "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
                    "max_tokens": 400,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=timeout,
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"].strip()
            return text or None
    except Exception:
        return None
    return None
