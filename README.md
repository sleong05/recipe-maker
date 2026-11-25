# YouTube → Recipe Card: Pipeline Design

## Overview

The pipeline turns a YouTube cooking video URL into a one-page, US Letter recipe card PDF for a printed recipe book. Six Python steps run in order (`generate_recipe.py`); each step reads and extends one shared state file. Code handles fetching, checking and layout; an LLM handles judgement and writing.

## Workflow

```mermaid
flowchart TD
    URL([YouTube video URL]) --> S1
    S1["1. Fetch video data<br/>"] --> S2
    S2["2. Check it is a recipe<br/><small> extract recipe links</small>"]
    S2 -. not one dish or not a recipe .-> STOP([stop])
    S2 --> S3
    S3["3. Scrape recipe page<br/><small></small>"] --> S4
    S4["4. Extract recipe from collected text<br/><small></small>"] --> S5
    S5["5. Validate recipe<br/><small> </small>"] --> S6
    S5 -- "errors/issues → fixer,<br/>up to 2 rounds" --> S5
    S6["6. Render PDF<br/><small>Jinja2</small>"] --> PDF([One-page recipe card PDF])
    S6 -- "overflows at 8.5 pt →<br/>LLM condenses, up to 2x" --> S6

    classDef llm fill:#dbe8fb,stroke:#2f6fd6,stroke-width:2px,color:#111
    classDef stop fill:#fbe3e3,stroke:#c0392b,color:#111
    class S2,S4,S5,S6 llm
    class STOP stop
```

Shaded steps call the LLM through a chain of providers because I am cheap and don't want to pay for my LLM usage. 
Models go down all the time as well so this can help the system be a bit more robust. Future work will run a local LLM when
it won't fry my computer.

## Steps and decisions

| Step | What it does | 
| --- | --- | 
| 1. Fetch video data | yt-dlp pulls title, description and chapters; youtube-transcript-api pulls captions. |  
| 2. Check it's a recipe (LLM) | Gate: is this one dish? Picks recipe links from the description as well. | 
| 3. Scrape recipe page | requests + BeautifulSoup on each link to parse out the page  | 
| 4. Extract recipe (LLM) | Builds a structured recipe: ingredient groups, step groups, equipment, tips from the video data + recipe page if it exists. | 
| 5. Validate recipe (LLM) | Code checks by comparing ingredients, then llm validator finalizes the critics and sends back for another round of work. Up to 2 fix rounds. |
| 6. Render PDF | Jinja2 HTML template to WeasyPrint PDF, US Letter. LLM is used to check if its longer than 1 page and will attempt to shrink up to two times.| 
