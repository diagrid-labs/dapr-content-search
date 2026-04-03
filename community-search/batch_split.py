#!/usr/bin/env python3
"""Split a JSON array file into smaller batch files.

Reads a JSON file containing an array of posts and writes chunks of
configurable size to separate batch files, suitable for parallel
enrichment by subagents.
"""

import argparse
import json
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split a JSON array file into batch files."
    )
    parser.add_argument(
        "json_file",
        help="Path to the input JSON array file",
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=15,
        help="Number of posts per batch file (default: 15)",
    )
    parser.add_argument(
        "--output-dir", "-d",
        default=None,
        help="Directory for batch files (default: same as input file)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.json_file):
        print(f"Error: file not found: {args.json_file}")
        sys.exit(1)

    with open(args.json_file, "r", encoding="utf-8") as f:
        posts = json.load(f)

    if not posts:
        print("Error: JSON file is empty or contains no posts.")
        sys.exit(1)

    output_dir = args.output_dir or os.path.dirname(os.path.abspath(args.json_file))
    os.makedirs(output_dir, exist_ok=True)

    stem = os.path.splitext(os.path.basename(args.json_file))[0]

    batch_files = []
    for i in range(0, len(posts), args.batch_size):
        batch_num = i // args.batch_size + 1
        batch = posts[i : i + args.batch_size]
        batch_path = os.path.join(output_dir, f"{stem}_batch_{batch_num}.json")

        with open(batch_path, "w", encoding="utf-8") as f:
            json.dump(batch, f, indent=2, ensure_ascii=False)

        batch_files.append(batch_path)
        print(batch_path)

    print(f"Split {len(posts)} posts into {len(batch_files)} batch files.")


if __name__ == "__main__":
    main()
