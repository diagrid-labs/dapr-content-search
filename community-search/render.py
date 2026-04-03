#!/usr/bin/env python3
"""Render enriched JSON results into a final Markdown report.

Reads a JSON file where each post has been enriched with 'sentiment' and
'relevancy_score' fields, then produces a Markdown file with:
  - Posts reordered by relevancy (high > medium > low), then by date descending
  - A summary table with internal anchor links
"""

import argparse
import json
import os
import re
import sys
from datetime import date

from stats import build_stats, render_stats_table


RELEVANCY_ORDER = {"high": 0, "medium": 1, "low": 2, "": 3}


def slugify_heading(heading: str) -> str:
    """Convert a Markdown heading to a GitHub-flavored anchor slug."""
    slug = heading.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = slug.strip()
    slug = slug.replace(" ", "-")
    return slug


def sort_results(results: list[dict]) -> list[dict]:
    """Sort by relevancy_score (high first), then date descending."""
    return sorted(
        results,
        key=lambda r: (
            RELEVANCY_ORDER.get(r.get("relevancy_score", ""), 3),
            r.get("date", "") == "",  # empty dates last
            # Negate date for descending: reverse the string comparison
        ),
    )


def _date_sort_key(r: dict) -> str:
    """Return date string for secondary sort (descending)."""
    return r.get("date", "")


def sort_results(results: list[dict]) -> list[dict]:
    """Sort by relevancy_score (high first), then date descending within each tier."""
    # Stable sort: first by date descending, then by relevancy
    by_date = sorted(results, key=lambda r: r.get("date", ""), reverse=True)
    return sorted(
        by_date,
        key=lambda r: RELEVANCY_ORDER.get(r.get("relevancy_score", ""), 3),
    )


def _escape_pipe(text: str) -> str:
    """Escape literal pipe characters to prevent breaking Markdown tables."""
    return text.replace("|", r"\|")


def make_heading(r: dict) -> str:
    """Build the ## heading for a post."""
    author = _escape_pipe(r["author"])
    return f"{r['date']} \u2014 {author} \u2014 {r['type']}"


def render_post(r: dict) -> str:
    """Render a single post as Markdown."""
    heading = make_heading(r)
    section = (
        f"## {heading}\n\n"
        f"### Platform\n\n{r['platform']}\n\n"
        f"### Author\n\n{r['author']}\n\n"
        f"### Post\n\n{r['text']}\n\n"
        f"### URL\n\n{r['url']}\n"
    )
    quoted_url = r.get("quoted_url", "")
    if quoted_url:
        section += f"\n### Quoted Post URL\n\n{quoted_url}\n"
    if r.get("sentiment"):
        section += f"\n### Sentiment\n\n{r['sentiment']}\n"
    if r.get("relevancy_score"):
        section += f"\n### Relevancy Score\n\n{r['relevancy_score']}\n"
    return section


def render_summary_table(results: list[dict]) -> str:
    """Build the summary table with anchor links."""
    lines = [
        "| # | Platform | Author | Summary | Sentiment | Relevancy Score | Link |",
        "|---|----------|--------|---------|-----------|-----------------|------|",
    ]
    for i, r in enumerate(results, 1):
        heading = make_heading(r)
        anchor = slugify_heading(heading)
        # Strip handle/platform suffix from author for the table
        author_display = re.split(r"\s*[\(@]", r["author"])[0].strip()
        summary = r.get("summary", "")
        sentiment = r.get("sentiment", "")
        relevancy = r.get("relevancy_score", "")
        # Escape pipe characters to prevent breaking the Markdown table
        author_display = _escape_pipe(author_display)
        summary = _escape_pipe(summary)
        lines.append(
            f"| {i} | {r['platform']} | {author_display} | {summary} | {sentiment} | {relevancy} | [View](#{anchor}) |"
        )
    return "\n".join(lines)


def render_report(results: list[dict], since: str, until: str) -> str:
    """Render the full Markdown report."""
    sorted_results = sort_results(results)

    header = f"# Dapr Community Content \u2014 {since} to {until}\n\n"
    platform_stats = build_stats(sorted_results)
    stats_table = render_stats_table(platform_stats)
    summary_table = render_summary_table(sorted_results)
    posts = "\n---\n\n".join(render_post(r) for r in sorted_results)

    return f"{header}{stats_table}\n\n{summary_table}\n\n{posts}\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render enriched JSON results into a Markdown report."
    )
    parser.add_argument(
        "json_file",
        help="Path to the enriched JSON file",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output Markdown file path (default: same name as JSON with .md extension)",
    )
    parser.add_argument(
        "--since",
        help="Start date for the report header (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--until",
        help="End date for the report header (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.json_file):
        print(f"Error: JSON file not found: {args.json_file}")
        sys.exit(1)

    with open(args.json_file, "r", encoding="utf-8") as f:
        results = json.load(f)

    if not results:
        print("No results in JSON file.")
        sys.exit(0)

    # Derive date range from data if not provided
    since = args.since or min(r["date"] for r in results if r.get("date"))
    until = args.until or max(r["date"] for r in results if r.get("date"))

    output_path = args.output or os.path.splitext(args.json_file)[0] + ".md"

    report = render_report(results, since, until)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Report written to {output_path} ({len(results)} posts)")


if __name__ == "__main__":
    main()
