---
name: search-dapr-content
description: Search X, LinkedIn, and Bluesky for Dapr community content using the community-search Python application.
user-invocable: true
---

# Search Dapr Content

Search social media platforms (X, LinkedIn, Bluesky) for Dapr-related community content. The app searches for keywords defined in `community-search/config.py` (e.g., `Dapr`, `Dapr Workflow`, `Dapr Agents`).

## How to Use

The user may provide:
- **Platform**: `x`, `linkedin`, `bluesky`, or `all`. Default: `all`.
- **Date range**: A `--since` and/or `--until` date. Default: last 30 days from today.
- **Output file**: A custom output path. Default: `community-search/YYYY-MM-DD-community-content.md`.
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

6. **Summarize the results**: Provide a brief overview of the content found (post count, platforms, notable authors or topics).
