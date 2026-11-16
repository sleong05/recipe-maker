"""Provider-agnostic LLM client.

Talks to any OpenAI-compatible endpoint (Ollama Cloud, Groq, Gemini, OpenRouter,
local Ollama). Switch providers by setting these in .env:

    LLM_BASE_URL   default: https://ollama.com/v1
    LLM_MODEL      default: gpt-oss:120b
    LLM_API_KEY    falls back to OLLAMA_API_KEY
    LLM_TEMPERATURE default: 0 (extraction should be repeatable, not creative)
"""

import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError

load_dotenv()

BASE_URL = os.getenv("LLM_BASE_URL", "https://ollama.com/v1")
MODEL = os.getenv("LLM_MODEL", "gpt-oss:120b")
API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OLLAMA_API_KEY")
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

_client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

# Models sometimes wrap JSON in ```json fences despite instructions.
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


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
        reply = _client.chat.completions.create(model=MODEL, messages=messages, temperature=TEMPERATURE)
        content = _FENCE.sub("", (reply.choices[0].message.content or "").strip())
        try:
            return schema.model_validate_json(content)
        except ValidationError as e:
            if attempt == retries:
                raise
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": f"That JSON was invalid:\n{e}\n\nReturn only the corrected JSON object.",
            })
