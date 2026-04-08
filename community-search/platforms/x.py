"""X (Twitter) query builder.

The Playwright-based scraper has been replaced by the x-mcp MCP server.
X search is now performed via MCP tool calls orchestrated by the
search-dapr-content skill. This module retains the query builder used
by the normalization script (x_mcp_normalize.py).
"""

from datetime import date

import config


def build_x_query(keyword: str, since: date, until: date) -> str:
    """Build the X advanced search query string."""
    parts = [keyword]

    if config.X_LANGUAGE_FILTER:
        parts.append(f"lang:{config.X_LANGUAGE_FILTER}")

    parts.append(f"since:{since.isoformat()}")
    parts.append(f"until:{until.isoformat()}")

    if config.X_EXCLUDE_RETWEETS:
        parts.append("-filter:retweets")

    for ex in config.EXCLUSIONS.get("x", []):
        parts.append(f"-{ex}")

    return " ".join(parts)
