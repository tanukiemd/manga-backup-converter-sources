#!/usr/bin/env python3
"""Compare two backups of the SAME app - what's newly added, what's no
longer present, and whose reading progress changed. Read-only, writes
nothing back. Same engine as the "Compare two backups" section on
https://chococornet.moe/convert/, just local/offline.

Usage:
    python compare_backups.py --app tachiyomi --old old_library.tachibk --new new_library.tachibk
    python compare_backups.py --app aidoku --old a.aib --new b.aib --json out.json
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from app import diff  # noqa: E402

APPS = ["tachiyomi", "tachimanga", "aidoku"]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--app", required=True, choices=APPS,
                         help="Which app both backups are from")
    parser.add_argument("--old", required=True, type=Path, help="The older backup")
    parser.add_argument("--new", required=True, type=Path, help="The newer backup")
    parser.add_argument("--json", type=Path, default=None,
                         help="Optional: also write the full result as JSON to this path")
    args = parser.parse_args()

    for p in (args.old, args.new):
        if not p.exists():
            sys.exit(f"Error: file not found: {p}")

    try:
        result = diff.compare_backups(args.old.read_bytes(), args.new.read_bytes(), args.app)
    except Exception as e:
        sys.exit(f"Comparison failed: {e}")

    if not result["added"] and not result["removed"] and not result["progress_changed"]:
        print("No differences found - these two backups are identical.")
    else:
        if result["added"]:
            print(f"\n{len(result['added'])} newly added:")
            for m in result["added"]:
                print(f"  + {m['title']}")
        if result["removed"]:
            print(f"\n{len(result['removed'])} no longer present:")
            for m in result["removed"]:
                print(f"  - {m['title']}")
        if result["progress_changed"]:
            print(f"\n{len(result['progress_changed'])} reading progress changed:")
            for m in result["progress_changed"]:
                parts = []
                if m["newly_read"]:
                    parts.append(f"{m['newly_read']} newly read")
                if m["new_chapters"]:
                    parts.append(f"{m['new_chapters']} new chapters")
                suffix = f" ({', '.join(parts)})" if parts else ""
                print(f"  ~ {m['title']}{suffix}")
        print(f"\n{result['unchanged_count']} unchanged")

    if args.json:
        args.json.write_text(json.dumps(result, indent=2))
        print(f"\nFull result written to {args.json}")


if __name__ == "__main__":
    main()
