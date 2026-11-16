"""Pydantic data types passed between pipeline steps."""

from typing import Literal

from pydantic import BaseModel, Field


# Step 1: extract_video_data

class Transcript(BaseModel):
    language: str | None = None
    is_generated: bool | None = None
    text: str | None = None
    error: str | None = None  # Set when no captions could be fetched.


class Chapter(BaseModel):
    title: str | None = None
    start: float | None = None


class VideoData(BaseModel):
    id: str
    title: str
    description: str = ""
    webpage_url: str
    language: str | None = None
    chapters: list[Chapter] = []
    transcript: Transcript


# Step 2: check_recipe

class RecipeCheck(BaseModel):
    is_recipe: bool = Field(description="True if the video teaches how to cook or bake a dish.")
    single_dish: bool = Field(
        description="True if the video covers one dish, including one dish shown with a few variations. "
        "False for compilations of different dishes like '5 easy dinners'."
    )
    dish_name: str | None = Field(description="Name of the dish, or null if not a recipe.")
    recipe_links: list[str] = Field(
        description="URLs from the description that likely lead to the written recipe for this dish. "
        "Exclude social media, merch, sponsors and affiliate/product links."
    )
    reason: str = Field(description="One sentence explaining the decision.")


# Step 3: scrape_recipe

class ScrapedPage(BaseModel):
    url: str
    # json-ld: structured recipe data found; text: visible page text;
    # blocked: site refused automated access; error: fetch failed for another reason.
    status: Literal["json-ld", "text", "blocked", "error"]
    text: str | None = None
    error: str | None = None


# Step 4: extract_recipe

class Ingredient(BaseModel):
    quantity: str | None = Field(
        description="Amount as written, e.g. '450', '1 1/2', '3/4'. Null if the sources give no amount."
    )
    unit: str | None = Field(description="Unit, e.g. 'g', 'cups', 'tbsp'. Null for countable items like '2 eggs'.")
    name: str = Field(description="Ingredient name only, e.g. 'all-purpose flour'. Never repeat the unit here.")
    note: str | None = Field(
        description="Prep or qualifier, e.g. 'cold, cubed', 'optional', 'to taste', 'a splash'. "
        "Never repeat the quantity or unit here; a can or package size is fine, e.g. '28 oz / 800 g'."
    )


class IngredientGroup(BaseModel):
    name: str | None = Field(description="Component name like 'Sauce' or 'Topping'; null if only one group.")
    items: list[Ingredient]


class StepGroup(BaseModel):
    name: str | None = Field(description="Component name matching an ingredient group; null if only one group.")
    steps: list[str] = Field(description="Ordered instructions, one action per step, imperative voice.")


class Recipe(BaseModel):
    title: str
    summary: str = Field(description="One short sentence describing the dish, for under the title.")
    servings: str | None = Field(description="e.g. '12 biscuits' or '4 servings'.")
    prep_time: str | None = Field(description="Human-readable, e.g. '20 min'.")
    cook_time: str | None = Field(description="Human-readable, e.g. '1 hr 15 min'.")
    ingredient_groups: list[IngredientGroup]
    equipment: list[str] = Field(
        description="Tools and non-food supplies needed, with sizes where given, e.g. "
        "'Two 8-inch round cake pans', 'Stand mixer', 'Parchment paper'."
    )
    step_groups: list[StepGroup]
    tips: list[str] = Field(description="Up to 3 short, genuinely useful tips from the cook. Empty if none.")


# Step 5: validate_recipe

class Issue(BaseModel):
    severity: Literal["error", "warning"] = Field(
        description="error: wrong or missing information that would mislead the cook. "
        "warning: minor wording or style problem."
    )
    location: str = Field(description="Where the problem is, e.g. 'ingredient: garlic' or 'Cake step 3'.")
    problem: str
    fix: str = Field(description="The specific correction to make.")


class Critique(BaseModel):
    issues: list[Issue] = Field(description="Every real problem found. Empty if the recipe is correct.")


class Validation(BaseModel):
    approved: bool          # True if no errors remain after the fix loop
    rounds: int             # How many critique rounds ran
    fixed: list[Issue]      # Errors that were sent back for fixing
    remaining: list[Issue]  # Issues still present in the final recipe


# Step 6: render_recipe

class Render(BaseModel):
    pdf: str              # Path to the printable PDF
    pages: int            # 1 unless the recipe couldn't be made to fit
    font_size: float      # Base font size (pt) the page was rendered at
    condense_rounds: int  # How many times the LLM had to shorten the recipe to fit


# Pipeline state: one file per video, each step fills in its own section.

class PipelineState(BaseModel):
    video: VideoData                     # step 1
    check: RecipeCheck | None = None      # step 2
    scraped: ScrapedPage | None = None    # step 3 (None if the description had no recipe links)
    recipe: Recipe | None = None          # step 4 (step 5 replaces it with the corrected version)
    validation: Validation | None = None  # step 5
    render: Render | None = None          # step 6
