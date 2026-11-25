"""Provider-agnostic LLM access. Steps only ever use `complete(prompt, schema)`.

    client.py     complete(): prompt -> validated Pydantic object
    chain.py      ProviderChain: tries each provider in turn until one answers
    providers.py  one class per provider (Gemini, Groq, local Ollama, ...)
"""

from .client import complete

__all__ = ["complete"]
