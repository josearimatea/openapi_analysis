"""The judge's LLM client and its usage tally (layer 3; needs the [judge] extra).

Same construction as openapi_generator / openapi_rulesbank: one ChatOpenAI client,
since OpenAI and OpenRouter speak the same chat-completions protocol — the provider
only decides the key, base URL, headers and how reasoning is passed.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI

from openapi_analysis.config import judge_settings as s


class UsageTracker(BaseCallbackHandler):
    """Totals calls, tokens and cost of every LLM call in this process.

    OpenRouter reports `cost` in US dollars inside token_usage; OpenAI does not, and
    the total then stays 0.0 while the token counts remain right.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0
        self.cached_tokens = 0
        self.cost = 0.0

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        usage = (response.llm_output or {}).get("token_usage") or {}
        if not usage:  # structured-output calls report usage on the generation
            for generation in response.generations or []:
                for item in generation:
                    meta = getattr(getattr(item, "message", None), "response_metadata", {}) or {}
                    usage = meta.get("token_usage") or {}
                    if usage:
                        break
                if usage:
                    break
        if not usage:
            return
        self.calls += 1
        self.prompt_tokens += usage.get("prompt_tokens", 0) or 0
        self.completion_tokens += usage.get("completion_tokens", 0) or 0
        self.cost += usage.get("cost", 0.0) or 0.0
        self.reasoning_tokens += (usage.get("completion_tokens_details") or {}).get(
            "reasoning_tokens", 0) or 0
        self.cached_tokens += (usage.get("prompt_tokens_details") or {}).get(
            "cached_tokens", 0) or 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_prompt_tokens": self.cached_tokens,
            "cost_usd": round(self.cost, 6),
        }


usage_tracker = UsageTracker()


def _provider_kwargs() -> dict[str, Any]:
    if s.PROVIDER == "openrouter":
        if not s.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY is not set (see .env.example).")
        kwargs: dict[str, Any] = {"api_key": s.OPENROUTER_API_KEY,
                                  "base_url": s.OPENROUTER_BASE_URL,
                                  "default_headers": {"X-Title": s.OPENROUTER_APP_NAME}}
        # OpenRouter takes reasoning as a body field; "none" means omit it.
        if s.REASONING_EFFORT and s.REASONING_EFFORT != "none":
            kwargs["extra_body"] = {"reasoning": {"effort": s.REASONING_EFFORT}}
        return kwargs
    if s.PROVIDER == "openai":
        if not s.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set (see .env.example).")
        kwargs = {"api_key": s.OPENAI_API_KEY}
        if s.REASONING_EFFORT and s.REASONING_EFFORT != "none":
            kwargs["reasoning_effort"] = s.REASONING_EFFORT
        return kwargs
    raise ValueError(f"Unknown JUDGE_PROVIDER {s.PROVIDER!r} (openrouter | openai).")


@lru_cache(maxsize=1)
def get_llm() -> ChatOpenAI:
    """The judge's client, built once from judge_settings, with the usage tracker attached."""
    return ChatOpenAI(model=s.MODEL, temperature=s.TEMPERATURE,
                      timeout=s.LLM_REQUEST_TIMEOUT, max_retries=s.LLM_MAX_RETRIES,
                      callbacks=[usage_tracker], **_provider_kwargs())
