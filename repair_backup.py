#!/usr/bin/env python3
"""Clean up a backup: drop entries missing a url or title, collapse
duplicate chapters within the same manga (keeps the read copy when either
is marked read), and remove category tags pointing at a category that no
longer exists. Same format in, same format out.

Usage:
    python repair_backup.py --app tachiyomi --backup library.tachibk
    python repair_backup.py --app tachiyomi --backup library.tachibk --apply --out repaired.tachibk
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from app import repair  # noqa: E402

APPS = ["tachiyomi", "tachimanga", "aidoku"]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--app", required=True, choices=APPS, help="Which app the backup is from")
    parser.add_argument("--backup", required=True, type=Path, help="The backup file")
    parser.add_argument("--apply", action="store_true",
                         help="Write a repaired backup instead of just analyzing")
    parser.add_argument("--out", type=Path, default=None, help="Where to write the repaired backup")
    args = parser.parse_args()

    if not args.backup.exists():
        sys.exit(f"Error: file not found: {args.backup}")
    data = args.backup.read_bytes()

    if not args.apply:
        try:
            result = repair.analyze_backup(data, args.app)
        except Exception as e:
            sys.exit(f"Failed to analyze backup: {e}")
        if not result["has_issues"]:
            print("No issues found - this backup looks clean.")
            return
        print("Issues found:")
        if result["broken_entries_removed"]:
            print(f"  {result['broken_entries_removed']} broken entries")
        if result["duplicate_chapters_removed"]:
            print(f"  {result['duplicate_chapters_removed']} duplicate chapters")
        if result["orphaned_categories_removed"]:
            print(f"  {result['orphaned_categories_removed']} orphaned category tags")
        print("\nRun again with --apply --out repaired<ext> to write a cleaned copy.")
        return

    if not args.out:
        sys.exit("Error: --out is required with --apply.")

    try:
        cleaned, report = repair.repair_backup(data, args.app)
    except Exception as e:
        sys.exit(f"Failed to repair backup: {e}")

    args.out.write_bytes(cleaned)
    print(f"{report['broken_entries_removed']} broken entries, "
          f"{report['duplicate_chapters_removed']} duplicate chapters, "
          f"{report['orphaned_categories_removed']} orphaned category tags removed.")
    print(f"Written to {args.out}")


if __name__ == "__main__":
    main()
