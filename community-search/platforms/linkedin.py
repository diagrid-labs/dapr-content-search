"""LinkedIn scraper using Playwright."""

import logging
import os
import re
from datetime import date, timedelta, datetime
from urllib.parse import quote

from playwright.async_api import Playwright, async_playwright

import config
from platforms import is_nsfw, only_dapr_in_youtube_id

logger = logging.getLogger(__name__)


def parse_relative_time(text: str) -> str:
    """Convert LinkedIn relative timestamps to YYYY-MM-DD dates.

    Examples: '3d ago' -> date, '1w ago' -> date, '2mo ago' -> date
    Also handles: '3 days ago', '1 week ago', '2 months ago'
    """
    today = date.today()
    text = text.strip().lower()

    # Match patterns like '3d', '1w', '2mo', or longer forms
    match = re.search(r"(\d+)\s*(d|w|mo|day|week|month)", text)
    if not match:
        return today.isoformat()

    value = int(match.group(1))
    unit = match.group(2)

    if unit in ("d", "day"):
        result = today - timedelta(days=value)
    elif unit in ("w", "week"):
        result = today - timedelta(weeks=value)
    elif unit in ("mo", "month"):
        result = today - timedelta(days=value * 30)
    else:
        result = today

    return result.isoformat()


def build_linkedin_url(keyword: str, since: date) -> str:
    """Build the LinkedIn content search URL."""
    encoded = quote(keyword)
    return (
        f"https://www.linkedin.com/search/results/content/"
        f"?keywords={encoded}&datePosted=past-month&sortBy=date_posted"
    )


async def scrape_linkedin(
    keyword: str, since: date, until: date, pw: Playwright
) -> list[dict]:
    """Scrape LinkedIn search results for a single keyword."""
    state_path = config.LINKEDIN_AUTH_STATE_FILE
    if not os.path.exists(state_path):
        raise FileNotFoundError(
            f"LinkedIn auth state not found at '{state_path}'. "
            f"Run: uv run search.py --auth linkedin"
        )

    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(storage_state=state_path)
    page = await context.new_page()

    results: list[dict] = []
    try:
        url = build_linkedin_url(keyword, since)
        logger.debug("LinkedIn navigating to: %s", url)

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Detect login redirect — session may have expired
        if "/login" in page.url:
            logger.warning(
                "Session expired for LinkedIn. Re-run: uv run search.py --auth linkedin"
            )
            return []

        # Wait for search results to appear
        result_selector = "li.reusable-search__result-container, div[data-chameleon-result-urn]"
        try:
            await page.wait_for_selector(result_selector, timeout=15000)
        except Exception:
            logger.info("No results found for keyword %r on LinkedIn", keyword)
            return []

        # If since is older than 30 days, try to adjust the date filter via UI
        days_ago = (date.today() - since).days
        if days_ago > 30:
            logger.debug("Since date is >30 days ago, attempting UI date filter")
            try:
                # Click "All filters" button
                all_filters = page.locator("button:has-text('All filters')").first
                if await all_filters.count() > 0:
                    await all_filters.click()
                    await page.wait_for_timeout(2000)
                    # Try to select a broader date range option
                    past_year = page.locator("label:has-text('Past year')").first
                    if await past_year.count() > 0:
                        await past_year.click()
                        # Apply filter
                        apply_btn = page.locator("button:has-text('Show results')").first
                        if await apply_btn.count() > 0:
                            await apply_btn.click()
                            await page.wait_for_timeout(3000)
            except Exception as exc:
                logger.debug("Could not adjust LinkedIn date filter: %s", exc)

        # Scroll loop to load more results
        for attempt in range(config.LINKEDIN_MAX_SCROLL_ATTEMPTS):
            count_before = await page.locator(result_selector).count()
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(int(config.LINKEDIN_SCROLL_PAUSE_SECONDS * 1000))
            count_after = await page.locator(result_selector).count()
            logger.debug("LinkedIn scroll %d: %d -> %d results", attempt + 1, count_before, count_after)
            if count_after == count_before:
                break

        # Extract data from each result
        items = page.locator(result_selector)
        count = await items.count()
        for i in range(count):
            item = items.nth(i)
            try:
                # Author name
                name_el = item.locator(".update-components-actor__name").first
                author_name = await name_el.inner_text() if await name_el.count() else "Unknown"
                author_name = author_name.strip()

                # Post text (truncated)
                text_el = item.locator(".update-components-text").first
                text = await text_el.inner_text() if await text_el.count() else ""
                text = text.strip()

                # Timestamp (relative)
                time_el = item.locator(".update-components-actor__sub-description").first
                time_text = await time_el.inner_text() if await time_el.count() else ""
                post_date = parse_relative_time(time_text)

                # Post URL — extract activity URN link
                link_el = item.locator('a.app-aware-link[href*="/feed/update/"]').first
                post_url = ""
                if await link_el.count() > 0:
                    post_url = await link_el.get_attribute("href") or ""
                    # Clean tracking params
                    if "?" in post_url:
                        post_url = post_url.split("?")[0]

                # Type detection
                article_count = await item.locator(".update-components-article").count()
                post_type = "Article share" if article_count > 0 else "Post"

                # Exclusion filter
                text_lower = text.lower()
                if any(ex.lower() in text_lower for ex in config.EXCLUSIONS.get("linkedin", [])):
                    continue

                # Date filter
                if post_date < since.isoformat() or post_date > until.isoformat():
                    continue

                # Filter out posts where "dapr" only appears in a YouTube video ID
                if only_dapr_in_youtube_id(text):
                    continue

                # Filter out adult content
                if is_nsfw(text):
                    continue

                results.append({
                    "date": post_date,
                    "author": author_name,
                    "text": text,
                    "url": post_url,
                    "type": post_type,
                    "platform": "linkedin",
                })
            except Exception as exc:
                logger.debug("Failed to extract LinkedIn result %d: %s", i, exc)
                continue
    finally:
        await context.close()
        await browser.close()

    logger.debug("LinkedIn keyword %r returned %d results", keyword, len(results))
    return results


async def run_linkedin(since: date, until: date) -> list[dict]:
    """Run LinkedIn search for all configured keywords, deduplicate by URL."""
    all_results: list[dict] = []
    seen_urls: set[str] = set()

    async with async_playwright() as pw:
        for keyword in config.SEARCH_KEYWORDS:
            posts = await scrape_linkedin(keyword, since, until, pw)
            for post in posts:
                if post["url"] and post["url"] not in seen_urls:
                    seen_urls.add(post["url"])
                    all_results.append(post)

    logger.info("LinkedIn: %d unique results across all keywords", len(all_results))
    return all_results
