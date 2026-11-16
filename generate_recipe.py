"""Generate a one-page printable recipe PDF from a YouTube cooking video.

Usage:
    python generate_recipe.py <youtube_url>

Each step reads and updates output/<video_id>/pipeline.json; the PDF is saved
next to it as recipe.pdf. Stops at the first step that fails or rejects the video.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "steps"))

import check_recipe
import extract_recipe
import extract_video_data
import render_recipe
import scrape_recipe
import validate_recipe
from common import video_dir

STEPS = [
    ("Fetch video data", extract_video_data),
    ("Check it's a recipe", check_recipe),
    ("Scrape recipe page", scrape_recipe),
    ("Extract recipe", extract_recipe),
    ("Validate recipe", validate_recipe),
    ("Render PDF", render_recipe),
]


def generate_recipe(url: str) -> None:
    start = time.time()
    for number, (label, step) in enumerate(STEPS, 1):
        print(f"\n[{number}/{len(STEPS)}] {label}")
        try:
            step.run(url)
        except SystemExit as e:
            # Steps exit with a message or status 1 when they fail or reject the video.
            if e.code not in (None, 0):
                if isinstance(e.code, str):
                    print(e.code)
                sys.exit(f"\nStopped at step {number} ({label}).")
    print(f"\nDone in {time.time() - start:.0f}s -> {video_dir(url) / 'recipe.pdf'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="YouTube video URL")
    generate_recipe(parser.parse_args().url)


if __name__ == "__main__":
    main()
