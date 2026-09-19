#!/usr/bin/env python3
"""Helper for contributing a new source mapping to app/sources.py (see
README: "Contributing a new source").

Give it a Tachiyomi-ecosystem backup and an Aidoku backup that both
contain the SAME manga added from the SAME source, and it matches them up
by title and lines up the raw URLs/IDs side by side - the tedious part of
figuring out a SourceMapping by hand. For a few common id patterns (last
URL segment, before/after a "-" or ".") it also checks whether that
pattern holds across every matched pair and, if so, prints ready-to-adapt
Python code.

This tool does NOT invent an untested mapping and add it to sources.py by
itself - always verify the generated code against more than one manga
before submitting a PR, and prefer chapter URLs too if the pattern isn't
obvious from manga URLs alone.

Usage:
    python diff_tool.py --tachi library.tachibk --aidoku library.aib
"""
import argparse
import plistlib
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from app import convert  # noqa: E402

CANDIDATE_EXTRACTORS = [
    ("last URL path segment",
     lambda u: u.rstrip("/").split("/")[-1],
     'tachi_url.rstrip("/").split("/")[-1]'),
    ("last path segment, part after last '.'",
     lambda u: u.rstrip("/").split("/")[-1].rsplit(".", 1)[-1],
     'tachi_url.rstrip("/").split("/")[-1].rsplit(".", 1)[-1]'),
    ("last path segment, part before first '-'",
     lambda u: u.rstrip("/").split("/")[-1].split("-", 1)[0],
     'tachi_url.rstrip("/").split("/")[-1].split("-", 1)[0]'),
    ("second-to-last URL path segment",
     lambda u: u.rstrip("/").split("/")[-2] if u.rstrip("/").count("/") >= 1 else None,
     'tachi_url.rstrip("/").split("/")[-2]'),
    ("whole URL unchanged",
     lambda u: u,
     'tachi_url'),
]


def read_aidoku_raw_manga(aib_bytes):
    AI = plistlib.loads(aib_bytes)
    out = []
    for m in AI.get("manga", []):
        out.append({
            "sourceId": m.get("sourceId"),
            "id": m.get("id"),
            "title": m.get("title", ""),
            "url": m.get("url", ""),
        })
    return out


def normalize(title):
    return " ".join(title.lower().split())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tachi", required=True, type=Path, help="Tachiyomi/Mihon/Komikku .tachibk backup")
    parser.add_argument("--aidoku", required=True, type=Path, help="Aidoku .aib backup")
    args = parser.parse_args()

    tachi_mangas = convert.read_tachibk(args.tachi.read_bytes())
    aidoku_mangas = read_aidoku_raw_manga(args.aidoku.read_bytes())

    aidoku_by_title = {}
    for m in aidoku_mangas:
        aidoku_by_title.setdefault(normalize(m["title"]), []).append(m)

    matched = []
    unmatched_tachi = []
    for tm in tachi_mangas:
        candidates = aidoku_by_title.get(normalize(tm.title), [])
        if len(candidates) == 1:
            matched.append((tm, candidates[0]))
        else:
            unmatched_tachi.append(tm.title)

    if not matched:
        print("No manga titles matched between the two backups. Make sure you added")
        print("the same manga (same source) to your library in both apps first.")
        return

    by_aidoku_source = {}
    for tm, am in matched:
        by_aidoku_source.setdefault(am["sourceId"], []).append((tm, am))

    for aidoku_source_id, pairs in by_aidoku_source.items():
        tachi_source_ids = {tm.source_id for tm, am in pairs}
        print(f"\n=== Aidoku source '{aidoku_source_id}' <-> Tachi source_id(s) {tachi_source_ids} ===")
        print(f"{len(pairs)} matched manga:\n")
        for tm, am in pairs:
            print(f"  {tm.title}")
            print(f"    tachi url:   {tm.url}")
            print(f"    aidoku id:   {am['id']}")
            print(f"    aidoku url:  {am['url']}")

        print("\n  Checking for a consistent id pattern...")
        found_any = False
        for name, fn, code in CANDIDATE_EXTRACTORS:
            try:
                if all(fn(tm.url) == am["id"] for tm, am in pairs):
                    found_any = True
                    print(f"\n  MATCH: manga id = {name}")
                    print(f"\n    def _mymapping_manga_id(tachi_url: str) -> str:")
                    print(f"        return {code}\n")
            except Exception:
                continue
        if not found_any:
            print("  No simple pattern matched across all pairs - inspect the URLs above by hand,")
            print("  and check chapter URLs too (python diff_tool.py only compares manga urls/ids).")

    if unmatched_tachi:
        print(f"\n{len(unmatched_tachi)} manga from the Tachi-side backup had no title match in the Aidoku backup "
              f"(different source, or not added to both libraries) - ignored:")
        for t in unmatched_tachi[:20]:
            print(f"  - {t}")


if __name__ == "__main__":
    main()
