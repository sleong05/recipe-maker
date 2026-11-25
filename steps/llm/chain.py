"""Tries providers in order until one answers.

The order comes from LLM_PROVIDERS in .env; each provider can have several keys, and
each key is its own entry in the chain. Providers that fail are benched so later calls
in the same run don't waste time on them (see ProviderError for how long).
"""

import os
import sys
import time

from .providers import PROVIDERS, Provider, ProviderError

DEFAULT_ORDER = "gemini,groq,cerebras,openrouter,gemini_paid"
COOLDOWN_SECONDS = 60


class ProviderChain:
    def __init__(self, providers: list[Provider]):
        self.providers = providers
        self._benched_until: dict[str, float] = {}  # provider name -> time it may be tried again

    @classmethod
    def from_env(cls) -> "ProviderChain":
        order = [s.strip() for s in os.getenv("LLM_PROVIDERS", DEFAULT_ORDER).split(",") if s.strip()]
        unknown = [s for s in order if s not in PROVIDERS]
        if unknown:
            raise SystemExit(f"LLM error: unknown provider(s) {unknown} in LLM_PROVIDERS. "
                             f"Choose from: {', '.join(PROVIDERS)}")
        return cls([p for slug in order for p in PROVIDERS[slug].from_env(slug)])

    def chat(self, messages: list[dict], temperature: float) -> str:
        if not self.providers:
            raise SystemExit("LLM error: no providers have API keys. Add at least one *_API_KEYS line to .env "
                             "(see .env.example).")
        failures = []
        for provider in self.providers:
            until = self._benched_until.get(provider.name, 0)
            if until > time.time():
                failures.append(f"{provider.name}: skipped (failed earlier this run)")
                continue
            try:
                reply = provider.chat(messages, temperature)
            except ProviderError as e:
                failures.append(f"{provider.name}: {e}")
                print(f"  [llm] {provider.name} failed ({e}), trying next provider", file=sys.stderr)
                if e.kind == "dead":
                    self._benched_until[provider.name] = float("inf")
                elif e.kind == "cooldown":
                    self._benched_until[provider.name] = time.time() + COOLDOWN_SECONDS
                continue
            if failures:
                print(f"  [llm] answered by {provider.name}", file=sys.stderr)
            return reply
        raise SystemExit("LLM error: every provider failed:\n  " + "\n  ".join(failures))
