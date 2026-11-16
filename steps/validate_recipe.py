"""Step 5: Check the extracted recipe against its sources and fix errors (evaluator-optimizer).

Each round:
  1. Code checks flag likely problems (ingredients never used in a step, amounts in
     steps that don't match the ingredient list, groups without matching steps).
  2. An LLM critic compares the recipe to the sources, using the code flags as hints,
     and reports issues as errors or warnings.
  3. If there are errors, an LLM fixer rewrites the recipe to correct them.
Stops when no errors remain or after MAX_FIX_ROUNDS fixes.

Usage:
    python steps/validate_recipe.py <youtube_url>
"""

import argparse
import re
import sys

from common import load_state, save_state
from extract_recipe import format_sources
from llm import complete
from models import Critique, Issue, PipelineState, Recipe, Validation

MAX_FIX_ROUNDS = 2

# Measured units that must match the ingredient list when they appear in a step.
UNITS = r"g|kg|mg|ml|l|cups?|tbsp|tsp|oz|lbs?|pounds?|ounces?|grams?|tablespoons?|teaspoons?"
AMOUNT = re.compile(rf"(\d[\d\s/.,½¼¾⅓⅔⅛]*)\s*({UNITS})\b", re.IGNORECASE)

# Words too generic to show an ingredient was used ("all-purpose flour" -> check "flour").
GENERIC = {"fresh", "large", "small", "medium", "ground", "unsalted", "salted", "purpose", "granulated",
           "extract", "powder", "fine", "sharp", "cold", "warm", "chopped", "whole", "optional"}

CRITIC_SYSTEM = "You are a meticulous recipe editor checking a recipe card against its source material."

CRITIC_PROMPT = """Check this recipe card against the sources. Report only real problems:
- An ingredient, amount, unit, temperature or time that is wrong, missing, or not supported by the sources.
- An amount with a missing unit (e.g. "1 garlic" should be "1 clove garlic").
- A unit repeated in the ingredient name or note (e.g. unit "clove" with name "garlic clove").
- An ingredient used in a step but missing from the ingredient list, or listed but never used.
- A step whose amount doesn't match the ingredient list.
- Steps out of order, or a step a cook couldn't follow without watching the video.
Do not report style preferences. If the sources don't say something, the recipe shouldn't either.
Never ask for information the sources don't contain: a missing amount the sources never give is
correct as "to taste" / no quantity, and a component from a separate recipe the cook only links to
is correct as a single ingredient noted "see separate recipe".

Automated checks flagged these possible problems. Some may be false alarms; confirm each against the recipe:
{hints}

=== RECIPE CARD ===
{recipe}

{sources}"""

FIXER_SYSTEM = "You correct recipe cards. Change only what is needed to fix the listed issues."

FIXER_PROMPT = """Fix these issues in the recipe card. Keep everything else exactly the same.
Steps must keep repeating ingredient amounts exactly as written in the ingredient list.
Only use information stated in the sources. If fixing an issue would require an ingredient or amount
the sources don't give, leave that part unchanged rather than guessing.

Issues:
{issues}

=== RECIPE CARD ===
{recipe}

{sources}"""


FRACTIONS = {"½": "1/2", "¼": "1/4", "¾": "3/4", "⅓": "1/3", "⅔": "2/3", "⅛": "1/8"}


def normalize_amount(quantity: str, unit: str) -> str:
    """'2¼ tsp', '2 ¼ tsp' and '2 1/4 tsp' all become '2 1/4 tsp'."""
    for symbol, fraction in FRACTIONS.items():
        quantity = quantity.replace(symbol, f" {fraction}")
    return f"{' '.join(quantity.split())} {unit}".lower()


def stem(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def code_checks(recipe: Recipe) -> list[str]:
    """Cheap deterministic checks; results are hints for the critic, not final verdicts."""
    hints = []
    step_text = " ".join(step for group in recipe.step_groups for step in group.steps).lower()
    step_words = {stem(w) for w in re.findall(r"[a-z]+", step_text)}

    listed_amounts = set()
    for group in recipe.ingredient_groups:
        for item in group.items:
            if item.quantity and item.unit:
                listed_amounts.add(normalize_amount(item.quantity, item.unit))
            if item.unit:
                unit = stem(item.unit.lower())
                repeated_in = [label for label, text in (("name", item.name), ("note", item.note or ""))
                               if unit in {stem(w) for w in re.findall(r"[a-z]+", text.lower())}]
                if repeated_in:
                    hints.append(f"Ingredient '{item.name}' repeats its unit '{item.unit}' in the "
                                 f"{' and '.join(repeated_in)}.")
            words = [stem(w) for w in re.findall(r"[a-z]+", item.name.lower())]
            keywords = [w for w in words if len(w) > 2 and w not in GENERIC] or words
            if not any(w in step_words for w in keywords):
                hints.append(f"Ingredient '{item.name}' doesn't seem to be used in any step.")

    for quantity, unit in AMOUNT.findall(step_text):
        amount = normalize_amount(quantity, unit)
        if amount not in listed_amounts:
            hints.append(f"A step mentions '{amount}', which isn't an amount in the ingredient list.")

    ingredient_names = {g.name for g in recipe.ingredient_groups if g.name}
    step_names = {g.name for g in recipe.step_groups if g.name}
    for name in ingredient_names - step_names:
        hints.append(f"Ingredient group '{name}' has no step group with the same name.")

    if not recipe.ingredient_groups or not any(g.items for g in recipe.ingredient_groups):
        hints.append("The recipe has no ingredients.")
    if not any(g.steps for g in recipe.step_groups):
        hints.append("The recipe has no steps.")
    return hints


def critique(recipe: Recipe, sources: str) -> list[Issue]:
    hints = code_checks(recipe)
    prompt = CRITIC_PROMPT.format(
        hints="\n".join(f"- {h}" for h in hints) or "(none)",
        recipe=recipe.model_dump_json(indent=2),
        sources=sources,
    )
    return complete(prompt, Critique, system=CRITIC_SYSTEM).issues


def fix(recipe: Recipe, issues: list[Issue], sources: str) -> Recipe:
    prompt = FIXER_PROMPT.format(
        issues="\n".join(f"- [{i.location}] {i.problem} Fix: {i.fix}" for i in issues),
        recipe=recipe.model_dump_json(indent=2),
        sources=sources,
    )
    return complete(prompt, Recipe, system=FIXER_SYSTEM)


def validate_recipe(state: PipelineState) -> tuple[Recipe, Validation]:
    sources = format_sources(state)
    recipe, fixed = state.recipe, []

    for round_number in range(1, MAX_FIX_ROUNDS + 2):
        issues = critique(recipe, sources)
        errors = [i for i in issues if i.severity == "error"]
        print(f"Round {round_number}: {len(errors)} errors, {len(issues) - len(errors)} warnings")
        for issue in issues:
            print(f"  {issue.severity.upper()} [{issue.location}] {issue.problem}")
        if not errors or round_number > MAX_FIX_ROUNDS:
            break
        fixed += errors
        recipe = fix(recipe, errors, sources)

    validation = Validation(approved=not errors, rounds=round_number, fixed=fixed, remaining=issues)
    return recipe, validation


def run(url: str) -> None:
    state = load_state(url)
    if state.recipe is None:
        sys.exit("No recipe found. Run extract_recipe.py on this URL first.")

    state.recipe, state.validation = validate_recipe(state)
    out_path = save_state(url, state)

    v = state.validation
    print(f"{'APPROVED' if v.approved else 'NOT APPROVED'} after {v.rounds} round(s), {len(v.fixed)} errors fixed")
    print(f"Saved -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="YouTube video URL")
    run(parser.parse_args().url)


if __name__ == "__main__":
    main()
