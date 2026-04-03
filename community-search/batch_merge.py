#!/usr/bin/env python3
"""Merge batch JSON files back into a single JSON array file.

Reads multiple batch files (produced by batch_split.py), concatenates
their arrays in batch-number order, and writes the merged result.
"""

import argparse
import glob
import json
import os
import re
import sys


def _batch_sort_key(path: str) -> int:
    """Extract the numeric batch suffix for sorting."""
    match = re.search(r"_batch_(\d+)\.json$", path)
    return int(match.group(1)) if match else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge batch JSON files into a single JSON array file."
    )
    parser.add_argument(
        "batch_files",
        nargs="*",
        help="Paths to batch JSON files",
    )
    parser.add_argument(
        "--pattern", "-p",
        default=None,
        help='Glob pattern to find batch files (e.g. "reports/*_batch_*.json")',
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Path to write the merged JSON array",
    )
    parser.add_argument(
        "--delete-batches",
        action="store_true",
        help="Delete batch files after successful merge",
    )
    args = parser.parse_args()

    # Collect batch file paths
    batch_files = list(args.batch_files) if args.batch_files else []
    if args.pattern:
        batch_files.extend(glob.glob(args.pattern))

    if not batch_files:
        print("Error: no batch files found.")
        sys.exit(1)

    # Deduplicate and sort by batch number
    batch_files = sorted(set(batch_files), key=_batch_sort_key)

    # Read and merge
    merged = []
    for path in batch_files:
        if not os.path.exists(path):
            print(f"Error: batch file not found: {path}")
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            merged.extend(json.load(f))

    # Write merged output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"Merged {len(merged)} posts from {len(batch_files)} batch files into {args.output}")

    # Clean up batch files if requested
    if args.delete_batches:
        for path in batch_files:
            os.remove(path)
        print(f"Deleted {len(batch_files)} batch files.")


if __name__ == "__main__":
    main()
