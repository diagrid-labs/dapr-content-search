#!/usr/bin/env python3
"""CLI entry point for Dapr community content search."""

import argparse
import asyncio
import logging
import os
import sys
from datetime import date

from dateutil.parser import parse as parse_date

# Ensure the script's directory is on the path so config/platforms are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from platforms.bluesky import run_bluesky
from platforms.x import run_x
from platforms.linkedin import run_linkedin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth setup
# ---------------------------------------------------------------------------

async def auth_setup(platform: str) -> None:
    """Launch a headed browser for the user to log in and save session state."""
    from playwright.async_api import async_playwright

    if platform == "x":
        login_url = "https://x.com/login"
        state_file = config.X_AUTH_STATE_FILE
    elif platform == "linkedin":
        login_url = "https://www.linkedin.com/login"
        state_file = config.LINKEDIN_AUTH_STATE_FILE
    else:
        print(f"Auth not supported for platform: {platform}")
        sys.exit(1)

    os.makedirs(config.AUTH_DIR, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
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
# Output rendering
# ---------------------------------------------------------------------------

def render_results(results: list[dict]) -> str:
    """Render results as Markdown with headings."""
    sections: list[str] = []
    for r in results:
        section = (
            f"## {r['date']} — {r['type']}\n\n"
            f"### Platform\n\n{r['platform']}\n\n"
            f"### Author\n\n{r['author']}\n\n"
            f"### Post\n\n{r['text']}\n\n"
            f"### URL\n\n{r['url']}\n"
        )
        quoted_url = r.get("quoted_url", "")
        if quoted_url:
            section += f"\n### Quoted Post URL\n\n{quoted_url}\n"
        sections.append(section)
    return "\n---\n\n".join(sections)


def append_to_file(path: str, since: date, until: date, content: str) -> None:
    """Append the Markdown content to a file with a section header."""
    with open(path, "a") as f:
        f.write(f"# Dapr Community Content — {since} to {until}\n\n")
        f.write(content)
        f.write("\n")


# ---------------------------------------------------------------------------
# Platform runners (with error isolation)
# ---------------------------------------------------------------------------

async def run_platform(name: str, since: date, until: date) -> list[dict]:
    """Run a single platform, catching errors so others can continue."""
    runners = {
        "bluesky": run_bluesky,
        "x": run_x,
        "linkedin": run_linkedin,
    }
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
        "--platform", choices=["x", "linkedin", "bluesky"],
        help="Run a single platform",
    )
    mode.add_argument(
        "--auth", choices=["x", "linkedin"],
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
        help="Write results to this file (default: YYYY-MM-DD-community-content.md)",
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
        platforms = ["x", "linkedin", "bluesky"]
    else:
        platforms = [args.platform]

    # Run each platform (errors are caught per-platform)
    all_results: list[dict] = []
    for name in platforms:
        results = await run_platform(name, since, until)
        all_results.extend(results)

    # Deduplicate by URL across platforms (use author+text hash for empty URLs)
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in all_results:
        dedup_key = r["url"] if r["url"] else f"{r['author']}:{r['text'][:200]}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            deduped.append(r)

    # Sort by date descending
    deduped.sort(key=lambda r: r["date"], reverse=True)

    if not deduped:
        print("No results found.")
        return

    # Render table
    table_str = render_results(deduped)

    # Determine output file path (default: reports/ in repo root)
    if args.output:
        output_path = args.output
    else:
        reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports")
        os.makedirs(reports_dir, exist_ok=True)
        output_path = os.path.join(reports_dir, f"{date.today().isoformat()}-community-content.md")

    # Write to file
    append_to_file(output_path, since, until, table_str)
    print(f"Results written to {output_path} ({len(deduped)} posts)")


if __name__ == "__main__":
    asyncio.run(main())
