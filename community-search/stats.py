#!/usr/bin/env python3
"""Generate a platform statistics table from an enriched JSON report.

Reads a JSON file and prints a Markdown table showing the number of posts
per platform, broken down by relevancy score (high, medium, low).
"""

import argparse
import json
import os
import sys
from collections import Counter


def build_stats(results: list[dict]) -> dict[str, Counter]:
    """Build per-platform relevancy counters.

    Returns a dict mapping platform name to a Counter of relevancy scores.
    """
    stats: dict[str, Counter] = {}
    for r in results:
        platform = r.get("platform", "unknown")
        relevancy = r.get("relevancy_score", "unknown")
        if platform not in stats:
            stats[platform] = Counter()
        stats[platform][relevancy] += 1
    return stats


def render_stats_table(stats: dict[str, Counter]) -> str:
    """Render the statistics as a Markdown table."""
    lines = [
        "| Platform | High | Medium | Low | Total |",
        "|----------|------|--------|-----|-------|",
    ]

    total_high = 0
    total_medium = 0
    total_low = 0
    total_all = 0

    for platform in sorted(stats.keys()):
        counts = stats[platform]
        high = counts.get("high", 0)
        medium = counts.get("medium", 0)
        low = counts.get("low", 0)
        total = sum(counts.values())
        lines.append(f"| {platform} | {high} | {medium} | {low} | {total} |")
        total_high += high
        total_medium += medium
        total_low += low
        total_all += total

    lines.append(f"| **Total** | **{total_high}** | **{total_medium}** | **{total_low}** | **{total_all}** |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate platform statistics table from enriched JSON."
    )
    parser.add_argument(
        "json_file",
        help="Path to the enriched JSON file",
    )
    args = parser.parse_args()

    if not os.path.exists(args.json_file):
        print(f"Error: JSON file not found: {args.json_file}", file=sys.stderr)
        sys.exit(1)

    with open(args.json_file, "r", encoding="utf-8") as f:
        results = json.load(f)

    if not results:
        print("No results in JSON file.", file=sys.stderr)
        sys.exit(0)

    stats = build_stats(results)
    print(render_stats_table(stats))


if __name__ == "__main__":
    main()
