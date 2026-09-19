"""Clean up a single backup without changing its format: drop entries
missing a url or title (can't be identified as a real work), collapse
duplicate chapters within the same manga (same chapter url twice - keeps
the read one if either copy is marked read), and drop category tags that
point at a category which no longer exists. Read/write each format
natively, same reasoning as dedupe.py.
"""
import gzip
import hashlib
import io
import json
import plistlib
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from . import pb
from .convert import _STRUCTURE_ERRORS, _reencode_tuple, _reraise_as_format_error
from .safety import bounded_gzip_decompress, bounded_zip_read


def _repair_tachibk(data: bytes) -> tuple:
    raw = bounded_gzip_decompress(data)
    top = pb.parse(raw)

    valid_cat_orders = set()
    for f, w, v in top:
        if f == 2:
            d = pb.to_dict(v)
            valid_cat_orders.add(pb.g1(d, 2, 0))

    report = {"broken_entries_removed": 0, "duplicate_chapters_removed": 0, "orphaned_categories_removed": 0}
    kept_top = []

    for f, w, v in top:
        if f != 1:
            kept_top.append((f, w, v))
            continue

        manga_tuples = pb.parse(v)
        d = pb.to_dict(v)
        url = pb.as_str(d[2][0]) if d.get(2) else ""
        title = pb.as_str(d[3][0]) if d.get(3) else ""
        if not url or not title:
            report["broken_entries_removed"] += 1
            continue

        best_chapter_by_url = {}
        for t in manga_tuples:
            if t[0] != 16:
                continue
            cd = pb.to_dict(t[2])
            curl = pb.as_str(cd[1][0]) if cd.get(1) else None
            if curl is None:
                continue
            read = bool(pb.g1(cd, 4, 0))
            existing = best_chapter_by_url.get(curl)
            if existing is None:
                best_chapter_by_url[curl] = t
            else:
                report["duplicate_chapters_removed"] += 1
                if read and not bool(pb.g1(pb.to_dict(existing[2]), 4, 0)):
                    best_chapter_by_url[curl] = t
        valid_chapter_urls = set(best_chapter_by_url.keys())
        kept_chapter_ids = {id(t) for t in best_chapter_by_url.values()}

        kept_manga_tuples = []
        for t in manga_tuples:
            f2 = t[0]
            if f2 == 16:
                if id(t) in kept_chapter_ids:
                    kept_manga_tuples.append(t)
                continue
            if f2 == 104:  # history, keyed by chapter url inside
                hd = pb.to_dict(t[2])
                hurl = pb.as_str(hd[1][0]) if hd.get(1) else None
                if hurl is not None and hurl not in valid_chapter_urls:
                    continue
                kept_manga_tuples.append(t)
                continue
            if f2 == 17:  # category order reference
                if t[2] not in valid_cat_orders:
                    report["orphaned_categories_removed"] += 1
                    continue
                kept_manga_tuples.append(t)
                continue
            kept_manga_tuples.append(t)

        rebuilt = b"".join(_reencode_tuple(f2, w2, v2) for f2, w2, v2 in kept_manga_tuples)
        kept_top.append((1, 2, rebuilt))

    result = gzip.compress(b"".join(_reencode_tuple(f, w, v) for f, w, v in kept_top))
    return result, report


def _repair_tmb(data: bytes) -> tuple:
    from . import tachimanga as tm
    outer = zipfile.ZipFile(io.BytesIO(data))
    contents_zip_bytes = bounded_zip_read(outer, "contents.zip")
    inner_names = zipfile.ZipFile(io.BytesIO(contents_zip_bytes)).namelist()
    db_path_in_zip = "inner/tachimanga.db" if "inner/tachimanga.db" in inner_names else "tachimanga.db"
    inner = zipfile.ZipFile(io.BytesIO(contents_zip_bytes))
    db_bytes = bounded_zip_read(inner, db_path_in_zip)
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp.write(db_bytes)
        tmp_path = tmp.name

    conn = sqlite3.connect(tmp_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    report = {"broken_entries_removed": 0, "duplicate_chapters_removed": 0, "orphaned_categories_removed": 0}

    broken_ids = [r["id"] for r in cur.execute(
        "SELECT id FROM Manga WHERE url IS NULL OR url = '' OR title IS NULL OR title = ''"
    ).fetchall()]
    for mid in broken_ids:
        cur.execute("DELETE FROM Chapter WHERE manga = ?", (mid,))
        cur.execute("DELETE FROM History WHERE manga_id = ?", (mid,))
        cur.execute("DELETE FROM CategoryManga WHERE manga = ?", (mid,))
        cur.execute("DELETE FROM TrackRecord WHERE manga_id = ?", (mid,))
        cur.execute("DELETE FROM Manga WHERE id = ?", (mid,))
    report["broken_entries_removed"] = len(broken_ids)

    for manga_id, url, count in cur.execute(
        "SELECT manga, url, COUNT(*) FROM Chapter GROUP BY manga, url HAVING COUNT(*) > 1"
    ).fetchall():
        rows = cur.execute(
            "SELECT id, read FROM Chapter WHERE manga = ? AND url = ? ORDER BY read DESC, id ASC",
            (manga_id, url),
        ).fetchall()
        for row in rows[1:]:
            cur.execute("DELETE FROM Chapter WHERE id = ?", (row["id"],))
            cur.execute("DELETE FROM History WHERE last_chapter_id = ?", (row["id"],))
            report["duplicate_chapters_removed"] += 1

    orphaned = cur.execute(
        "SELECT CategoryManga.rowid AS rid FROM CategoryManga "
        "LEFT JOIN Category ON Category.id = CategoryManga.category "
        "WHERE Category.id IS NULL"
    ).fetchall()
    for row in orphaned:
        cur.execute("DELETE FROM CategoryManga WHERE rowid = ?", (row["rid"],))
    report["orphaned_categories_removed"] = len(orphaned)

    conn.commit()
    conn.close()
    new_db_bytes = Path(tmp_path).read_bytes()
    Path(tmp_path).unlink(missing_ok=True)

    new_contents_zip = tm._rebuild_zip(contents_zip_bytes, {db_path_in_zip: new_db_bytes})
    checksum = hashlib.sha1(new_contents_zip).hexdigest()
    meta = json.loads(bounded_zip_read(outer, "meta.json"))
    meta["checksum"] = checksum
    meta["size"] = len(new_contents_zip)

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("meta.json", json.dumps(meta, indent=2))
        z.writestr("contents.zip", new_contents_zip)
    return out_buf.getvalue(), report


def _repair_aib(data: bytes) -> tuple:
    AI = plistlib.loads(data)
    report = {"broken_entries_removed": 0, "duplicate_chapters_removed": 0, "orphaned_categories_removed": 0}

    good_manga = []
    broken_keys = set()
    for m in AI.get("manga", []):
        if not m.get("id") or not m.get("title"):
            broken_keys.add((m.get("sourceId"), m.get("id")))
            report["broken_entries_removed"] += 1
        else:
            good_manga.append(m)
    AI["manga"] = good_manga
    if broken_keys:
        AI["library"] = [l for l in AI.get("library", []) if (l["sourceId"], l["mangaId"]) not in broken_keys]
        AI["chapters"] = [c for c in AI.get("chapters", []) if (c["sourceId"], c["mangaId"]) not in broken_keys]
        AI["history"] = [h for h in AI.get("history", []) if (h["sourceId"], h["mangaId"]) not in broken_keys]
        AI["trackItems"] = [t for t in AI.get("trackItems", []) if (t["sourceId"], t["mangaId"]) not in broken_keys]

    seen_chapter_keys = {}
    kept_chapters = []
    for c in AI.get("chapters", []):
        key = (c["sourceId"], c["mangaId"], c["id"])
        if key not in seen_chapter_keys:
            seen_chapter_keys[key] = c
            kept_chapters.append(c)
        else:
            report["duplicate_chapters_removed"] += 1
    AI["chapters"] = kept_chapters

    valid_category_titles = set()
    for c in AI.get("categories", []):
        valid_category_titles.add(c["title"] if isinstance(c, dict) else c)
    for lib in AI.get("library", []):
        original = lib.get("categories", [])
        cleaned = [c for c in original if c in valid_category_titles]
        report["orphaned_categories_removed"] += len(original) - len(cleaned)
        lib["categories"] = cleaned

    return plistlib.dumps(AI, fmt=plistlib.FMT_BINARY), report


_REPAIRERS = {"tachiyomi": _repair_tachibk, "tachimanga": _repair_tmb, "aidoku": _repair_aib}


def analyze_backup(data: bytes, app_name: str) -> dict:
    """Read-only: runs the same logic as repair_backup but discards the
    cleaned bytes, returning only the counts of what would change."""
    try:
        _, report = _REPAIRERS[app_name](data)
    except _STRUCTURE_ERRORS as e:
        _reraise_as_format_error(app_name, e)
    report["app"] = app_name
    report["has_issues"] = any(
        report[k] for k in ("broken_entries_removed", "duplicate_chapters_removed", "orphaned_categories_removed")
    )
    return report


def repair_backup(data: bytes, app_name: str) -> tuple:
    try:
        return _REPAIRERS[app_name](data)
    except _STRUCTURE_ERRORS as e:
        _reraise_as_format_error(app_name, e)
