"""Step 6: Render the recipe to a one-page US Letter PDF.

Fit-to-one-page loop (evaluator-optimizer, with the renderer as the evaluator):
  1. Render at each font size from largest to smallest and keep the largest that fits on one page.
  2. If even the smallest size overflows, ask the LLM to condense the recipe, then try again.
Gives up after MAX_CONDENSE_ROUNDS and saves the smallest-size render with a warning.

Usage:
    python steps/render_recipe.py <youtube_url>
"""

import argparse
import re
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from common import load_state, save_state, video_dir
from llm import complete
from models import Recipe, Render

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# "2 1/4" -> "2¼". Display only; the stored recipe keeps whatever the sources used.
FRACTION_GLYPHS = {"1/2": "½", "1/4": "¼", "3/4": "¾", "1/3": "⅓", "2/3": "⅔", "1/8": "⅛"}
FRACTION = re.compile(r"(?:(\d+)\s+)?\b(" + "|".join(FRACTION_GLYPHS) + r")\b")


def pretty_fractions(text: str) -> str:
    return FRACTION.sub(lambda m: (m.group(1) or "") + FRACTION_GLYPHS[m.group(2)], text)


_env = Environment(loader=FileSystemLoader(ASSETS), autoescape=True)
_env.filters["fractions"] = pretty_fractions
# Capitalize only the first letter, unlike Jinja's capitalize which lowercases the rest ("8-inch Pan").
_env.filters["sentence"] = lambda text: text[:1].upper() + text[1:]
TEMPLATE = _env.get_template("recipe.html.j2")

# Base font sizes (pt) to try, largest first, in quarter-point steps.
# Below 8.5pt gets hard to read at the stove.
FONT_SIZES = [12 - 0.25 * i for i in range(15)]
MAX_CONDENSE_ROUNDS = 2

CONDENSE_SYSTEM = "You edit recipe cards to fit on a single printed page without losing information a cook needs."

CONDENSE_PROMPT = """This recipe card runs onto {pages} pages even at the smallest font size. Shorten it to fit one page:
- Tighten wording and merge closely related steps.
- Shorten the summary and tips first; drop tips if needed.
- Never remove an ingredient, amount, temperature, time, pan size or doneness cue.
- Steps must keep repeating ingredient amounts exactly as written in the ingredient list.

=== RECIPE CARD ===
{recipe}"""


def render(recipe: Recipe, font_size: float, source: str):
    html = TEMPLATE.render(recipe=recipe, font_size=font_size, source=source)
    return HTML(string=html, base_url=str(ASSETS)).render()


def fit_to_page(recipe: Recipe, source: str):
    """Return (document, font_size) for the largest font that fits on one page, or None."""
    for font_size in FONT_SIZES:
        document = render(recipe, font_size, source)
        if len(document.pages) == 1:
            return document, font_size
    return None


def condense(recipe: Recipe, pages: int) -> Recipe:
    prompt = CONDENSE_PROMPT.format(pages=pages, recipe=recipe.model_dump_json(indent=2))
    return complete(prompt, Recipe, system=CONDENSE_SYSTEM)


def run(url: str) -> None:
    state = load_state(url)
    if state.recipe is None:
        sys.exit("No recipe found. Run extract_recipe.py on this URL first.")
    if state.validation and not state.validation.approved:
        print(f"Warning: rendering a recipe with {len(state.validation.remaining)} unresolved validation issue(s).")

    # Shown in the page footer; quotes would break the CSS string it's placed in.
    source = f"Source: {state.video.webpage_url}".replace('"', "")
    recipe = state.recipe
    condense_rounds = 0

    while (fitted := fit_to_page(recipe, source)) is None and condense_rounds < MAX_CONDENSE_ROUNDS:
        pages = len(render(recipe, FONT_SIZES[-1], source).pages)
        condense_rounds += 1
        print(f"Doesn't fit at {FONT_SIZES[-1]}pt ({pages} pages); condensing (round {condense_rounds})")
        recipe = condense(recipe, pages)

    if fitted:
        document, font_size = fitted
    else:
        font_size = FONT_SIZES[-1]
        document = render(recipe, font_size, source)
        print(f"Warning: still {len(document.pages)} pages after {condense_rounds} condense rounds.")

    folder = video_dir(url)
    pdf_path = folder / f"{folder.name}.pdf"
    document.write_pdf(pdf_path)

    # Keep the stored recipe in sync with what was printed.
    state.recipe = recipe
    state.render = Render(pdf=str(pdf_path), pages=len(document.pages),
                          font_size=font_size, condense_rounds=condense_rounds)
    save_state(url, state)

    print(f"Rendered {len(document.pages)} page(s) at {font_size}pt, {condense_rounds} condense round(s)")
    print(f"Saved -> {pdf_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="YouTube video URL")
    run(parser.parse_args().url)


if __name__ == "__main__":
    main()
