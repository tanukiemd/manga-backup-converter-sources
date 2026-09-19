#!/usr/bin/env python3
"""Find manga tracked from multiple different sources within ONE backup
(e.g. added once via MangaDex, once via AsuraScans), and remove the ones
you don't want to keep. Same format in, same format out - no conversion.

Usage:
    # Step 1: see what's duplicated
    python find_duplicates.py --app tachiyomi --backup library.tachibk

    # Step 2: remove everything except the suggested keeper in each group
    python find_duplicates.py --app tachiyomi --backup library.tachibk \
        --apply --out cleaned.tachibk

By default --apply keeps whichever entry in each group has the most
chapters read (tied-broken by most recently read) - the same suggestion
the website shows. There's no interactive per-group picker here; if you
want a specific different one kept, edit the JSON from --dump-json and
pass it back with --keys-file.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from app import dedupe  # noqa: E402

APPS = ["tachiyomi", "tachimanga", "aidoku"]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--app", required=True, choices=APPS, help="Which app the backup is from")
    parser.add_argument("--backup", required=True, type=Path, help="The backup file")
    parser.add_argument("--apply", action="store_true",
                         help="Write a cleaned backup instead of just listing duplicates")
    parser.add_argument("--out", type=Path, default=None,
                         help="Where to write the cleaned backup (required with --apply, unless --keys-file is used standalone)")
    parser.add_argument("--dump-json", type=Path, default=None,
                         help="Also write the full find-duplicates result as JSON to this path")
    parser.add_argument("--keys-file", type=Path, default=None,
                         help="Advanced: a JSON file listing exactly which [key, key] pairs to remove, "
                              "instead of using the auto-suggested keeper for every group")
    args = parser.parse_args()

    if not args.backup.exists():
        sys.exit(f"Error: file not found: {args.backup}")
    data = args.backup.read_bytes()

    try:
        result = dedupe.find_duplicates(data, args.app)
    except Exception as e:
        sys.exit(f"Failed to read backup: {e}")

    if args.dump_json:
        args.dump_json.write_text(json.dumps(result, indent=2))
        print(f"Full result written to {args.dump_json}")

    if not result["duplicate_groups"]:
        print("No duplicates found - every manga in this backup only has one entry.")
        return

    print(f"{len(result['duplicate_groups'])} duplicate group(s) out of {result['total_manga']} manga:\n")
    for group in result["duplicate_groups"]:
        print(f"  {group['title']}")
        for i, e in enumerate(group["entries"]):
            marker = " <- keeping" if i == group["suggested_keeper"] else ""
            print(f"    - {e['chapters_read']} chapters read{marker}")

    if not args.apply:
        print("\nRun again with --apply --out cleaned<ext> to write a cleaned backup "
              "using these suggestions (or --keys-file to choose differently).")
        return

    if args.keys_file:
        keys_to_remove = json.loads(args.keys_file.read_text())
    else:
        keys_to_remove = []
        for group in result["duplicate_groups"]:
            for i, e in enumerate(group["entries"]):
                if i != group["suggested_keeper"]:
                    keys_to_remove.append(e["key"])

    if not args.out:
        sys.exit("Error: --out is required with --apply.")

    try:
        cleaned = dedupe.remove_duplicates(data, args.app, keys_to_remove)
    except Exception as e:
        sys.exit(f"Failed to write cleaned backup: {e}")

    args.out.write_bytes(cleaned)
    print(f"\n{len(keys_to_remove)} duplicate entries removed. Written to {args.out}")


if __name__ == "__main__":
    main()
