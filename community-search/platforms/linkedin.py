"""LinkedIn scraper using Playwright."""

import logging
import os
import re
from datetime import date, timedelta, datetime
from urllib.parse import quote

from playwright.async_api import Playwright, async_playwright

import config
from platforms import has_dapr_keyword, is_nsfw, only_dapr_in_youtube_id

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
        # Find and click the overflow menu button (three dots)
        overflow_btn = item.locator('button[aria-label^="Open control menu"]')
        if await overflow_btn.count() == 0:
            return ""
        await overflow_btn.first.click()
        await page.wait_for_timeout(1000)

        # Find and click the "Copy link to post" menu item
        copy_link_item = page.locator('div[role="menuitem"]').filter(has_text="Copy link to post")
        if await copy_link_item.count() == 0:
            # Close the menu by pressing Escape
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
            return ""
        await copy_link_item.first.click()
        await page.wait_for_timeout(500)

        # Read the URL from the clipboard
        url = await page.evaluate("navigator.clipboard.readText()")
        if url and "linkedin.com" in url:
            logger.debug("Copied post link: %s", url)
            return url.strip()
    except Exception as exc:
        logger.debug("Failed to copy post link: %s", exc)
        # Try to close any open menu
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
    return ""


async def scrape_linkedin(
    keyword: str, since: date, until: date, pw: Playwright, sort_by: str = "date_posted"
) -> list[dict]:
    """Scrape LinkedIn search results for a single keyword."""
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

    results: list[dict] = []
    try:
        url = build_linkedin_url(keyword, since, sort_by=sort_by)
        logger.debug("LinkedIn navigating to: %s", url)

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Detect login redirect — session may have expired
        if "/login" in page.url:
            logger.warning(
                "Session expired for LinkedIn. Re-run: uv run search.py --auth linkedin"
            )
            return []

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
            return []

        # Scroll loop to load more results
        stale_scrolls = 0
        max_stale = 3  # stop after this many consecutive scrolls with no new results
        for attempt in range(config.LINKEDIN_MAX_SCROLL_ATTEMPTS):
            count_before = await page.locator(result_selector).count()
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

        # Extract data from each result
        items = page.locator(result_selector)
        count = await items.count()

        for i in range(count):
            item = items.nth(i)
            try:
                # Extract all data via a single JS evaluation for reliability
                data = await item.evaluate("""el => {
                    // Author name: first <p> with a specific style variable
                    const authorP = el.querySelector('p[style*="--_2f26bb22"]');
                    const author = authorP ? authorP.textContent.trim() : '';

                    // Timestamp: <p> containing time indicators like "1d", "3w", "2mo"
                    const allPs = el.querySelectorAll('p');
                    let timeText = '';
                    for (const p of allPs) {
                        const t = p.textContent.trim();
                        if (/^\d+[mhdwmo]+\s*[•·]/.test(t) || /^\d+\s*(min|hour|day|week|month)/.test(t)) {
                            timeText = t;
                            break;
                        }
                    }

                    // Post text from expandable text box
                    const textBox = el.querySelector('[data-testid="expandable-text-box"]');
                    let text = '';
                    if (textBox) {
                        // Resolve links: use href for truncated display text
                        function resolveNode(node) {
                            let result = '';
                            for (const child of node.childNodes) {
                                if (child.nodeType === 3) {
                                    result += child.textContent;
                                } else if (child.tagName === 'IMG') {
                                    // LinkedIn renders emojis as <img> with alt text
                                    const alt = child.getAttribute('alt') || '';
                                    if (alt) result += alt;
                                } else if (child.tagName === 'A') {
                                    const href = child.getAttribute('href') || '';
                                    const display = child.textContent || '';
                                    if (display.includes('\u2026') || display.endsWith('...')) {
                                        result += href;
                                    } else {
                                        result += display;
                                    }
                                } else if (child.tagName === 'BUTTON') {
                                    // Skip "...more" buttons
                                    continue;
                                } else {
                                    result += resolveNode(child);
                                }
                            }
                            return result;
                        }
                        text = resolveNode(textBox).trim();
                    }

                    // Post URL: try multiple extraction strategies
                    let postUrl = '';
                    // Strategy 1: share URN from componentkey attributes
                    const shareMatch = el.innerHTML.match(/shareId=(\d+)/);
                    if (shareMatch) {
                        postUrl = 'https://www.linkedin.com/feed/update/urn:li:share:' + shareMatch[1];
                    }
                    // Strategy 2: ugcPost URN from userGeneratedContentId
                    if (!postUrl) {
                        const ugcMatch = el.innerHTML.match(/userGeneratedContentId=(\d+)/);
                        if (ugcMatch) {
                            postUrl = 'https://www.linkedin.com/feed/update/urn:li:ugcPost:' + ugcMatch[1];
                        }
                    }
                    // Strategy 3: activity link
                    if (!postUrl) {
                        const activityMatch = el.innerHTML.match(/activity[/:](\d{15,})/);
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

                    // Author profile URL
                    let authorUrl = '';
                    const authorLink = el.querySelector('a[href*="/in/"], a[href*="/company/"]');
                    if (authorLink) {
                        authorUrl = authorLink.getAttribute('href') || '';
                        if (authorUrl.includes('?')) authorUrl = authorUrl.split('?')[0];
                    }

                    // Quoted/reshared post detection
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

                    return { author, timeText, text, postUrl, authorUrl, quotedPostUrl };
                }""")

                author_name = data.get("author", "Unknown") or "Unknown"
                text = data.get("text", "")
                time_text = data.get("timeText", "")
                post_url = data.get("postUrl", "")
                quoted_post_url = data.get("quotedPostUrl", "")
                post_date = parse_relative_time(time_text)

                # If URL is still missing, use the "Copy link to post" menu
                if not post_url:
                    post_url = await _copy_post_link(item, page)

                # Type detection based on content
                post_type = "Repost" if quoted_post_url else "Post"
                if data.get("authorUrl") and "/company/" in data.get("authorUrl", ""):
                    post_type = "Repost" if quoted_post_url else "Post"

                # Exclusion filter
                text_lower = text.lower()
                if any(ex.lower() in text_lower for ex in config.EXCLUSIONS.get("linkedin", [])):
                    continue

                # Date filter
                if post_date < since.isoformat() or post_date > until.isoformat():
                    continue

                # Filter out posts where "dapr" is not a standalone keyword
                # (e.g. French "d'après" contains "dapr" as a substring)
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
                logger.debug("Failed to extract LinkedIn result %d: %s", i, exc)
                continue
    finally:
        await context.close()
        await browser.close()

    logger.debug("LinkedIn keyword %r returned %d results", keyword, len(results))
    return results


async def run_linkedin(since: date, until: date) -> list[dict]:
    """Run LinkedIn search for all configured keywords, deduplicate by URL.

    Searches twice per keyword: once sorted by relevance (Top Match) and once
    sorted by date, so posts that only surface in one view are still captured.
    """
    all_results: list[dict] = []
    seen_keys: set[str] = set()

    async with async_playwright() as pw:
        for keyword in config.SEARCH_KEYWORDS:
            for sort_by in ("", "date_posted"):
                posts = await scrape_linkedin(keyword, since, until, pw, sort_by=sort_by)
                for post in posts:
                    # Deduplicate by URL if available, otherwise by author+text hash
                    dedup_key = post["url"] if post["url"] else f"{post['author']}:{post['text'][:200]}"
                    if dedup_key not in seen_keys:
                        seen_keys.add(dedup_key)
                        all_results.append(post)

    logger.info("LinkedIn: %d unique results across all keywords", len(all_results))
    return all_results
