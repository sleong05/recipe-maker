"""Step 1: Fetch metadata, description and transcript for a YouTube video.

Uses yt-dlp and youtube-transcript-api (no API keys needed). No video is downloaded.

Usage:
    python steps/extract_video_data.py <youtube_url>
"""

import argparse
import re
import sys

from youtube_transcript_api import YouTubeTranscriptApi
from yt_dlp import YoutubeDL

from common import save_state
from models import Chapter, PipelineState, Transcript, VideoData

# Caption noise: sound tags like [music] / [Applause] and ">>" speaker-change markers.
CAPTION_NOISE = re.compile(r"\[[^\]]*\]|>>")


def clean_caption(text: str) -> str:
    return " ".join(CAPTION_NOISE.sub(" ", text).split())


def fetch_transcript(video_id: str, language: str | None) -> Transcript:
    """Return the caption text, preferring the video's own language and manual captions.

    Never raises: if no captions exist, `text` is None and `error` says why,
    so a later step can fall back to transcribing the audio.
    """
    languages = [language.split("-")[0]] if language else []
    languages += [lang for lang in ("en",) if lang not in languages]
    try:
        # find_transcript prefers manually created captions over auto-generated ones.
        transcript = YouTubeTranscriptApi().list(video_id).find_transcript(languages)
        fetched = transcript.fetch()
    except Exception as e:
        return Transcript(error=f"{type(e).__name__}: {str(e).splitlines()[0]}")

    lines = (clean_caption(s.text) for s in fetched.snippets)
    return Transcript(
        language=transcript.language_code,
        is_generated=transcript.is_generated,
        text=" ".join(line for line in lines if line),
    )


def extract_video_data(url: str) -> VideoData:
    """Return the video's metadata, description and transcript."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return VideoData(
        id=info["id"],
        title=(info.get("title") or "").strip(),
        description=(info.get("description") or "").strip(),
        webpage_url=info["webpage_url"],
        language=info.get("language"),
        # Chapters often map 1:1 to recipe steps, so keep them when present.
        chapters=[
            Chapter(title=c.get("title"), start=c.get("start_time"))
            for c in (info.get("chapters") or [])
        ],
        transcript=fetch_transcript(info["id"], info.get("language")),
    )


def run(url: str) -> None:
    try:
        video = extract_video_data(url)
    except Exception as e:
        sys.exit(f"Failed to fetch video data: {e}")

    # Step 1 starts a fresh state, discarding results from any earlier run.
    out_path = save_state(url, PipelineState(video=video))

    t = video.transcript
    print(video.title)
    if t.text:
        kind = "auto-generated" if t.is_generated else "manual"
        print(f"Transcript: {len(t.text.split())} words ({t.language}, {kind})")
    else:
        print(f"Transcript: none ({t.error})")
    print(f"Saved -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="YouTube video URL")
    run(parser.parse_args().url)


if __name__ == "__main__":
    main()
