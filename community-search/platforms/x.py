"""X (Twitter) scraper using Playwright."""

import logging
import os
from datetime import date
from urllib.parse import quote

from playwright.async_api import Playwright, async_playwright

import config
from platforms import is_nsfw, only_dapr_in_youtube_id

logger = logging.getLogger(__name__)


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


async def scrape_x(
    keyword: str, since: date, until: date, pw: Playwright
) -> list[dict]:
    """Scrape X search results for a single keyword."""
    state_path = config.X_AUTH_STATE_FILE
    if not os.path.exists(state_path):
        raise FileNotFoundError(
            f"X auth state not found at '{state_path}'. "
            f"Run: uv run search.py --auth x"
        )

    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(storage_state=state_path)
    page = await context.new_page()

    results: list[dict] = []
    try:
        query = build_x_query(keyword, since, until)
        url = f"https://x.com/search?q={quote(query)}&src=typed_query&f=live"
        logger.debug("X navigating to: %s", url)

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Detect login redirect — session may have expired
        if "/login" in page.url:
            logger.warning(
                "Session expired for X. Re-run: uv run search.py --auth x"
            )
            return []

        # Wait for tweet articles to appear
        try:
            await page.wait_for_selector(
                'article[data-testid="tweet"]', timeout=15000
            )
        except Exception:
            logger.info("No tweets found for keyword %r on X", keyword)
            return []

        # Scroll loop to load more results
        for attempt in range(config.X_MAX_SCROLL_ATTEMPTS):
            count_before = await page.locator('article[data-testid="tweet"]').count()
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(int(config.X_SCROLL_PAUSE_SECONDS * 1000))
            count_after = await page.locator('article[data-testid="tweet"]').count()
            logger.debug("X scroll %d: %d -> %d tweets", attempt + 1, count_before, count_after)
            if count_after == count_before:
                break

        # Extract data from each tweet article
        articles = page.locator('article[data-testid="tweet"]')
        count = await articles.count()
        for i in range(count):
            article = articles.nth(i)
            try:
                # Author display name: first span inside User-Name testid
                name_el = article.locator('[data-testid="User-Name"] span').first
                display_name = await name_el.inner_text() if await name_el.count() else ""

                # Author handle: link starting with /
                handle_el = article.locator('[data-testid="User-Name"] a[href^="/"]').first
                handle_href = await handle_el.get_attribute("href") if await handle_el.count() else ""
                handle = f"@{handle_href.strip('/')}" if handle_href else ""

                # Tweet text — resolve truncated display URLs to full links
                text_el = article.locator('[data-testid="tweetText"]').first
                if await text_el.count():
                    text = await text_el.evaluate("""el => {
                        let result = '';
                        for (const node of el.childNodes) {
                            if (node.nodeType === 3) {
                                result += node.textContent;
                            } else if (node.tagName === 'A') {
                                result += node.getAttribute('title') || node.getAttribute('href') || node.textContent;
                            } else if (node.tagName === 'IMG') {
                                result += node.getAttribute('alt') || '';
                            } else {
                                // Recurse into spans and other containers
                                const links = node.querySelectorAll('a');
                                if (links.length > 0) {
                                    let inner = '';
                                    for (const child of node.childNodes) {
                                        if (child.nodeType === 3) {
                                            inner += child.textContent;
                                        } else if (child.tagName === 'A') {
                                            inner += child.getAttribute('title') || child.getAttribute('href') || child.textContent;
                                        } else {
                                            inner += child.textContent || '';
                                        }
                                    }
                                    result += inner;
                                } else {
                                    result += node.textContent || '';
                                }
                            }
                        }
                        return result;
                    }""")
                else:
                    text = ""

                # Timestamp
                time_el = article.locator("time").first
                datetime_attr = await time_el.get_attribute("datetime") if await time_el.count() else ""
                post_date = datetime_attr[:10] if datetime_attr else ""

                # Tweet URL
                link_el = article.locator('a[href*="/status/"]').first
                link_href = await link_el.get_attribute("href") if await link_el.count() else ""
                tweet_url = f"https://x.com{link_href}" if link_href and link_href.startswith("/") else link_href

                # Type detection: check for reply and link card embed
                reply_count = await article.locator('[data-testid="socialContext"]').count()
                card_count = await article.locator('[data-testid="card.wrapper"]').count()
                if reply_count > 0:
                    post_type = "Reply post"
                elif card_count > 0:
                    post_type = "Post with link"
                else:
                    post_type = "Post"

                # Date filter
                if post_date and (post_date < since.isoformat() or post_date > until.isoformat()):
                    continue

                # Filter out posts where "dapr" only appears in a YouTube video ID
                if only_dapr_in_youtube_id(text):
                    continue

                # Filter out adult content
                if is_nsfw(text):
                    continue

                results.append({
                    "date": post_date,
                    "author": f"{display_name} ({handle})",
                    "text": text,
                    "url": tweet_url,
                    "type": post_type,
                    "platform": "x",
                })
            except Exception as exc:
                logger.debug("Failed to extract tweet %d: %s", i, exc)
                continue
    finally:
        await context.close()
        await browser.close()

    logger.debug("X keyword %r returned %d results", keyword, len(results))
    return results


async def run_x(since: date, until: date) -> list[dict]:
    """Run X search for all configured keywords, deduplicate by URL."""
    all_results: list[dict] = []
    seen_urls: set[str] = set()

    async with async_playwright() as pw:
        for keyword in config.SEARCH_KEYWORDS:
            posts = await scrape_x(keyword, since, until, pw)
            for post in posts:
                if post["url"] not in seen_urls:
                    seen_urls.add(post["url"])
                    all_results.append(post)

    logger.info("X: %d unique results across all keywords", len(all_results))
    return all_results
