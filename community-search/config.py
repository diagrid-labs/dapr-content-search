# config.py

from datetime import date

# ---------------------------------------------------------------------------
# Date range
# ---------------------------------------------------------------------------
# Default values used when --since / --until are not supplied on the CLI.
SINCE_DATE: date = date(2026, 3, 1)
UNTIL_DATE: date = date(2026, 4, 1)

# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------
# Each entry becomes a separate search query; results are merged and
# deduplicated by URL.
SEARCH_KEYWORDS: list[str] = [
    "Dapr",
]

# ---------------------------------------------------------------------------
# Per-platform exclusion keywords
# ---------------------------------------------------------------------------
# X supports native query negation (e.g. -gamer). For LinkedIn and Bluesky,
# exclusions are applied as a post-processing filter on the result text.
EXCLUSIONS: dict[str, list[str]] = {
    "x": ["gamer", "gaming", "stream", "twitch"],
    "linkedin": ["gamer", "gaming", "stream", "twitch"],
    "bluesky": ["gamer", "gaming", "stream", "twitch"],
    "reddit": ["gamer", "gaming", "stream", "twitch"],
}

# ---------------------------------------------------------------------------
# Platform-specific settings
# ---------------------------------------------------------------------------

X_LANGUAGE_FILTER: str = "en"          # appended as lang:en to every X query
X_EXCLUDE_RETWEETS: bool = True        # if True, append -filter:retweets

# X MCP settings (x-mcp server replaces Playwright browser scraping)
X_MCP_MAX_PAGES: int = 5              # max pagination calls (100 posts per page)
X_MCP_PRODUCT: str = "Latest"         # "Top" or "Latest" sort order

LINKEDIN_MAX_SCROLL_ATTEMPTS: int = 10
LINKEDIN_SCROLL_PAUSE_SECONDS: float = 3.0

BLUESKY_API_BASE: str = "https://api.bsky.app/xrpc"
BLUESKY_SEARCH_ENDPOINT: str = "app.bsky.feed.searchPosts"
BLUESKY_MAX_PAGES: int = 5             # maximum cursor-paginated pages to fetch
BLUESKY_PAGE_LIMIT: int = 25           # posts per page (API max is 25)

REDDIT_SUBREDDITS: list[str] = ["dotnet", "csharp", "dApr", "microservices"]
REDDIT_MAX_PAGES: int = 5             # maximum pages to fetch per subreddit per keyword
REDDIT_PAGE_LIMIT: int = 100          # posts per page (API max is 100)

# ---------------------------------------------------------------------------
# Auth state file paths
# ---------------------------------------------------------------------------
AUTH_DIR: str = "auth"
LINKEDIN_AUTH_STATE_FILE: str = f"{AUTH_DIR}/linkedin_state.json"
