#!/usr/bin/env python3
"""Apply enrichment data to a JSON report file.

Reads a JSON report file and an enrichment JSON string (or file), then merges
the enrichment fields (sentiment, relevancy_score, summary) into the report
by matching on array index. Writes the result back using json.dump so that
all string values are properly escaped.

Usage:
    # Enrichment from a JSON string:
    uv run python enrich.py <report.json> --data '[{"sentiment": "positive", ...}, ...]'

    # Enrichment from a file:
    uv run python enrich.py <report.json> --data-file enrichments.json
"""

import argparse
import json
import sys


ENRICHMENT_FIELDS = ("sentiment", "relevancy_score", "summary")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge enrichment fields into a JSON report file."
    )
    parser.add_argument("report", help="Path to the JSON report file to enrich.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--data",
        help="Enrichment data as a JSON string (array of objects).",
    )
    group.add_argument(
        "--data-file",
        help="Path to a JSON file containing the enrichment array.",
    )
    args = parser.parse_args()

    # Load the report
    with open(args.report, "r", encoding="utf-8") as f:
        posts = json.load(f)

    # Load enrichment data
    if args.data_file:
        with open(args.data_file, "r", encoding="utf-8") as f:
            enrichments = json.load(f)
    else:
        enrichments = json.loads(args.data)

    if len(enrichments) != len(posts):
        print(
            f"Error: enrichment array length ({len(enrichments)}) does not match "
            f"report array length ({len(posts)}).",
            file=sys.stderr,
        )
        sys.exit(1)

    # Merge enrichment fields into posts
    for post, enrichment in zip(posts, enrichments):
        for field in ENRICHMENT_FIELDS:
            if field in enrichment:
                post[field] = enrichment[field]

    # Write back with json.dump — this guarantees valid JSON with proper escaping
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)

    print(f"Enriched {len(posts)} posts in {args.report}")


if __name__ == "__main__":
    main()
