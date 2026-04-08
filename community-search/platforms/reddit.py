"""Reddit search via the public JSON API."""

import asyncio
import logging
from datetime import date, datetime, timezone

import httpx

import config
from platforms import has_dapr_keyword, is_nsfw, only_dapr_in_youtube_id

logger = logging.getLogger(__name__)

REDDIT_BASE_URL = "https://www.reddit.com"
USER_AGENT = "DaprCommunitySearch/0.1 (httpx; github.com/diagrid-labs/dapr-content-search)"


async def search_reddit_subreddit(
    subreddit: str, keyword: str, since: date, until: date
) -> list[dict]:
    """Search a single subreddit for a keyword and return matching posts."""
    results: list[dict] = []
    after: str | None = None

    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(headers=headers) as client:
        for page in range(config.REDDIT_MAX_PAGES):
            params: dict = {
                "q": keyword,
                "restrict_sr": "1",
                "sort": "new",
                "t": "all",
                "limit": config.REDDIT_PAGE_LIMIT,
                "raw_json": "1",
            }
            if after:
                params["after"] = after

            url = f"{REDDIT_BASE_URL}/r/{subreddit}/search.json"
            logger.debug(
                "Reddit request r/%s page %d: %s params=%s",
                subreddit, page + 1, url, params,
            )

            resp = await client.get(url, params=params, timeout=30.0)
            if resp.status_code in (403, 429):
                logger.warning(
                    "Reddit returned %d on page %d for r/%s — likely rate limited. "
                    "Returning %d results collected so far.",
                    resp.status_code, page + 1, subreddit, len(results),
                )
                break
            resp.raise_for_status()
            data = resp.json()

            children = data.get("data", {}).get("children", [])
            if not children:
                break

            for child in children:
                if child.get("kind") != "t3":
                    continue

                post_data = child.get("data", {})

                # Convert epoch to date
                created_utc = post_data.get("created_utc", 0)
                post_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                post_date = post_dt.date()
                post_date_str = post_dt.strftime("%Y-%m-%d")

                # Date filter
                if post_date < since or post_date > until:
                    continue

                # NSFW filter via Reddit's flag
                if post_data.get("over_18", False):
                    continue

                # Build text from title + selftext
                title = post_data.get("title", "")
                selftext = post_data.get("selftext", "")
                if selftext in ("[removed]", "[deleted]"):
                    selftext = ""
                text = f"{title}\n\n{selftext}".strip() if selftext else title

                # Apply exclusion filter
                text_lower = text.lower()
                if any(ex.lower() in text_lower for ex in config.EXCLUSIONS.get("reddit", [])):
                    continue

                # Filter out posts where "dapr" is not a standalone keyword
                if not has_dapr_keyword(text):
                    continue

                # Filter out posts where "dapr" only appears in a YouTube video ID
                if only_dapr_in_youtube_id(text):
                    continue

                # NSFW text filter
                if is_nsfw(text):
                    continue

                # Build post URL
                permalink = post_data.get("permalink", "")
                post_url = f"{REDDIT_BASE_URL}{permalink}" if permalink else ""

                # Author
                author = post_data.get("author", "[deleted]")
                subreddit_prefixed = post_data.get("subreddit_name_prefixed", f"r/{subreddit}")

                # Post type and quoted URL
                is_self = post_data.get("is_self", True)
                if is_self:
                    post_type = "Post"
                    quoted_url = ""
                else:
                    post_type = "Post with link"
                    quoted_url = post_data.get("url", "")

                results.append({
                    "date": post_date_str,
                    "author": f"u/{author} ({subreddit_prefixed})",
                    "text": text,
                    "url": post_url,
                    "quoted_url": quoted_url,
                    "type": post_type,
                    "platform": "reddit",
                })

            # Check for next page
            after = data.get("data", {}).get("after")
            if not after:
                break

            # Delay between pages to avoid rate limiting
            await asyncio.sleep(1.0)

    logger.debug(
        "Reddit r/%s keyword %r returned %d results",
        subreddit, keyword, len(results),
    )
    return results


async def run_reddit(since: date, until: date) -> list[dict]:
    """Run Reddit search across all configured subreddits and keywords, deduplicate by URL."""
    tasks = [
        search_reddit_subreddit(sub, kw, since, until)
        for sub in config.REDDIT_SUBREDDITS
        for kw in config.SEARCH_KEYWORDS
    ]
    batches = await asyncio.gather(*tasks)

    all_results: list[dict] = []
    seen_urls: set[str] = set()
    for posts in batches:
        for post in posts:
            if post["url"] not in seen_urls:
                seen_urls.add(post["url"])
                all_results.append(post)

    logger.info("Reddit: %d unique results across all subreddits/keywords", len(all_results))
    return all_results
