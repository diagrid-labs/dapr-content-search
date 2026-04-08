#!/usr/bin/env python3
"""CLI entry point for Dapr community content search."""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date

from dateutil.parser import parse as parse_date

# Ensure the script's directory is on the path so config/platforms are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from platforms.bluesky import run_bluesky
from platforms.linkedin import run_linkedin
from platforms.reddit import run_reddit

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth setup
# ---------------------------------------------------------------------------

async def auth_setup(platform: str) -> None:
    """Launch a headed browser for the user to log in and save session state."""
    from playwright.async_api import async_playwright

    if platform == "linkedin":
        login_url = "https://www.linkedin.com/login"
        state_file = config.LINKEDIN_AUTH_STATE_FILE
    else:
        print(f"Auth not supported for platform: {platform}")
        sys.exit(1)

    os.makedirs(config.AUTH_DIR, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, channel="chrome")
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        await page.goto(login_url)
        print(f"\nA browser window has opened to {login_url}")
        print("Log in manually, then press Enter here to save the session...")
        await asyncio.get_event_loop().run_in_executor(None, input)

        await context.storage_state(path=state_file)
        print(f"Session saved to {state_file}")

        await context.close()
        await browser.close()


# ---------------------------------------------------------------------------
# Platform runners (with error isolation)
# ---------------------------------------------------------------------------

async def run_platform(name: str, since: date, until: date) -> list[dict]:
    """Run a single platform, catching errors so others can continue."""
    runners = {
        "bluesky": run_bluesky,
        "linkedin": run_linkedin,
        "reddit": run_reddit,
    }
    if name == "x":
        print("[x] X search now uses the x-mcp MCP server. "
              "Use the search-dapr-content skill or call x-mcp tools directly.")
        return []
    runner = runners.get(name)
    if not runner:
        print(f"Unknown platform: {name}")
        return []
    try:
        return await runner(since, until)
    except FileNotFoundError as exc:
        print(f"[{name}] {exc}")
        return []
    except Exception as exc:
        logger.error("Platform %s failed: %s", name, exc, exc_info=True)
        print(f"[{name}] Error: {exc}")
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search social platforms for Dapr community content."
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--all", action="store_true",
        help="Run all three platforms and merge results",
    )
    mode.add_argument(
        "--platform", choices=["x", "linkedin", "bluesky", "reddit"],
        help="Run a single platform",
    )
    mode.add_argument(
        "--auth", choices=["linkedin"],
        help="Auth setup mode — launches a visible browser for login",
    )

    parser.add_argument(
        "--since", type=str, default=None,
        help="Start date (YYYY-MM-DD); overrides config default",
    )
    parser.add_argument(
        "--until", type=str, default=None,
        help="End date (YYYY-MM-DD); overrides config default",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Write results to this JSON file (default: reports/YYYY-MM-DD-community-content.json)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug-level logging",
    )

    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Logging setup
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Require at least one mode flag
    if not args.all and not args.platform and not args.auth:
        parser.print_usage()
        sys.exit(1)

    # Parse date overrides
    since = config.SINCE_DATE
    until = config.UNTIL_DATE

    if args.since:
        since = parse_date(args.since).date()
    if args.until:
        until = parse_date(args.until).date()

    # Validate date range
    if since >= until:
        print(f"Error: --since ({since}) must be before --until ({until})")
        sys.exit(1)

    # Auth mode
    if args.auth:
        await auth_setup(args.auth)
        return

    # Determine which platforms to run
    if args.all:
        platforms = ["x", "linkedin", "bluesky", "reddit"]
    else:
        platforms = [args.platform]

    # Run platforms in parallel
    platform_results = await asyncio.gather(
        *(run_platform(name, since, until) for name in platforms)
    )

    # Write a separate JSON file per platform
    reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports")
    os.makedirs(reports_dir, exist_ok=True)

    total_posts = 0
    for name, results in zip(platforms, platform_results):
        if not results:
            print(f"[{name}] No results found.")
            continue

        # Deduplicate by URL (use author+text hash for empty URLs)
        seen: set[str] = set()
        deduped: list[dict] = []
        for r in results:
            dedup_key = r["url"] if r["url"] else f"{r['author']}:{r['text'][:200]}"
            if dedup_key not in seen:
                seen.add(dedup_key)
                deduped.append(r)

        # Sort by date descending
        deduped.sort(key=lambda r: r["date"], reverse=True)

        # Determine output file path
        if args.output:
            base, ext = os.path.splitext(args.output)
            output_path = f"{base}-{name}{ext or '.json'}"
        else:
            output_path = os.path.join(reports_dir, f"{date.today().isoformat()}-{name}-community-content.json")

        json_results = []
        for r in deduped:
            json_results.append({
                "date": r["date"],
                "author": r["author"],
                "text": r["text"],
                "url": r["url"],
                "quoted_url": r.get("quoted_url", ""),
                "type": r["type"],
                "platform": r["platform"],
                "sentiment": "",
                "relevancy_score": "",
            })
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(json_results, f, indent=2, ensure_ascii=False)

        print(f"JSON written to {output_path} ({len(deduped)} posts)")
        total_posts += len(deduped)

    if total_posts == 0:
        print("No results found across any platform.")


if __name__ == "__main__":
    asyncio.run(main())
