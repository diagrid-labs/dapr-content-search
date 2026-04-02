# Dapr Community Content Search

A Claude Code skill that searches X, LinkedIn, and Bluesky for Dapr community content, enriches posts with sentiment and relevancy scores, and renders a Markdown report.

## How it works

The skill is defined in `.claude/skills/search-dapr-content/SKILL.md` and is invoked from Claude Code using the `/search-dapr-content` slash command. It orchestrates the Python application in `community-search/` to:

1. **Search** social media platforms for posts matching keywords defined in `community-search/config.py` (e.g., `Dapr`, `Dapr Workflow`, `Dapr Agents`).
2. **Enrich** each post with a sentiment (`positive`, `neutral`, `negative`), a relevancy score (`high`, `medium`, `low`), and a one-line summary.
3. **Render** a sorted Markdown report with a summary table and anchor-linked post details.

Output is written to the `reports/` directory as both JSON and Markdown files.

## Supported platforms

| Platform | Method | Auth required |
|----------|--------|---------------|
| Bluesky | Public API | No |
| X | Playwright browser scraping | Yes |
| LinkedIn | Playwright browser scraping | Yes |

## Prerequisites

- [uv](https://github.com/astral-sh/uv) for Python dependency management
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI

## First-time setup

```bash
cd community-search && uv venv && uv pip install -e .
```

For X or LinkedIn, install the Playwright browser and authenticate:

```bash
cd community-search && uv run playwright install chromium
cd community-search && uv run python search.py --auth x
cd community-search && uv run python search.py --auth linkedin
```

## Usage

From Claude Code, run the skill:

```
/search-dapr-content
```

You can specify a platform, date range, or output path:

- "Search Bluesky for the last 7 days"
- "Search all platforms since 2026-03-01 until 2026-03-31"

### Running the scripts directly

**Search:**

```bash
cd community-search && uv run python search.py --all --since 2026-03-01 --until 2026-03-31 --verbose
cd community-search && uv run python search.py --platform bluesky --since 2026-03-01 --until 2026-03-31 --verbose
```

**Render:**

```bash
cd community-search && uv run python render.py ../reports/YYYY-MM-DD-community-content.json --output ../reports/YYYY-MM-DD-community-content.md
```

## Project structure

```
community-search/
  config.py       # Keywords, date ranges, platform settings
  search.py       # CLI entry point for searching platforms
  render.py       # Renders enriched JSON into a Markdown report
  platforms/      # Per-platform scraper modules
reports/          # Generated JSON and Markdown output
```
