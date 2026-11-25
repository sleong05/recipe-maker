"""One class per LLM provider. Every provider answers the same call: chat(messages) -> str.

The rest of the pipeline never knows which provider it's talking to, so a new one
(another API, a local model) only needs a subclass here plus an entry in PROVIDERS.

Most hosted providers speak the OpenAI chat API, so they share OpenAICompatible and
differ only in URL, default model and where their keys live in .env. A provider that
doesn't speak that API would subclass Provider directly and write its own chat().
"""

import os
from abc import ABC, abstractmethod

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

load_dotenv()  # Before the classes below read their settings.


class ProviderError(Exception):
    """A provider couldn't answer. `kind` tells the chain how long to stay away from it:

    "dead"      - bad key, no credits, unknown model: skip it for the rest of this run
    "cooldown"  - rate limited: skip it for a while, then try again
    "transient" - server error, timeout, request too big: skip it for this call only
    """

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class Provider(ABC):
    """Anything that can turn chat messages into a reply string."""

    name: str  # Shown in logs, e.g. "gemini#2".

    @abstractmethod
    def chat(self, messages: list[dict], temperature: float) -> str:
        """Return the reply text, or raise ProviderError."""


class OpenAICompatible(Provider):
    """Any endpoint that speaks the OpenAI chat-completions API."""

    base_url: str
    default_model: str
    env_prefix: str        # GEMINI -> reads GEMINI_API_KEYS and GEMINI_MODEL
    needs_key: bool = True

    def __init__(self, api_key: str, label: str):
        self.name = label
        self.model = os.getenv(f"{self.env_prefix}_MODEL", self.default_model)
        # Fail fast (one quick retry) so the chain moves on instead of waiting out backoffs.
        self._client = OpenAI(base_url=self.base_url, api_key=api_key or "none", max_retries=1, timeout=180)

    @classmethod
    def from_env(cls, slug: str) -> list["Provider"]:
        """One instance per key in <PREFIX>_API_KEYS (comma-separated). No keys -> none."""
        if not cls.needs_key:
            return [cls("", slug)]
        raw = os.getenv(f"{cls.env_prefix}_API_KEYS") or os.getenv(f"{cls.env_prefix}_API_KEY") or ""
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if len(keys) == 1:
            return [cls(keys[0], slug)]
        return [cls(key, f"{slug}#{i}") for i, key in enumerate(keys, 1)]

    def chat(self, messages: list[dict], temperature: float) -> str:
        try:
            reply = self._client.chat.completions.create(
                model=self.model, messages=messages, temperature=temperature)
        except APIStatusError as e:
            code = e.status_code
            if code in (401, 402, 403, 404):
                reasons = {401: "API key rejected", 402: "out of credits",
                           403: "key not allowed to use this model", 404: f"model '{self.model}' not found"}
                raise ProviderError("dead", f"{code} {reasons[code]}") from None
            if code == 429:
                raise ProviderError("cooldown", "429 rate limited / quota used up") from None
            if code == 413:
                raise ProviderError("transient", "413 request too large for this provider") from None
            raise ProviderError("transient", f"{code} {e.message}") from None
        except APITimeoutError:
            raise ProviderError("transient", "timed out") from None
        except APIConnectionError:
            raise ProviderError("transient", f"couldn't reach {self.base_url}") from None
        return (reply.choices[0].message.content or "").strip()


# --- Hosted providers (free tiers) -------------------------------------------------

class Gemini(OpenAICompatible):
    """Google AI Studio free tier."""
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    default_model = "gemini-3.6-flash"
    env_prefix = "GEMINI"


class GeminiPaid(Gemini):
    """Same API as Gemini, separate paid key, so it can sit last in the order as a backstop."""
    env_prefix = "GEMINI_PAID"


class Groq(OpenAICompatible):
    base_url = "https://api.groq.com/openai/v1"
    default_model = "openai/gpt-oss-120b"
    env_prefix = "GROQ"


class OpenRouter(OpenAICompatible):
    base_url = "https://openrouter.ai/api/v1"
    default_model = "openai/gpt-oss-120b:free"
    env_prefix = "OPENROUTER"


class Cerebras(OpenAICompatible):
    base_url = "https://api.cerebras.ai/v1"
    default_model = "gpt-oss-120b"
    env_prefix = "CEREBRAS"


class OllamaCloud(OpenAICompatible):
    base_url = "https://ollama.com/v1"
    default_model = "gpt-oss:120b"
    env_prefix = "OLLAMA"


# --- Local models ------------------------------------------------------------------

class LocalOllama(OpenAICompatible):
    """A model running on this machine via `ollama serve`. No key, no limits."""
    base_url = os.getenv("LOCAL_OLLAMA_URL", "http://localhost:11434/v1")
    default_model = "gpt-oss:20b"
    env_prefix = "LOCAL_OLLAMA"
    needs_key = False


# Names usable in LLM_PROVIDERS in .env.
PROVIDERS: dict[str, type[OpenAICompatible]] = {
    "gemini": Gemini,
    "groq": Groq,
    "openrouter": OpenRouter,
    "cerebras": Cerebras,
    "ollama": OllamaCloud,
    "local": LocalOllama,
    "gemini_paid": GeminiPaid,
}
