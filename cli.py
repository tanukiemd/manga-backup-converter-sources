#!/usr/bin/env python3
"""Local, offline manga backup converter.

Same conversion engine as https://chococornet.moe/convert/, but everything
stays on your machine - no upload, no server, no internet connection
needed once you've cloned this repo. For people who'd rather not send
their library/reading history anywhere, even to a tool that promises not
to keep it.

Usage:
    python cli.py --from tachiyomi --to aidoku --source library.tachibk --out converted.aib
    python cli.py --from aidoku --to tachiyomi --source library.aib --target existing.tachibk --out merged.tachibk

If --target is omitted, an empty starter backup for the target app is used
(same ones the web tool offers), so you don't need an existing backup in
the target app first.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from app import convert  # noqa: E402

APPS = ["tachiyomi", "tachimanga", "aidoku"]
APP_LABELS = {
    "tachiyomi": "Tachiyomi / Mihon / Komikku",
    "tachimanga": "Tachimanga",
    "aidoku": "Aidoku",
}
EMPTY_TEMPLATES = {
    "tachiyomi": ROOT / "app" / "static" / "templates" / "empty_tachiyomi.tachibk",
    "tachimanga": ROOT / "app" / "static" / "templates" / "empty_tachimanga.tmb",
    "aidoku": ROOT / "app" / "static" / "templates" / "empty_aidoku.aib",
}


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--from", dest="source_app", required=True, choices=APPS,
                         help="App the source backup is from")
    parser.add_argument("--to", dest="target_app", required=True, choices=APPS,
                         help="App to convert into")
    parser.add_argument("--source", required=True, type=Path,
                         help="Path to the source backup file")
    parser.add_argument("--target", type=Path, default=None,
                         help="Existing backup from the target app to merge into "
                              "(optional - an empty starter is used if omitted)")
    parser.add_argument("--out", required=True, type=Path,
                         help="Where to write the converted backup")
    args = parser.parse_args()

    if args.source_app == args.target_app:
        sys.exit("Error: --from and --to must be different apps.")
    if not args.source.exists():
        sys.exit(f"Error: source file not found: {args.source}")

    source_bytes = args.source.read_bytes()
    if args.target:
        if not args.target.exists():
            sys.exit(f"Error: target file not found: {args.target}")
        target_bytes = args.target.read_bytes()
        used_blank_target = False
    else:
        target_bytes = EMPTY_TEMPLATES[args.target_app].read_bytes()
        used_blank_target = True

    try:
        out_bytes, report = convert.convert_backup(
            source_bytes, args.source_app, target_bytes, args.target_app
        )
    except Exception as e:
        sys.exit(f"Conversion failed: {e}")

    args.out.write_bytes(out_bytes)

    if used_blank_target:
        print(f"No --target given, merged into a blank {APP_LABELS[args.target_app]} starter.\n")
    print(f"{len(report.manga_converted)} manga newly transferred")
    print(f"{len(report.manga_already_present)} already existed in the target backup")
    print(f"{report.chapters_added} chapters, {report.history_added} history entries added")
    if report.manga_skipped_no_source:
        print(f"\n{len(report.manga_skipped_no_source)} manga not transferable (source not supported on the target app):")
        for title in report.manga_skipped_no_source:
            print(f"  - {title}")
    if report.errors:
        print(f"\n{len(report.errors)} errors on individual entries:")
        for err in report.errors:
            print(f"  - {err}")
    print(f"\nWritten to {args.out}")


if __name__ == "__main__":
    main()
