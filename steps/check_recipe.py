"""Step 2: Decide whether a video is a single-dish recipe and find recipe links.

Reads the video data from the URL's pipeline.json and adds the verdict to it.
Exits with status 1 if the video should not continue through the pipeline.

Usage:
    python steps/check_recipe.py <youtube_url>
"""

import argparse
import re
import sys

from common import load_state, save_state
from llm import complete
from models import RecipeCheck, VideoData

# The opening of the transcript is enough to judge what the video is about.
TRANSCRIPT_WORDS = 500

URL = re.compile(r"https?://\S+")

SYSTEM = (
    "You classify YouTube cooking videos for a pipeline that turns a single recipe "
    "into a printable one-page recipe card."
)

PROMPT = """Decide whether this video teaches how to make a dish, and whether it covers exactly one dish.
Compilations or roundups of several different dishes are NOT single-dish, even if each is a real recipe.
One dish shown with a few variations (e.g. classic plus two regional twists) IS single-dish.
A main dish with its own sauce or side counts as one dish.

From the description, list the URLs that likely lead to the written recipe for this dish.
Only use URLs that appear in the description. Exclude social media, merch, sponsors and product links.

Title: {title}

Description:
{description}

Transcript (first {n} words):
{transcript}"""


def check_recipe(video: VideoData) -> RecipeCheck:
    words = (video.transcript.text or "").split()
    prompt = PROMPT.format(
        title=video.title,
        description=video.description or "(none)",
        n=TRANSCRIPT_WORDS,
        transcript=" ".join(words[:TRANSCRIPT_WORDS]) or "(no transcript available)",
    )
    check = complete(prompt, RecipeCheck, system=SYSTEM)

    # Guard against hallucinated links: keep only URLs that are really in the description.
    found = set(URL.findall(video.description))
    check.recipe_links = [link for link in check.recipe_links if link in found]
    return check


def run(url: str) -> None:
    state = load_state(url)
    state.check = check = check_recipe(state.video)
    out_path = save_state(url, state)

    passed = check.is_recipe and check.single_dish
    print(f"{'PASS' if passed else 'REJECT'}: {check.reason}")
    if check.dish_name:
        print(f"Dish: {check.dish_name}")
    for link in check.recipe_links:
        print(f"Recipe link: {link}")
    print(f"Saved -> {out_path}")
    if not passed:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="YouTube video URL")
    run(parser.parse_args().url)


if __name__ == "__main__":
    main()
