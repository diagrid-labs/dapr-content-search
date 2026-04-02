---
name: search-dapr-content
description: Search X, LinkedIn, and Bluesky for Dapr community content using the community-search Python application.
user-invocable: true
---

# Search Dapr Content

Search social media platforms (X, LinkedIn, Bluesky) for Dapr-related community content. The app searches for keywords defined in `community-search/config.py` (e.g., `Dapr`, `Dapr Workflow`, `Dapr Agents`).

**False positive filtering**: The scrapers automatically reject posts where "dapr" only appears as a substring inside another word (e.g., the French word "d'apr&egrave;s"). The `has_dapr_keyword()` function in `platforms/__init__.py` enforces that "dapr" must appear as a standalone keyword, not surrounded by letters or apostrophes.

## How to Use

The user may provide:
- **Platform**: `x`, `linkedin`, `bluesky`, or `all`. Default: `all`.
- **Date range**: A `--since` and/or `--until` date. Default: last 30 days from today.
- **Output file**: A custom output path. Default: `reports/YYYY-MM-DD-community-content.md` (in the repo root).
- **Authentication**: The user may ask to authenticate for X or LinkedIn. This requires an interactive browser and must be run by the user themselves.

**Important platform notes:**
- **Bluesky** uses a public API and works immediately — no setup or authentication needed.
- **X and LinkedIn** require browser-based authentication and Playwright browser binaries.

## Prerequisites

Before the first run, ensure:
1. `uv` is installed on the system.
2. The virtual environment and dependencies are set up (see First-Time Setup below).
3. For X or LinkedIn: Playwright Chromium is installed and authentication is completed.

## First-Time Setup

Only run these steps if the `.venv` directory does not exist in `community-search/`:

```
cd community-search && uv venv && uv pip install -e .
```

For X or LinkedIn searches, also install the Playwright browser:

```
cd community-search && uv run playwright install chromium
```

Then authenticate by telling the user to run these commands themselves (they require an interactive browser that Claude cannot operate):

```
cd community-search && uv run python search.py --auth x
cd community-search && uv run python search.py --auth linkedin
```

## Execution Steps

1. **Parse the user's request** to extract optional platform, date range, and output file preferences.

2. **Build the command** using the `community-search/search.py` CLI:
   - The CLI requires one of `--all` or `--platform <name>` — there is no default.
   - Use `--all` if the user wants all platforms, or `--platform <name>` for a specific one.
   - Calculate `--since` and `--until` dates in `YYYY-MM-DD` format. If the user says something like "last 7 days", compute the dates relative to today.
   - Add `--output <path>` if the user specified one.
   - Always add `--verbose` for detailed logging.

3. **Check the environment**: If `.venv` does not exist in `community-search/`, run the First-Time Setup steps above.

4. **Run the search** using `uv run` from the `community-search/` directory:
   ```
   cd community-search && uv run python search.py --all --since YYYY-MM-DD --until YYYY-MM-DD --verbose
   ```
   Or for a specific platform:
   ```
   cd community-search && uv run python search.py --platform bluesky --since YYYY-MM-DD --until YYYY-MM-DD --verbose
   ```

5. **Check the output**:
   - The script writes two files: a Markdown file and a **JSON file** (same name, `.json` extension). The JSON file contains the structured results for enrichment.
   - If the script reports results written to a file, note the JSON file path for the next step.
   - Note: Markdown results are **appended** to the output file. Running the same search twice will produce duplicates. The JSON file is overwritten each time.
   - If a platform fails with a `FileNotFoundError` about missing auth state, inform the user they need to authenticate first by running the commands themselves (use `!` prefix):
     ```
     ! cd community-search && uv run python search.py --auth x
     ! cd community-search && uv run python search.py --auth linkedin
     ```
   - If a platform logs a warning about being redirected to `/login`, the session has expired. The user needs to re-authenticate using the auth commands above.
   - If no results are found, inform the user.

6. **Enrich posts via JSON** — read the JSON file and determine the enrichment strategy based on result count:

   **For 15 or fewer posts** (small set): Enrich directly in the main conversation.
   - Read the JSON file.
   - For each post, determine `sentiment` and `relevancy_score` (see Enrichment Rules below).
   - Add a `summary` field (one concise sentence, under 100 characters).
   - Write the enriched JSON back to the same file.

   **For more than 15 posts** (large set): Use **batched parallel enrichment with subagents**.
   - Read the JSON file to get the total post count.
   - Split posts into batches of up to 15 posts each.
   - For each batch, write a temporary JSON file: `reports/<base>_batch_N.json`
   - Launch one **Agent** subagent per batch **in parallel** (use a single message with multiple Agent tool calls). Each subagent prompt should be:

     ```
     Read the JSON file at <batch_file_path>. For each post in the array, fill in three fields:
     - "sentiment": one of "positive", "neutral", or "negative" based on the post text tone.
     - "relevancy_score": one of "high", "medium", or "low":
       - high: clearly about Dapr (distributed application runtime) or Dapr Agents (Python library for agentic AI).
       - medium: mentions Dapr in passing or discusses related distributed systems topics alongside Dapr.
       - low: not relevant to Dapr (slang, different topic, accidental keyword match).
     - "summary": one concise sentence summarizing the post (under 100 characters).
     Write the enriched array back to the same file path. Do not change any other fields.
     ```

   - After all subagents complete, read and merge all batch files into one array, preserving original order.
   - Write the merged enriched JSON back to the original JSON file path.
   - Delete the temporary batch files.

7. **Render the final report** using `render.py`:
   ```
   cd community-search && uv run python render.py <json_file_path> --output <markdown_file_path> --since YYYY-MM-DD --until YYYY-MM-DD
   ```
   This script handles all mechanical post-processing:
   - Reorders posts by relevancy score (high first, then medium, then low; date descending within each tier)
   - Generates the summary table with internal anchor links
   - Writes the final Markdown file

8. **Summarize the results**: Provide a brief overview of the content found (post count, platforms, notable authors or topics, relevancy score distribution).

## Enrichment Rules

For each post, assign:

- **`sentiment`**: Analyze the post text and assign one of: `positive`, `neutral`, or `negative`.
- **`relevancy_score`**: Assess how relevant the post is to Dapr:
  - **high**: The post is clearly about **Dapr** (the distributed application runtime) or **Dapr Agents** (the Python library for building agentic AI applications).
  - **medium**: The post is somewhat relevant to Dapr (mentions Dapr in passing, discusses related distributed systems topics alongside Dapr, or is tangentially connected).
  - **low**: The post is not relevant to Dapr at all (e.g., uses "dapr" as slang, is about a different topic entirely, or matched the search keywords by accident).
- **`summary`**: A single concise sentence summarizing the post content (under 100 characters).

## Post Format Reference

The final Markdown format for each post (produced by `render.py`) is:

```
## YYYY-MM-DD — [Author] — [Type]

### Platform

[x|linkedin|bluesky]

### Author

[author]

### Post

[text]

### URL

[url]

### Sentiment

[positive|neutral|negative]

### Relevancy Score

[high|medium|low]
```

Including the author name in the `##` heading ensures each heading is unique, which makes GFM anchor links reliable without needing duplicate-suffix logic (`-1`, `-2`, etc.).
