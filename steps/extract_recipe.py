"""Step 4: Extract a structured recipe from the transcript, description and scraped page.

The written recipe page (when step 3 got one) is trusted for ingredients and amounts;
the transcript adds technique detail and tips. Amounts use the units the cook uses
in the video.

Usage:
    python steps/extract_recipe.py <youtube_url>
"""

import argparse
import sys

from common import load_state, save_state
from llm import complete
from models import PipelineState, Recipe

SYSTEM = (
    "You turn cooking videos into accurate, printable one-page recipe cards. "
    "Accuracy matters more than completeness: never invent an ingredient, amount, time or temperature."
)

PROMPT = """Write the recipe for "{dish}" using the sources below.

How to use the sources:
- WRITTEN RECIPE (if present) is the most reliable source for the ingredient list and amounts.
- TRANSCRIPT is what the cook says in the video. Use it for technique, visual cues ("until golden"),
  and tips. It may be auto-generated, so numbers in it can be misheard; prefer the written recipe when they disagree.
- DESCRIPTION sometimes contains the ingredient list itself.

Rules:
- Units: use the units the cook uses in the video. If the written recipe lists two systems,
  e.g. "3 cups (450g)", and the cook says grams, use "450" + "g". If the cook says both
  ("2 1/2 cups or 280 grams"), use the one they say first. Apply the same choice to every ingredient.
- If no source gives an amount, set quantity to null and describe it in note ("to taste", "a splash").
- If the cook uses a component from a separate recipe without giving its ingredients
  (e.g. "my vanilla buttercream, link above"), list it as one ingredient with no amount and
  note "see separate recipe". Never fill in ingredients or amounts from general cooking knowledge.
- Don't repeat the unit in the name or note: "1" + "clove" + "garlic", not "1 clove garlic clove".
- If the video shows several variations of the dish, write the recipe for the main or first version
  and mention the other variations briefly in a tip.
- Group ingredients and steps by component (e.g. "Cake", "Frosting") only when the recipe has distinct components.
  Every ingredient group should have a step group with the same name.
- Steps must be detailed enough to cook from without the video: include temperatures, times, pan sizes
  and doneness cues. Merge trivial actions; aim for about 6-14 steps in total. It must fit on one printed page.
- When a step uses an ingredient, repeat its amount exactly as written in the ingredient list
  ("Add 450 g all-purpose flour"), in the same units. Don't add conversions in parentheses.
- Equipment: list the tools and non-food supplies the cook uses or the recipe calls for (pans with sizes,
  bowls, mixer, thermometer, parchment paper, plastic wrap, piping bags...). Skip things every kitchen
  has: oven, stovetop, knife, cutting board, spoons, measuring cups. Include them only if a specific
  kind or size matters (e.g. "serrated knife", "12-inch oven-safe skillet").
- Leave out sponsor segments, jokes and storytelling.

{sources}"""

SOURCES = """=== WRITTEN RECIPE ({page_status}) ===
{page}

=== DESCRIPTION ===
{description}

=== TRANSCRIPT ({transcript_kind}) ===
{transcript}"""


def format_sources(state: PipelineState) -> str:
    """The written recipe, description and transcript as one block of prompt text."""
    video, scraped, transcript = state.video, state.scraped, state.video.transcript
    if transcript.is_generated is None:
        transcript_kind = "not available"
    else:
        transcript_kind = "auto-generated captions" if transcript.is_generated else "creator-provided captions"

    return SOURCES.format(
        page_status=f"from {scraped.url}" if scraped and scraped.text else "not available",
        page=scraped.text if scraped and scraped.text else "(none)",
        description=video.description or "(none)",
        transcript_kind=transcript_kind,
        transcript=transcript.text or "(none)",
    )


def extract_recipe(state: PipelineState) -> Recipe:
    prompt = PROMPT.format(
        dish=state.check.dish_name or state.video.title,
        sources=format_sources(state),
    )
    return complete(prompt, Recipe, system=SYSTEM)


def run(url: str) -> None:
    state = load_state(url)
    if state.check is None:
        sys.exit("No recipe check found. Run check_recipe.py on this URL first.")
    if not (state.check.is_recipe and state.check.single_dish):
        sys.exit("This video was rejected by check_recipe.py; nothing to extract.")
    if not state.video.transcript.text and not (state.scraped and state.scraped.text):
        print("Warning: no transcript or written recipe; extracting from the description only.")

    state.recipe = recipe = extract_recipe(state)
    out_path = save_state(url, state)

    n_ingredients = sum(len(g.items) for g in recipe.ingredient_groups)
    n_steps = sum(len(g.steps) for g in recipe.step_groups)
    print(f"{recipe.title}: {n_ingredients} ingredients, {n_steps} steps")
    print(f"Saved -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="YouTube video URL")
    run(parser.parse_args().url)


if __name__ == "__main__":
    main()
