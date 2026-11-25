"""Helpers shared by all steps: every step takes a YouTube URL and finds its files from it."""

import json
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


def slugify(title: str) -> str:
    """Folder-safe name from a video title: 'Shakshuka | Basics with Babish' -> 'shakshuka'."""
    title = title.split("|")[0]  # Drop channel names and keyword tails after a "|".
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower().replace("'", "")).strip("-")
    return slug[:60].rstrip("-") or "recipe"


def _find_video_dir(video_id: str) -> Path | None:
    """The existing folder whose pipeline.json belongs to this video, if any."""
    for path in OUTPUT_DIR.glob("*/pipeline.json"):
        try:
            if json.loads(path.read_text())["video"]["id"] == video_id:
                return path.parent
        except (json.JSONDecodeError, KeyError):
            continue
    return None


def _new_video_dir(state: PipelineState) -> Path:
    """Pick a folder named after the video title; add the video ID only if that name is taken."""
    path = OUTPUT_DIR / slugify(state.video.title)
    return path if not path.exists() else path.with_name(f"{path.name}-{state.video.id}")


def video_dir(url: str) -> Path:
    """Directory holding every step's output for this video (named after its title)."""
    video_id = video_id_from_url(url)
    path = _find_video_dir(video_id)
    if path is None:
        raise SystemExit(f"No output folder for video {video_id}. Run extract_video_data.py on this URL first.")
    return path


def state_path(url: str) -> Path:
    """The single JSON file that every step reads from and appends its results to."""
    return video_dir(url) / "pipeline.json"


def load_state(url: str) -> PipelineState:
    return PipelineState.model_validate_json(state_path(url).read_text())


def save_state(url: str, state: PipelineState) -> Path:
    folder = _find_video_dir(video_id_from_url(url)) or _new_video_dir(state)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "pipeline.json"
    path.write_text(state.model_dump_json(indent=2))
    return path
