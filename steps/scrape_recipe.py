"""Step 3: Fetch the written recipe from the links found in step 2.

Tries each link in order and keeps the first page that yields recipe text.
Prefers schema.org Recipe data (JSON-LD) when the page has it, otherwise falls back
to the page's visible text. Sites that block automated access are skipped, not
worked around; extraction then relies on the transcript and description.
No LLM call is made here.

Usage:
    python steps/scrape_recipe.py <youtube_url>
"""

import argparse
import html
import json
import sys

import requests
from bs4 import BeautifulSoup

from common import load_state, save_state
from models import ScrapedPage

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 20

# Long blog posts can bury the recipe in thousands of words; cap what step 4 receives.
MAX_WORDS = 3000

BLOCKED_STATUSES = {401, 403, 429, 503}
# Bot-check / challenge pages that come back with a normal-looking response.
BLOCKED_MARKERS = ("Just a moment...", "cf-chl", "Enable JavaScript and cookies to continue")

NON_CONTENT_TAGS = ["script", "style", "noscript", "svg", "iframe", "nav", "header", "footer", "aside", "form"]


def find_recipe_jsonld(node):
    """Search parsed JSON-LD (which may nest lists and @graph) for a Recipe object."""
    if isinstance(node, list):
        for item in node:
            if found := find_recipe_jsonld(item):
                return found
    elif isinstance(node, dict):
        types = node.get("@type")
        if "Recipe" in (types if isinstance(types, list) else [types]):
            return node
        if "@graph" in node:
            return find_recipe_jsonld(node["@graph"])
    return None


def instructions_to_lines(instructions) -> list[str]:
    """Flatten recipeInstructions, which may be strings, HowToSteps or HowToSections."""
    if isinstance(instructions, str):
        return [instructions]
    lines = []
    for item in instructions or []:
        if isinstance(item, str):
            lines.append(item)
        elif item.get("@type") == "HowToSection":
            lines.append(f"{item.get('name', '')}:")
            lines += instructions_to_lines(item.get("itemListElement"))
        elif item.get("text"):
            lines.append(item["text"])
    return lines


def jsonld_to_text(recipe: dict) -> str:
    """Render a schema.org Recipe as plain text for the extraction step."""
    parts = [recipe.get("name", "")]
    for key in ("recipeYield", "prepTime", "cookTime", "totalTime"):
        if recipe.get(key):
            parts.append(f"{key}: {recipe[key]}")
    parts.append("Ingredients:")
    parts += recipe.get("recipeIngredient", [])
    parts.append("Instructions:")
    parts += instructions_to_lines(recipe.get("recipeInstructions"))
    # JSON-LD strings often still contain HTML entities like &quot;
    return "\n".join(html.unescape(str(p)).strip() for p in parts if p)


def page_text(soup: BeautifulSoup) -> str:
    for tag in soup(NON_CONTENT_TAGS):
        tag.decompose()
    words = soup.get_text(" ").split()
    return " ".join(words[:MAX_WORDS])


def scrape(url: str) -> ScrapedPage:
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as e:
        return ScrapedPage(url=url, status="error", error=f"{type(e).__name__}: {e}")

    if response.status_code in BLOCKED_STATUSES or any(m in response.text for m in BLOCKED_MARKERS):
        return ScrapedPage(url=url, status="blocked", error=f"HTTP {response.status_code}")
    if not response.ok:
        return ScrapedPage(url=url, status="error", error=f"HTTP {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            recipe = find_recipe_jsonld(json.loads(script.string or ""))
        except json.JSONDecodeError:
            continue
        # Some sites ship a Recipe block with no ingredients; that's no better than page text.
        if recipe and recipe.get("recipeIngredient"):
            return ScrapedPage(url=response.url, status="json-ld", text=jsonld_to_text(recipe))

    text = page_text(soup)
    if not text:
        return ScrapedPage(url=response.url, status="error", error="Page had no visible text")
    return ScrapedPage(url=response.url, status="text", text=text)


def run(url: str) -> None:
    state = load_state(url)
    if state.check is None:
        sys.exit("No recipe check found. Run check_recipe.py on this URL first.")

    state.scraped = None
    for link in state.check.recipe_links:
        page = scrape(link)
        print(f"{page.status.upper()}: {link}" + (f" ({page.error})" if page.error else ""))
        state.scraped = page
        if page.text:
            break

    if not state.check.recipe_links:
        print("No recipe links in the description; extraction will use the transcript only.")
    elif state.scraped.text:
        print(f"Got {len(state.scraped.text.split())} words of recipe text")
    else:
        print("Could not get recipe text; extraction will use the transcript only.")

    print(f"Saved -> {save_state(url, state)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="YouTube video URL")
    run(parser.parse_args().url)


if __name__ == "__main__":
    main()
