#!/usr/bin/env python3
"""Manga Wrapped: total manga, chapters read, top sources, top genres, and
oldest entry from a single backup. Read-only.

The website draws a shareable card image from this in the browser - there's
no equivalent image output here, this just prints the numbers (or dumps them
as JSON with --json).

Usage:
    python wrapped_stats.py --app tachiyomi --backup library.tachibk
    python wrapped_stats.py --app tachiyomi --backup library.tachibk --json out.json
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from app import wrapped  # noqa: E402

APPS = ["tachiyomi", "tachimanga", "aidoku"]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--app", required=True, choices=APPS, help="Which app the backup is from")
    parser.add_argument("--backup", required=True, type=Path, help="The backup file")
    parser.add_argument("--json", type=Path, default=None, help="Also write the full result as JSON")
    args = parser.parse_args()

    if not args.backup.exists():
        sys.exit(f"Error: file not found: {args.backup}")

    try:
        result = wrapped.compute_stats(args.backup.read_bytes(), args.app)
    except Exception as e:
        sys.exit(f"Failed to read backup: {e}")

    print(f"{result['total_manga']} manga")
    print(f"{result['total_chapters_read']} chapters read")
    if result["top_sources"]:
        print(f"Top source: {result['top_sources'][0][0]} ({result['top_sources'][0][1]} manga)")
    if result["top_genres"]:
        print(f"Top genre: {result['top_genres'][0][0]} ({result['top_genres'][0][1]} manga)")
    if result["oldest_entry_title"]:
        print(f"Oldest entry: {result['oldest_entry_title']}")

    if args.json:
        args.json.write_text(json.dumps(result, indent=2))
        print(f"\nFull result written to {args.json}")


if __name__ == "__main__":
    main()
