#!/usr/bin/env python3
"""Normalize raw x-mcp search_twitter output into the standard report format.

Also provides a --build-query mode to print the X advanced search query string.

Usage:
    # Build query string for a keyword and date range
    uv run python platforms/x_mcp_normalize.py --build-query --keyword Dapr \\
        --since 2026-03-01 --until 2026-04-01

    # Normalize raw x-mcp JSON output
    uv run python platforms/x_mcp_normalize.py \\
        --input /tmp/x_mcp_raw.json \\
        --output reports/2026-04-08-x-community-content.json \\
        --since 2026-03-01 --until 2026-04-01
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import date

from dateutil.parser import parse as parse_date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from platforms import has_dapr_keyword, is_nsfw, only_dapr_in_youtube_id
from platforms.x import build_x_query

logger = logging.getLogger(__name__)


def _extract_date(raw: dict) -> str:
    """Extract and normalize post date from various possible field names."""
    for field in ("created_at", "timestamp", "date", "time"):
        value = raw.get(field)
        if value:
            try:
                if isinstance(value, (int, float)):
                    from datetime import datetime, timezone
                    dt = datetime.fromtimestamp(value, tz=timezone.utc)
                    return dt.strftime("%Y-%m-%d")
                return parse_date(str(value)).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue
    return ""


def _extract_author(raw: dict) -> str:
    """Extract author display name and handle from various possible fields."""
    display_name = (
        raw.get("name", "")
        or raw.get("display_name", "")
        or raw.get("author_name", "")
        or ""
    )
    handle = (
        raw.get("username", "")
        or raw.get("screen_name", "")
        or raw.get("handle", "")
        or raw.get("author_handle", "")
        or ""
    )

    # Try to extract handle from the URL if not found in fields
    if not handle:
        url = raw.get("url", "")
        match = re.match(r"https?://(?:x\.com|twitter\.com)/([^/]+)/status/", url)
        if match:
            handle = match.group(1)

    if handle and not handle.startswith("@"):
        handle = f"@{handle}"

    if display_name and handle:
        return f"{display_name} ({handle})"
    return display_name or handle or ""


def _detect_type(raw: dict, text: str) -> str:
    """Detect post type from available fields."""
    if raw.get("in_reply_to") or raw.get("in_reply_to_status_id"):
        return "Reply post"
    if raw.get("quoted_tweet") or raw.get("quoted_status"):
        return "Quote tweet"
    if re.search(r"https?://", text):
        return "Post with link"
    return "Post"


def _extract_quoted_url(raw: dict) -> str:
    """Extract quoted tweet URL if present."""
    qt = raw.get("quoted_tweet") or raw.get("quoted_status")
    if isinstance(qt, dict):
        return qt.get("url", "")
    return ""


def normalize_post(raw: dict, since: str, until: str) -> dict | None:
    """Normalize a single x-mcp post into the standard schema.

    Returns None if the post should be filtered out.
    """
    text = raw.get("text", "") or raw.get("full_text", "") or ""
    url = raw.get("url", "") or ""
    post_date = _extract_date(raw)

    # Date filter
    if post_date and (post_date < since or post_date > until):
        return None

    # Keyword filter
    if not has_dapr_keyword(text):
        return None

    # YouTube video ID filter
    if only_dapr_in_youtube_id(text):
        return None

    # NSFW filter
    if is_nsfw(text):
        return None

    # Exclusion keywords
    text_lower = text.lower()
    for ex in config.EXCLUSIONS.get("x", []):
        if ex.lower() in text_lower:
            return None

    return {
        "date": post_date,
        "author": _extract_author(raw),
        "text": text,
        "url": url,
        "quoted_url": _extract_quoted_url(raw),
        "type": _detect_type(raw, text),
        "platform": "x",
        "sentiment": "",
        "relevancy_score": "",
    }


def normalize_all(
    raw_posts: list[dict], since: str, until: str
) -> list[dict]:
    """Normalize and filter a list of raw x-mcp posts."""
    results: list[dict] = []
    seen_urls: set[str] = set()

    for i, raw in enumerate(raw_posts):
        # Log first post structure for schema discovery
        if i == 0:
            logger.info("First raw post fields: %s", list(raw.keys()))

        post = normalize_post(raw, since, until)
        if post is None:
            continue

        # Deduplicate by URL
        dedup_key = post["url"] if post["url"] else f"{post['author']}:{post['text'][:200]}"
        if dedup_key in seen_urls:
            continue
        seen_urls.add(dedup_key)

        results.append(post)

    # Sort by date descending
    results.sort(key=lambda r: r["date"], reverse=True)

    logger.info("Normalized %d posts from %d raw results", len(results), len(raw_posts))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize x-mcp output or build X search queries."
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--build-query", action="store_true",
        help="Print the X advanced search query string and exit",
    )
    mode.add_argument(
        "--input", type=str,
        help="Path to raw x-mcp JSON file to normalize",
    )

    parser.add_argument("--output", type=str, help="Output JSON file path")
    parser.add_argument("--keyword", type=str, default=None, help="Search keyword (for --build-query)")
    parser.add_argument("--since", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--until", type=str, required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    since = parse_date(args.since).date()
    until = parse_date(args.until).date()

    if args.build_query:
        keywords = [args.keyword] if args.keyword else config.SEARCH_KEYWORDS
        for kw in keywords:
            print(build_x_query(kw, since, until))
        return

    # Normalize mode
    if not args.output:
        parser.error("--output is required when normalizing")

    with open(args.input, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Handle both array of posts and x-mcp response wrapper
    if isinstance(raw_data, dict):
        raw_posts = raw_data.get("data", {}).get("posts", [])
        if not raw_posts:
            raw_posts = raw_data.get("posts", [])
        if not raw_posts:
            raw_posts = raw_data.get("data", [])
    elif isinstance(raw_data, list):
        raw_posts = raw_data
    else:
        logger.error("Unexpected JSON structure: %s", type(raw_data))
        sys.exit(1)

    results = normalize_all(raw_posts, args.since, args.until)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Normalized output written to {args.output} ({len(results)} posts)")


if __name__ == "__main__":
    main()
