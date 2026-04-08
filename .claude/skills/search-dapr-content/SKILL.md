---
name: search-dapr-content
description: Search X, LinkedIn, Bluesky, and Reddit for Dapr community content using the community-search Python application.
user-invocable: true
---

# Search Dapr Content

Search social media platforms (X, LinkedIn, Bluesky, Reddit) for Dapr-related community content. The app searches for keywords defined in `community-search/config.py` (e.g., `Dapr`, `Dapr Workflow`, `Dapr Agents`).

**False positive filtering**: The scrapers automatically reject posts where "dapr" only appears as a substring inside another word (e.g., the French word "d'apr&egrave;s"). The `has_dapr_keyword()` function in `platforms/__init__.py` enforces that "dapr" must appear as a standalone keyword, not surrounded by letters or apostrophes.

## How to Use

The user may provide:
- **Platform**: `x`, `linkedin`, `bluesky`, `reddit`, or `all`. Default: `all`.
- **Date range**: A `--since` and/or `--until` date. Default: last 30 days from today.
- **Output file**: A custom output path. Default: `reports/YYYY-MM-DD-community-content.md` (in the repo root).
- **Authentication**: The user may ask to authenticate for X or LinkedIn. This requires an interactive browser and must be run by the user themselves.

**Important platform notes:**
- **Bluesky** uses a public API and works immediately — no setup or authentication needed.
- **Reddit** uses the public JSON API and works immediately — no setup or authentication needed. Searches r/dotnet and r/csharp subreddits (configurable in `config.py`).
- **X** uses the x-mcp MCP server (requires `TWITTER_USERNAME` and `TWITTER_PASSWORD` environment variables set before launching Claude Code, and Node.js/npm installed for npx).
- **LinkedIn** requires browser-based authentication and Playwright browser binaries.

## Prerequisites

Before the first run, ensure:
1. `uv` is installed on the system.
2. The virtual environment and dependencies are set up (see First-Time Setup below).
3. For X: `TWITTER_USERNAME` and `TWITTER_PASSWORD` environment variables are set, and Node.js/npm is installed (for the x-mcp MCP server).
4. For LinkedIn: Playwright Chromium is installed and authentication is completed.

## First-Time Setup

Only run these steps if the `.venv` directory does not exist in `community-search/`:

```
cd community-search && uv venv && uv pip install -e .
```

For LinkedIn searches, also install the Playwright browser:

```
cd community-search && uv run playwright install chromium
```

Then authenticate by telling the user to run this command themselves (it requires an interactive browser that Claude cannot operate):

```
cd community-search && uv run python search.py --auth linkedin
```

For X searches, the x-mcp MCP server handles authentication automatically via environment variables. Ensure `TWITTER_USERNAME` and `TWITTER_PASSWORD` are set in the shell before launching Claude Code.

## Execution Steps

1. **Parse the user's request** to extract optional platform, date range, and output file preferences.

2. **Prepare the search parameters**:
   - Calculate `--since` and `--until` dates in `YYYY-MM-DD` format. If the user says something like "last 7 days", compute the dates relative to today.
   - Determine which platforms to search: `x`, `linkedin`, `bluesky`, or all three.
   - Always add `--verbose` for detailed logging.

3. **Check the environment**: If `.venv` does not exist in `community-search/`, run the First-Time Setup steps above.

4. **Run search + enrichment** — the approach depends on how many platforms are requested:

   ### Single platform (non-X)

   Run the search directly, then enrich in the main conversation:
   ```
   cd community-search && uv run python search.py --platform <name> --since YYYY-MM-DD --until YYYY-MM-DD --verbose
   ```
   Then proceed to step 5 (enrich), step 6 (merge — skipped for single platform), and step 7 (render).

   ### Single platform (X only)

   X search uses the x-mcp MCP server instead of the Python script. Run the search in the main conversation:

   1. **Build the search query** for each keyword in `config.py` (`SEARCH_KEYWORDS`):
      ```
      cd community-search && uv run python platforms/x_mcp_normalize.py --build-query --keyword Dapr --since YYYY-MM-DD --until YYYY-MM-DD
      ```

   2. **Call the `search_twitter` MCP tool** with:
      - `query`: the query string from step 1
      - `product`: "Latest"
      - `count`: 100

   3. **Paginate**: If the response includes a `cursor`, call `search_twitter` again with that cursor. Repeat until no cursor is returned or 5 total calls have been made.

   4. **Save raw results**: Collect all posts from all pages into a single JSON array and write it to `/tmp/x_mcp_raw.json`.

   5. **Normalize and filter**:
      ```
      cd community-search && uv run python platforms/x_mcp_normalize.py --input /tmp/x_mcp_raw.json --output reports/YYYY-MM-DD-x-community-content.json --since YYYY-MM-DD --until YYYY-MM-DD --verbose
      ```

   6. Proceed to step 5 (enrich), step 6 (merge — skipped for single platform), and step 7 (render).

   ### Multiple platforms (parallel pipeline)

   Launch one **Agent subagent per non-X platform in parallel** (use a single message with multiple Agent tool calls). Each subagent handles the full search-and-enrich pipeline for its platform independently, so fast platforms (e.g., Bluesky) complete without waiting for slower ones (e.g., LinkedIn).

   **For X**: Run the X search in the main conversation first (using the x-mcp MCP tool as described in "Single platform (X only)" steps 1-5 above), then launch an enrichment-only subagent for X in parallel with the other platform subagents.

   Each **non-X platform subagent** prompt should be:

   ```
   You are enriching Dapr community search results for the <PLATFORM> platform.

   1. Run the search:
      cd community-search && uv run python search.py --platform <PLATFORM> --since YYYY-MM-DD --until YYYY-MM-DD --verbose

   2. Check the output. The script writes a JSON file to the reports/ directory
      (e.g., reports/YYYY-MM-DD-<PLATFORM>-community-content.json).
      If the platform fails with a FileNotFoundError about missing auth state,
      or logs a warning about being redirected to /login, report the error and stop.

   3. Enrich the JSON file:
      - Read the platform JSON file.
      - For each post, determine three fields:
        - "sentiment": one of "positive", "neutral", or "negative" based on tone.
        - "relevancy_score": one of "high", "medium", or "low":
          - high: clearly about Dapr (distributed application runtime) or Dapr Agents (Python library for agentic AI).
          - medium: mentions Dapr in passing or discusses related distributed systems topics alongside Dapr.
          - low: not relevant to Dapr (slang, different topic, accidental keyword match).
        - "summary": one concise sentence summarizing the post (under 100 characters).

      **CRITICAL — Writing enrichment data back to JSON:**
      NEVER use the Write tool to write JSON files directly — post text often contains quotes,
      newlines, and special characters that will produce invalid JSON if not properly escaped.
      ALWAYS use the `enrich.py` helper script which uses `json.dump` for correct escaping.

      Write the enrichment array to a temporary JSON file first (this is safe because enrichment
      objects only contain short strings with no special characters), then pass it to `enrich.py`:

      ```
      cd community-search && uv run python enrich.py <json_path> --data-file /tmp/enrichments_<platform>.json
      ```

      The --data-file argument must point to a JSON file containing an array with one object per
      post (same order as the report file), each with only the three enrichment fields.

      If the file has more than 15 posts, use batched enrichment:
      - Split: cd community-search && uv run python batch_split.py <json_path> --batch-size 15
      - Launch one Agent subagent per batch in parallel to enrich each batch file.
      - Merge batches back: cd community-search && uv run python batch_merge.py --pattern "reports/<base>_batch_*.json" --output <json_path> --delete-batches

   4. Verify the enrichment by running:
      cd community-search && uv run python verify.py <json_path>
      Report the JSON file path and verification output when done.
   ```

   The **X enrichment-only subagent** prompt should be:

   ```
   You are enriching Dapr community search results for the X platform.
   The search has already been completed and the JSON file is at reports/YYYY-MM-DD-x-community-content.json.

   1. Read the JSON file and enrich each post with:
      - "sentiment": one of "positive", "neutral", or "negative" based on tone.
      - "relevancy_score": one of "high", "medium", or "low":
        - high: clearly about Dapr (distributed application runtime) or Dapr Agents (Python library for agentic AI).
        - medium: mentions Dapr in passing or discusses related distributed systems topics alongside Dapr.
        - low: not relevant to Dapr (slang, different topic, accidental keyword match).
      - "summary": one concise sentence summarizing the post (under 100 characters).

      **CRITICAL — Writing enrichment data back to JSON:**
      NEVER use the Write tool to write JSON files directly.
      ALWAYS use the `enrich.py` helper script:

      Write the enrichment array to /tmp/enrichments_x.json, then run:
      cd community-search && uv run python enrich.py <json_path> --data-file /tmp/enrichments_x.json

      If the file has more than 15 posts, use batched enrichment:
      - Split: cd community-search && uv run python batch_split.py <json_path> --batch-size 15
      - Launch one Agent subagent per batch in parallel to enrich each batch file.
      - Merge batches back: cd community-search && uv run python batch_merge.py --pattern "reports/<base>_batch_*.json" --output <json_path> --delete-batches

   2. Verify the enrichment by running:
      cd community-search && uv run python verify.py <json_path>
      Report the JSON file path and verification output when done.
   ```

   After all platform subagents complete, proceed to step 6 (merge) and step 7 (render).

5. **Enrich posts** (single-platform path only) — if you ran a single platform search directly in step 4 (not via subagent), enrich the JSON file now:

   **For 15 or fewer posts**: Enrich directly in the main conversation.
   - Read the platform JSON file.
   - For each post, determine `sentiment`, `relevancy_score`, and `summary` (see Enrichment Rules below).
   - **CRITICAL — Writing enrichment data back to JSON:**
     NEVER use the Write tool to write JSON files directly — post text often contains quotes,
     newlines, and special characters that will produce invalid JSON if not properly escaped.
     ALWAYS use the `enrich.py` helper script which uses `json.dump` for correct escaping.

     Write the enrichment array to a temporary JSON file first (this is safe because enrichment
     objects only contain short strings with no special characters), then pass it to `enrich.py`:
     ```
     cd community-search && uv run python enrich.py <json_path> --data-file /tmp/enrichments_<platform>.json
     ```
     The --data-file argument must point to a JSON file containing an array with one object per
     post (same order as the report file), each with only the three enrichment fields.

   **For more than 15 posts**: Use **batched parallel enrichment with subagents**.
   - Split posts into batches using `batch_split.py`:
     ```
     cd community-search && uv run python batch_split.py <platform_json_file_path> --batch-size 15
     ```
   - Launch one **Agent** subagent per batch **in parallel**. Each subagent prompt should be:

     ```
     Read the JSON file at <batch_file_path>. For each post in the array, determine three fields:
     - "sentiment": one of "positive", "neutral", or "negative" based on the post text tone.
     - "relevancy_score": one of "high", "medium", or "low":
       - high: clearly about Dapr (distributed application runtime) or Dapr Agents (Python library for agentic AI).
       - medium: mentions Dapr in passing or discusses related distributed systems topics alongside Dapr.
       - low: not relevant to Dapr (slang, different topic, accidental keyword match).
     - "summary": one concise sentence summarizing the post (under 100 characters).

     CRITICAL: NEVER use the Write tool to write JSON files with post text — it contains quotes and
     special characters that will produce invalid JSON. Instead, write the enrichment array (which
     only contains short safe strings) to a temp file, then use the enrich.py helper:
     Write enrichments to /tmp/enrichments_batch_N.json, then run:
     cd community-search && uv run python enrich.py <batch_file_path> --data-file /tmp/enrichments_batch_N.json
     ```

   - After all subagents complete, merge batch files back:
     ```
     cd community-search && uv run python batch_merge.py --pattern "reports/<platform_base>_batch_*.json" --output <platform_json_file_path> --delete-batches
     ```

6. **Merge platform JSON files** (multi-platform only) into a single combined JSON file using `batch_merge.py`. Do **not** delete the individual platform JSON files:
   ```
   cd community-search && uv run python batch_merge.py <platform_json_1> <platform_json_2> <platform_json_3> --output reports/YYYY-MM-DD-community-content.json
   ```
   Note: Do NOT use `--delete-batches` — the individual platform JSON files must be preserved.

   Check the subagent results for auth errors:
   - If X search failed (e.g., x-mcp returned an error), inform the user to check their `TWITTER_USERNAME` and `TWITTER_PASSWORD` environment variables.
   - If LinkedIn failed due to missing auth state or expired session, inform the user to authenticate by running:
   ```
   ! cd community-search && uv run python search.py --auth linkedin
   ```

7. **Render the final report** using `render.py`:
   - For multi-platform: use the merged JSON file from step 6.
   - For single-platform: use the enriched platform JSON file directly.
   ```
   cd community-search && uv run python render.py <json_file_path> --output reports/YYYY-MM-DD-community-content.md --since YYYY-MM-DD --until YYYY-MM-DD
   ```
   This script handles all mechanical post-processing:
   - Generates a **platform statistics table** as the first item in the report, showing the number of posts per platform with a breakdown by relevancy score (high, medium, low) and totals
   - Reorders posts by relevancy score (high first, then medium, then low; date descending within each tier)
   - Generates the summary table with internal anchor links
   - Writes the final Markdown file containing data from all platforms

   The statistics table can also be generated standalone using `stats.py`:
   ```
   cd community-search && uv run python stats.py <json_file_path>
   ```

8. **Verify the final output** using `verify.py`:
   ```
   cd community-search && uv run python verify.py <final_json_file_path>
   ```
   This checks that all posts have been enriched and prints a summary.

9. **Summarize the results**: Provide a brief overview of the content found (post count, platforms, notable authors or topics, relevancy score distribution).

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

[x|linkedin|bluesky|reddit]

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
