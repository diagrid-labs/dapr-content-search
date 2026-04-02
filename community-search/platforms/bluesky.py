"""Bluesky search via the AT Protocol public API."""

import logging
from datetime import date

import httpx

import config
from platforms import is_nsfw, only_dapr_in_youtube_id

logger = logging.getLogger(__name__)


async def search_bluesky(
    keyword: str, since: date, until: date
) -> list[dict]:
    """Search Bluesky for a single keyword and return matching posts."""
    results: list[dict] = []
    cursor: str | None = None

    headers = {"User-Agent": "DaprCommunitySearch/0.1 (httpx)"}
    async with httpx.AsyncClient(headers=headers) as client:
        for page in range(config.BLUESKY_MAX_PAGES):
            params: dict = {
                "q": keyword,
                "limit": config.BLUESKY_PAGE_LIMIT,
                "since": f"{since.isoformat()}T00:00:00Z",
                "until": f"{until.isoformat()}T23:59:59Z",
                "lang": "en",
            }
            if cursor:
                params["cursor"] = cursor

            url = f"{config.BLUESKY_API_BASE}/{config.BLUESKY_SEARCH_ENDPOINT}"
            logger.debug("Bluesky request page %d: %s params=%s", page + 1, url, params)

            resp = await client.get(url, params=params, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()

            for post in data.get("posts", []):
                record = post.get("record", {})
                author = post.get("author", {})
                text = record.get("text", "")

                # Apply exclusion filter
                text_lower = text.lower()
                if any(ex.lower() in text_lower for ex in config.EXCLUSIONS.get("bluesky", [])):
                    continue

                # Filter out posts where "dapr" only appears in a YouTube video ID
                if only_dapr_in_youtube_id(text):
                    continue

                # Filter out adult content (text labels or Bluesky content labels)
                labels = [lbl.get("val", "") for lbl in post.get("labels", [])]
                if is_nsfw(text) or any(v in ("porn", "nsfw", "sexual") for v in labels):
                    continue

                # Parse date from createdAt
                created_at = record.get("createdAt", "")
                post_date = created_at[:10] if created_at else ""

                # Date filter
                if post_date and (post_date < since.isoformat() or post_date > until.isoformat()):
                    continue

                # Construct web URL from AT URI
                uri = post.get("uri", "")
                # AT URI format: at://did:plc:.../app.bsky.feed.post/<rkey>
                rkey = uri.rsplit("/", 1)[-1] if "/" in uri else ""
                handle = author.get("handle", "")
                post_url = f"https://bsky.app/profile/{handle}/post/{rkey}"

                display_name = author.get("displayName") or handle

                # Detect post type
                embed = post.get("embed", {})
                embed_type = embed.get("$type", "") if embed else ""
                post_type = (
                    "Post with link"
                    if embed_type == "app.bsky.embed.external#view"
                    else "Post"
                )

                results.append({
                    "date": post_date,
                    "author": f"{display_name} (@{handle})",
                    "text": text,
                    "url": post_url,
                    "type": post_type,
                    "platform": "bluesky",
                })

            # Check for next page
            cursor = data.get("cursor")
            if not cursor:
                break

    logger.debug("Bluesky keyword %r returned %d results", keyword, len(results))
    return results


async def run_bluesky(since: date, until: date) -> list[dict]:
    """Run Bluesky search for all configured keywords, deduplicate by URL."""
    all_results: list[dict] = []
    seen_urls: set[str] = set()

    for keyword in config.SEARCH_KEYWORDS:
        posts = await search_bluesky(keyword, since, until)
        for post in posts:
            if post["url"] not in seen_urls:
                seen_urls.add(post["url"])
                all_results.append(post)

    logger.info("Bluesky: %d unique results across all keywords", len(all_results))
    return all_results
