"""LinkedIn scraper: Playwright for rendering, BeautifulSoup for parsing."""

import asyncio
import json
import logging
import os
import re
from datetime import date, timedelta
from urllib.parse import quote

from bs4 import BeautifulSoup, NavigableString
from playwright.async_api import Playwright, async_playwright

import config
from platforms import has_dapr_keyword, is_nsfw, only_dapr_in_youtube_id

logger = logging.getLogger(__name__)

# Directory for temporary HTML captures (inside community-search/)
TMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tmp")


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


def build_linkedin_url(keyword: str, since: date, sort_by: str = "date_posted") -> str:
    """Build the LinkedIn content search URL.

    Args:
        sort_by: "date_posted" for recent posts, "" (empty) for Top Match / relevance.
    """
    encoded = quote(keyword)
    url = (
        f"https://www.linkedin.com/search/results/content/"
        f"?keywords={encoded}&datePosted=past-month"
    )
    if sort_by:
        url += f"&sortBy={sort_by}"
    return url


async def _find_result_selector(page) -> str | None:
    """Try multiple selectors to find LinkedIn search result items."""
    selectors = [
        '[data-testid="lazy-column"] div[role="listitem"]',
        'div.search-results-container div[role="listitem"]',
        'div.reusable-search__entity-result-list li.reusable-search__result-container',
        'ul.reusable-search__entity-result-list > li',
    ]
    for selector in selectors:
        try:
            await page.wait_for_selector(selector, timeout=8000)
            count = await page.locator(selector).count()
            if count > 0:
                logger.debug("LinkedIn selector matched: %s (%d items)", selector, count)
                return selector
        except Exception:
            continue
    return None


async def _copy_post_link(item, page) -> str:
    """Click the overflow menu on a post and use 'Copy link to post' to get the URL."""
    try:
        overflow_btn = item.locator('button[aria-label^="Open control menu"]')
        if await overflow_btn.count() == 0:
            return ""
        await overflow_btn.first.click()
        await page.wait_for_timeout(1000)

        copy_link_item = page.locator('div[role="menuitem"]').filter(has_text="Copy link to post")
        if await copy_link_item.count() == 0:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
            return ""
        await copy_link_item.first.click()
        await page.wait_for_timeout(500)

        url = await page.evaluate("navigator.clipboard.readText()")
        if url and "linkedin.com" in url:
            logger.debug("Copied post link: %s", url)
            return url.strip()
    except Exception as exc:
        logger.debug("Failed to copy post link: %s", exc)
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
    return ""


async def _extract_post_urls(page, result_selector: str) -> list[dict]:
    """Extract post URLs and quoted post URLs from each result item.

    First tries JS-based extraction from the DOM. For items where that fails,
    falls back to the "Copy link to post" clipboard interaction.
    """
    items = page.locator(result_selector)
    count = await items.count()
    url_data: list[dict] = []

    for i in range(count):
        item = items.nth(i)
        data = await item.evaluate("""el => {
            let postUrl = '';
            // Strategy 1: share URN from componentkey attributes
            const shareMatch = el.innerHTML.match(/shareId=(\\d+)/);
            if (shareMatch) {
                postUrl = 'https://www.linkedin.com/feed/update/urn:li:share:' + shareMatch[1];
            }
            // Strategy 2: ugcPost URN
            if (!postUrl) {
                const ugcMatch = el.innerHTML.match(/userGeneratedContentId=(\\d+)/);
                if (ugcMatch) {
                    postUrl = 'https://www.linkedin.com/feed/update/urn:li:ugcPost:' + ugcMatch[1];
                }
            }
            // Strategy 3: activity link
            if (!postUrl) {
                const activityMatch = el.innerHTML.match(/activity[/:](\\d{15,})/);
                if (activityMatch) {
                    postUrl = 'https://www.linkedin.com/feed/update/urn:li:activity:' + activityMatch[1];
                }
            }
            // Strategy 4: data-urn attribute
            if (!postUrl) {
                const urnEl = el.querySelector('[data-urn]');
                if (urnEl) {
                    const urn = urnEl.getAttribute('data-urn');
                    if (urn && urn.includes(':activity:')) {
                        postUrl = 'https://www.linkedin.com/feed/update/' + urn;
                    }
                }
            }
            // Strategy 5: feed/update link in href
            if (!postUrl) {
                const feedLink = el.querySelector('a[href*="feed/update"]');
                if (feedLink) {
                    let href = feedLink.getAttribute('href') || '';
                    if (href.includes('?')) href = href.split('?')[0];
                    postUrl = href;
                }
            }

            // Quoted/reshared post URL
            let quotedPostUrl = '';
            const reshareArticle = el.querySelector(
                'article.feed-reshare-content, article[data-test-id="feed-reshare-content"], article[aria-label="Reshared post"]'
            );
            if (reshareArticle) {
                const reshareActivityUrn = reshareArticle.getAttribute('data-activity-urn');
                if (reshareActivityUrn && reshareActivityUrn.includes(':activity:')) {
                    quotedPostUrl = 'https://www.linkedin.com/feed/update/' + reshareActivityUrn;
                }
                if (!quotedPostUrl) {
                    const reshareShareUrn = reshareArticle.getAttribute('data-attributed-urn');
                    if (reshareShareUrn && reshareShareUrn.includes(':share:')) {
                        quotedPostUrl = 'https://www.linkedin.com/feed/update/' + reshareShareUrn;
                    }
                }
            }

            return { postUrl, quotedPostUrl };
        }""")

        # Fallback: use clipboard "Copy link to post" if JS extraction failed
        if not data.get("postUrl"):
            clipboard_url = await _copy_post_link(item, page)
            if clipboard_url:
                data["postUrl"] = clipboard_url

        url_data.append(data)

    return url_data


async def _capture_html(
    keyword: str, since: date, pw: Playwright, sort_by: str = "date_posted"
) -> tuple[str | None, list[dict]]:
    """Use Playwright to load, scroll, and capture the fully-rendered HTML.

    Returns a tuple of (filepath, url_data) where filepath is the saved HTML
    file path and url_data is a list of {postUrl, quotedPostUrl} dicts extracted
    via JS (one per result item, in DOM order). Returns (None, []) if no results.
    """
    state_path = config.LINKEDIN_AUTH_STATE_FILE
    if not os.path.exists(state_path):
        raise FileNotFoundError(
            f"LinkedIn auth state not found at '{state_path}'. "
            f"Run: uv run search.py --auth linkedin"
        )

    browser = await pw.chromium.launch(headless=False)
    context = await browser.new_context(
        storage_state=state_path,
        locale="en-US",
        permissions=["clipboard-read", "clipboard-write"],
    )
    page = await context.new_page()

    try:
        url = build_linkedin_url(keyword, since, sort_by=sort_by)
        logger.debug("LinkedIn navigating to: %s", url)

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Detect login redirect — session may have expired
        if "/login" in page.url:
            logger.warning(
                "Session expired for LinkedIn. Re-run: uv run search.py --auth linkedin"
            )
            return None, []

        # Click the "Top Match" filter for relevance searches
        if not sort_by:
            try:
                top_match_filter = page.locator('[aria-label="Filter by Top Match"]')
                await top_match_filter.wait_for(timeout=8000)
                await top_match_filter.click()
                await page.wait_for_timeout(2000)
                logger.debug("Clicked 'Top Match' filter for keyword %r", keyword)
            except Exception as exc:
                logger.debug("Could not click 'Top Match' filter: %s", exc)

        # Wait for search results with multiple selector fallbacks
        result_selector = await _find_result_selector(page)
        if not result_selector:
            logger.debug("Current URL after timeout: %s", page.url)
            logger.info("No results found for keyword %r on LinkedIn (sort=%s)", keyword, sort_by)
            return None, []

        # Scroll loop to load more results.
        # LinkedIn renders results inside a scrollable container, so
        # scrolling document.body alone may not trigger infinite-scroll.
        # We scroll the last result item into view, which works regardless
        # of which ancestor element is the actual scroll container.
        stale_scrolls = 0
        max_stale = 3
        for attempt in range(config.LINKEDIN_MAX_SCROLL_ATTEMPTS):
            count_before = await page.locator(result_selector).count()
            await page.locator(result_selector).last.scroll_into_view_if_needed()
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(int(config.LINKEDIN_SCROLL_PAUSE_SECONDS * 1000))
            count_after = await page.locator(result_selector).count()
            logger.debug("LinkedIn scroll %d: %d -> %d results", attempt + 1, count_before, count_after)
            if count_after == count_before:
                stale_scrolls += 1
                if stale_scrolls >= max_stale:
                    break
            else:
                stale_scrolls = 0

        # Extract post URLs via JS + clipboard fallback before capturing HTML
        url_data = await _extract_post_urls(page, result_selector)

        # Capture the fully-rendered HTML
        html = await page.content()

        # Save to tmp files
        os.makedirs(TMP_DIR, exist_ok=True)
        sort_label = sort_by or "relevance"
        safe_keyword = re.sub(r"[^a-zA-Z0-9]", "_", keyword).lower()

        html_filename = f"linkedin_{safe_keyword}_{sort_label}.html"
        html_filepath = os.path.join(TMP_DIR, html_filename)
        with open(html_filepath, "w", encoding="utf-8") as f:
            f.write(html)

        urls_filename = f"linkedin_{safe_keyword}_{sort_label}_urls.json"
        urls_filepath = os.path.join(TMP_DIR, urls_filename)
        with open(urls_filepath, "w", encoding="utf-8") as f:
            json.dump(url_data, f, indent=2)

        logger.info("Saved LinkedIn HTML to %s (%d URL records)", html_filepath, len(url_data))

        return html_filepath, url_data
    finally:
        await context.close()
        await browser.close()


def _resolve_text_node(element) -> str:
    """Recursively resolve text from a BeautifulSoup element, handling links and emojis."""
    result = ""
    for child in element.children:
        if isinstance(child, NavigableString):
            result += str(child)
        elif child.name == "br":
            result += "\n"
        elif child.name == "img":
            alt = child.get("alt", "")
            if alt:
                result += alt
        elif child.name == "a":
            href = child.get("href", "")
            display = child.get_text()
            if "\u2026" in display or display.endswith("..."):
                result += href
            else:
                result += display
        elif child.name == "button":
            continue
        else:
            result += _resolve_text_node(child)
    return result


def _parse_html(filepath: str, url_data: list[dict], since: date, until: date) -> list[dict]:
    """Parse LinkedIn search results from a saved HTML file using BeautifulSoup.

    Args:
        filepath: Path to the saved HTML file.
        url_data: List of {postUrl, quotedPostUrl} dicts extracted via Playwright JS,
                  one per result item in DOM order.
        since: Start date for filtering.
        until: End date for filtering.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    results: list[dict] = []

    # Try each selector strategy to find result items
    items = soup.select('[data-testid="lazy-column"] div[role="listitem"]')
    if not items:
        items = soup.select('div.search-results-container div[role="listitem"]')
    if not items:
        items = soup.select('div.reusable-search__entity-result-list li.reusable-search__result-container')
    if not items:
        items = soup.select('ul.reusable-search__entity-result-list > li')

    logger.debug("BeautifulSoup found %d result items in %s", len(items), filepath)

    for i, item in enumerate(items):
        try:
            # Author name: the second <a> in the item is the author profile
            # link, and its first <p> child contains the display name.
            # (Avoid relying on hashed CSS variable names which rotate.)
            author_name = "Unknown"
            item_links = item.select("a")
            if len(item_links) >= 2:
                author_p = item_links[1].select_one("p")
                if author_p:
                    author_name = author_p.get_text(strip=True)

            # Timestamp: <p> containing time indicators
            time_text = ""
            for p in item.find_all("p"):
                t = p.get_text(strip=True)
                if re.match(r"^\d+[mhdwmo]+\s*[•·]", t) or re.match(r"^\d+\s*(min|hour|day|week|month)", t):
                    time_text = t
                    break

            post_date = parse_relative_time(time_text)

            # Post text from expandable text box
            text_box = item.select_one('[data-testid="expandable-text-box"]')
            text = _resolve_text_node(text_box).strip() if text_box else ""

            # Post URL and quoted post URL from Playwright JS extraction
            item_urls = url_data[i] if i < len(url_data) else {}
            post_url = item_urls.get("postUrl", "")
            quoted_post_url = item_urls.get("quotedPostUrl", "")

            # Type detection
            post_type = "Repost" if quoted_post_url else "Post"

            # Exclusion filter
            text_lower = text.lower()
            if any(ex.lower() in text_lower for ex in config.EXCLUSIONS.get("linkedin", [])):
                continue

            # Date filter
            if post_date < since.isoformat() or post_date > until.isoformat():
                continue

            # Filter out posts where "dapr" is not a standalone keyword
            if not has_dapr_keyword(text):
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
                "quoted_url": quoted_post_url,
                "type": post_type,
                "platform": "linkedin",
            })
        except Exception as exc:
            logger.debug("Failed to parse LinkedIn result %d: %s", i, exc)
            continue

    logger.debug("Parsed %d valid results from %s", len(results), filepath)
    return results


async def scrape_linkedin(
    keyword: str, since: date, until: date, pw: Playwright, sort_by: str = "date_posted"
) -> list[dict]:
    """Scrape LinkedIn search results for a single keyword.

    Phase 1: Playwright renders the page and scrolls to load all results.
    Phase 2: The fully-rendered HTML is saved to a temp file.
    Phase 3: BeautifulSoup parses the data from the saved HTML.
    """
    filepath, url_data = await _capture_html(keyword, since, pw, sort_by=sort_by)
    if not filepath:
        return []
    return _parse_html(filepath, url_data, since, until)


async def run_linkedin(since: date, until: date) -> list[dict]:
    """Run LinkedIn search for all configured keywords in parallel, deduplicate by URL.

    Searches twice per keyword: once sorted by relevance (Top Match) and once
    sorted by date, so posts that only surface in one view are still captured.
    """
    async with async_playwright() as pw:
        # Launch all keyword searches concurrently (relevance sort)
        tasks = [scrape_linkedin(kw, since, until, pw, sort_by="") for kw in config.SEARCH_KEYWORDS]
        batches = await asyncio.gather(*tasks)

    all_results: list[dict] = []
    seen_keys: set[str] = set()
    for posts in batches:
        for post in posts:
            dedup_key = post["url"] if post["url"] else f"{post['author']}:{post['text'][:200]}"
            if dedup_key not in seen_keys:
                seen_keys.add(dedup_key)
                all_results.append(post)

    logger.info("LinkedIn: %d unique results across all keywords", len(all_results))
    return all_results
