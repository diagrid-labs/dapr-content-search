#!/usr/bin/env python3
"""Verify that a JSON report file has been enriched correctly.

Reads a JSON report file and checks that every post has non-empty
sentiment, relevancy_score, and summary fields. Prints a summary
including total post count, enrichment status, and a sample post.

Usage:
    uv run python verify.py <report.json>
"""

import argparse
import json
import sys


ENRICHMENT_FIELDS = ("sentiment", "relevancy_score", "summary")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify enrichment of a JSON report file."
    )
    parser.add_argument("report", help="Path to the JSON report file to verify.")
    args = parser.parse_args()

    with open(args.report, "r", encoding="utf-8") as f:
        posts = json.load(f)

    total = len(posts)
    enriched = sum(
        1
        for p in posts
        if all(p.get(field) for field in ENRICHMENT_FIELDS)
    )
    all_enriched = enriched == total

    print(f"Total posts: {total}")
    print(f"Enriched: {enriched}/{total}")
    print(f"All enriched: {all_enriched}")

    if total > 0:
        sample = {k: posts[0].get(k) for k in ("author", "sentiment", "relevancy_score", "summary")}
        print(f"Sample: {json.dumps(sample, indent=2)}")

    if not all_enriched:
        missing = [
            i for i, p in enumerate(posts)
            if not all(p.get(field) for field in ENRICHMENT_FIELDS)
        ]
        print(f"Posts missing enrichment at indices: {missing[:10]}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
