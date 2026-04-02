---
name: search-dapr-content
description: Search X, LinkedIn, and Bluesky for Dapr community content using the community-search Python application.
user-invocable: true
---

# Search Dapr Content

Search social media platforms (X, LinkedIn, Bluesky) for Dapr-related community content. The app searches for keywords defined in `community-search/config.py` (e.g., `Dapr`, `Dapr Workflow`, `Dapr Agents`).

**False positive filtering**: The scrapers automatically reject posts where "dapr" only appears as a substring inside another word (e.g., the French word "d'après"). The `has_dapr_keyword()` function in `platforms/__init__.py` enforces that "dapr" must appear as a standalone keyword, not surrounded by letters or apostrophes.

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
   - If the script reports results written to a file, read that file and present a summary to the user (number of posts found, platforms covered, date range).
   - Note: results are **appended** to the output file. Running the same search twice will produce duplicates.
   - If a platform fails with a `FileNotFoundError` about missing auth state, inform the user they need to authenticate first by running the commands themselves (use `!` prefix):
     ```
     ! cd community-search && uv run python search.py --auth x
     ! cd community-search && uv run python search.py --auth linkedin
     ```
   - If a platform logs a warning about being redirected to `/login`, the session has expired. The user needs to re-authenticate using the auth commands above.
   - If no results are found, inform the user.

6. **Analyze and enrich each post**: After the markdown file is written, read it and process every post. For each post, add two new subsections (after the `### URL` section):

   - **`### Sentiment`**: Analyze the post text and assign one of: `positive`, `neutral`, or `negative`.
   - **`### Relevancy Score`**: Assess how relevant the post is to Dapr and assign one of these values:
     - **high**: The post is clearly about **Dapr** (the distributed application runtime) or **Dapr Agents** (the Python library for building agentic AI applications).
     - **medium**: The post is somewhat relevant to Dapr (mentions Dapr in passing, discusses related distributed systems topics alongside Dapr, or is tangentially connected).
     - **low**: The post is not relevant to Dapr at all (e.g., uses "dapr" as slang, is about a different topic entirely, or matched the search keywords by accident).

   The final format for each post should be (where Type is one of `Post`, `Post with link`, `Article share`, or `Reply post`):
   ```
   ## YYYY-MM-DD — [Type]

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

7. **Reorder posts by relevancy**: Sort all posts by their Relevancy Score in descending order (high first, then medium, then low). Within the same relevancy, keep the original date-descending order. Rewrite the markdown file with the reordered posts, preserving the `# Dapr Community Content` header and horizontal rule separators between posts.

8. **Add a summary table**: After reordering, insert a summary table immediately after the `# Dapr Community Content — ...` heading and before the first post. The table provides a quick overview of all posts with internal links to jump to the full content.

   For each post, generate a GitHub-flavored Markdown anchor from the `## YYYY-MM-DD — [Type]` heading. The anchor is created by lowercasing, replacing spaces with `-`, and removing special characters (e.g., `## 2026-03-31 — Post with link` → `#2026-03-31--post-with-link`). If there are duplicate headings, append `-1`, `-2`, etc. to subsequent duplicates (matching GFM behavior).

   The table format:

   ```
   | # | Platform | Author | Summary | Sentiment | Relevancy Score | Link |
   |---|----------|--------|---------|-----------|-----------------|------|
   | 1 | bluesky | Author Name | One sentence summary of the post content | positive | high | [View](#2026-03-31--post-with-link) |
   | 2 | x | Author Name | One sentence summary of the post content | neutral | medium | [View](#2026-03-30--reply-post) |
   ```

   Rules for the table:
   - **#**: Sequential number starting at 1.
   - **Platform**: The platform name as it appears in the post's `### Platform` section (`x`, `linkedin`, or `bluesky`).
   - **Author**: The author name (without the handle/platform identifier in parentheses).
   - **Summary**: A single concise sentence summarizing what the post is about. Keep it under 100 characters.
   - **Sentiment**: The sentiment value already assigned to the post.
   - **Relevancy Score**: The relevancy score value already assigned to the post (`high`, `medium`, or `low`).
   - **Link**: An internal markdown link `[View](#anchor)` pointing to the post's heading anchor.

9. **Summarize the results**: Provide a brief overview of the content found (post count, platforms, notable authors or topics, relevancy score distribution).
