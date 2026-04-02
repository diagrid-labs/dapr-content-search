"""Bluesky search via the AT Protocol public API."""

import asyncio
import logging
from datetime import date

import httpx

import config
from platforms import is_nsfw, only_dapr_in_youtube_id

logger = logging.getLogger(__name__)


def resolve_facet_links(text: str, facets: list[dict]) -> str:
    """Replace truncated URLs in text with full URIs from Bluesky facets.

    Bluesky stores the display text (often shortened) in the record text and
    the complete URIs in ``record.facets``.  Facet indices are byte-based, so
    we operate on the UTF-8 encoded bytes and decode back at the end.
    """
    if not facets:
        return text

    text_bytes = text.encode("utf-8")

    # Collect link facets with their byte ranges and full URIs
    link_facets: list[dict] = []
    for facet in facets:
        for feature in facet.get("features", []):
            if feature.get("$type") == "app.bsky.richtext.facet#link":
                index = facet.get("index", {})
                uri = feature.get("uri", "")
                if uri:
                    link_facets.append({
                        "start": index.get("byteStart", 0),
                        "end": index.get("byteEnd", 0),
                        "uri": uri,
                    })

    # Replace from the end so earlier byte offsets stay valid
    link_facets.sort(key=lambda f: f["start"], reverse=True)

    for lf in link_facets:
        text_bytes = (
            text_bytes[: lf["start"]]
            + lf["uri"].encode("utf-8")
            + text_bytes[lf["end"] :]
        )

    return text_bytes.decode("utf-8")


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
            if resp.status_code == 403:
                logger.warning("Bluesky returned 403 on page %d — likely rate limited. Returning %d results collected so far.", page + 1, len(results))
                break
            resp.raise_for_status()
            data = resp.json()

            for post in data.get("posts", []):
                record = post.get("record", {})
                author = post.get("author", {})
                raw_text = record.get("text", "")
                text = resolve_facet_links(raw_text, record.get("facets", []))

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
                is_reply = record.get("reply") is not None
                embed = post.get("embed", {})
                embed_type = embed.get("$type", "") if embed else ""
                if is_reply:
                    post_type = "Reply post"
                elif embed_type == "app.bsky.embed.external#view":
                    post_type = "Post with link"
                else:
                    post_type = "Post"

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

            # Delay between pages to avoid rate limiting
            await asyncio.sleep(1.0)

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
