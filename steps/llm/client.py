"""complete(): send a prompt, get back a validated Pydantic object.

Which model answers is decided by the provider chain (see chain.py and .env.example);
nothing here depends on a specific provider.

    LLM_TEMPERATURE  default: 0 (extraction should be repeatable, not creative)
"""

import json
import os
import re

from pydantic import BaseModel, ValidationError

from .chain import ProviderChain

TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

# Models sometimes wrap JSON in ```json fences despite instructions.
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

_chain: ProviderChain | None = None


def _chat(messages: list[dict]) -> str:
    """One chat call through the chain, built on first use so importing never fails."""
    global _chain
    if _chain is None:
        _chain = ProviderChain.from_env()
    return _FENCE.sub("", _chain.chat(messages, TEMPERATURE))


def complete[T: BaseModel](prompt: str, schema: type[T], system: str = "", retries: int = 2) -> T:
    """Send a prompt and return the reply parsed into `schema`.

    The JSON schema is included in the prompt rather than relying on a provider's
    structured-output mode, so this works with any model. On invalid output the
    validation error is sent back to the model and it gets another try.
    """
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({
        "role": "user",
        "content": f"{prompt}\n\nRespond with only a JSON object matching this schema, "
                   f"no other text:\n{schema_json}",
    })

    for attempt in range(retries + 1):
        content = _chat(messages)
        try:
            return schema.model_validate_json(content)
        except ValidationError as e:
            if attempt == retries:
                raise SystemExit(f"LLM error: the model returned invalid {schema.__name__} JSON "
                                 f"{retries + 1} times in a row.\n{e}") from None
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": f"That JSON was invalid:\n{e}\n\nReturn only the corrected JSON object.",
            })
