"""Helpers shared by all steps: every step takes a YouTube URL and finds its files from it."""

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from models import PipelineState

# Fixed to the project root so steps work no matter which directory they're run from.
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_id_from_url(url: str) -> str:
    """Extract the 11-character video ID from any common YouTube URL form.

    Handles youtube.com/watch?v=ID, youtu.be/ID, /shorts/ID, /embed/ID, /live/ID.
    """
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")

    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            candidate = parts[1] if len(parts) > 1 and parts[0] in ("shorts", "embed", "live") else ""
    else:
        candidate = ""

    if not VIDEO_ID.match(candidate):
        raise ValueError(f"Not a recognised YouTube video URL: {url}")
    return candidate


def video_dir(url: str) -> Path:
    """Directory holding every step's output for this video."""
    return OUTPUT_DIR / video_id_from_url(url)


def state_path(url: str) -> Path:
    """The single JSON file that every step reads from and appends its results to."""
    return video_dir(url) / "pipeline.json"


def load_state(url: str) -> PipelineState:
    path = state_path(url)
    if not path.exists():
        raise SystemExit(f"{path} not found. Run extract_video_data.py on this URL first.")
    return PipelineState.model_validate_json(path.read_text())


def save_state(url: str, state: PipelineState) -> Path:
    path = state_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2))
    return path
