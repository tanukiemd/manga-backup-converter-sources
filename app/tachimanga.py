"""Read/write Tachimanga (.tmb) backups.

Format (reverse-engineered from a real sample - not publicly documented):
  outer zip: meta.json + contents.zip
  meta.json: {"checksum": sha1(contents.zip) as hex, "size": len(contents.zip), ...}
  contents.zip: tachimanga.db (SQLite) + pref.json + pref-all.json +
                extensions/*.jar + prefs/com.apple.java.util.prefs.plist

tachimanga.db schema is (confirmed against a real export) structurally the
same relational model Tachiyomi/Mihon/Komikku use internally, and - this is
the important part - uses the EXACT SAME numeric source ids and manga/chapter
url conventions, because Tachimanga runs the actual Tachiyomi extension jars.
So converting between .tachibk and .tmb needs no source-id translation at
all; only Aidoku needs the sources.py mapping.
"""
import hashlib
import io
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .model import TachiManga, TachiChapter, TachiHistoryEntry, TachiTrack


def read_tmb(tmb_bytes: bytes):
    """Return (list[TachiManga], raw contents.zip bytes) for library items only."""
    outer = zipfile.ZipFile(io.BytesIO(tmb_bytes))
    contents_zip_bytes = outer.read("contents.zip")
    inner = zipfile.ZipFile(io.BytesIO(contents_zip_bytes))
    db_bytes = inner.read("inner/tachimanga.db") if "inner/tachimanga.db" in inner.namelist() else inner.read("tachimanga.db")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp.write(db_bytes)
        tmp_path = tmp.name

    conn = sqlite3.connect(tmp_path)
    conn.row_factory = sqlite3.Row
    mangas = _read_mangas(conn)
    conn.close()
    Path(tmp_path).unlink(missing_ok=True)

    return mangas, contents_zip_bytes


def _read_mangas(conn):
    cur = conn.cursor()
    cats_by_id = {r["id"]: r["name"] for r in cur.execute("SELECT id, name FROM Category")}
    cat_names_by_manga = {}
    for r in cur.execute("SELECT manga, category FROM CategoryManga"):
        cat_names_by_manga.setdefault(r["manga"], []).append(cats_by_id.get(r["category"]))

    mangas = []
    manga_rows = cur.execute("SELECT * FROM Manga WHERE in_library = 1").fetchall()
    for m in manga_rows:
        sub = conn.cursor()
        chapters = []
        url_by_chapter_id = {}
        for c in sub.execute("SELECT * FROM Chapter WHERE manga = ?", (m["id"],)).fetchall():
            chapters.append(TachiChapter(
                url=c["url"], name=c["name"], scanlator=c["scanlator"],
                read=bool(c["read"]), last_page_read=c["last_page_read"],
                date_upload_ms=c["date_upload"] or None,
                chapter_number=c["chapter_number"], source_order=c["source_order"],
                last_modified_s=(c["update_at"] // 1000) if c["update_at"] else None,
            ))
            url_by_chapter_id[c["id"]] = c["url"]
        history = []
        for h in sub.execute("SELECT * FROM History WHERE manga_id = ?", (m["id"],)).fetchall():
            chapter_url = url_by_chapter_id.get(h["last_chapter_id"])
            if chapter_url is None:
                continue
            history.append(TachiHistoryEntry(
                chapter_url=chapter_url,
                last_read_ms=(h["last_read_at"] or 0) * 1000, read_duration=h["read_duration"] or 0,
            ))
        tracking = []
        for t in sub.execute("SELECT * FROM TrackRecord WHERE manga_id = ? AND sync_id = 2", (m["id"],)).fetchall():
            tracking.append(TachiTrack(sync_id=2, media_id=t["remote_id"], title=t["title"]))

        mangas.append(TachiManga(
            source_id=m["source"], url=m["url"], title=m["title"],
            artist=m["artist"], author=m["author"], description=m["description"],
            genres=[g.strip() for g in (m["genre"] or "").split(",") if g.strip()],
            status=m["status"], thumbnail_url=m["thumbnail_url"],
            date_added_ms=(m["in_library_at"] * 1000) if m["in_library_at"] else None,
            categories=[c for c in cat_names_by_manga.get(m["id"], []) if c],
            chapters=chapters, history=history, tracking=tracking,
        ))
    return mangas


def write_into_tmb(target_tmb_bytes: bytes, new_mangas: list) -> bytes:
    """Merge new_mangas into an existing Tachimanga backup, return new .tmb bytes."""
    outer = zipfile.ZipFile(io.BytesIO(target_tmb_bytes))
    contents_zip_bytes = outer.read("contents.zip")
    inner_names = zipfile.ZipFile(io.BytesIO(contents_zip_bytes)).namelist()
    db_path_in_zip = "inner/tachimanga.db" if "inner/tachimanga.db" in inner_names else "tachimanga.db"

    inner = zipfile.ZipFile(io.BytesIO(contents_zip_bytes))
    db_bytes = inner.read(db_path_in_zip)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp.write(db_bytes)
        tmp_path = tmp.name

    conn = sqlite3.connect(tmp_path)
    conn.row_factory = sqlite3.Row
    report = _merge_mangas(conn, new_mangas)
    conn.commit()
    conn.close()

    new_db_bytes = Path(tmp_path).read_bytes()
    Path(tmp_path).unlink(missing_ok=True)

    new_contents_zip = _rebuild_zip(contents_zip_bytes, {db_path_in_zip: new_db_bytes})

    checksum = hashlib.sha1(new_contents_zip).hexdigest()
    meta = json.loads(outer.read("meta.json"))
    meta["checksum"] = checksum
    meta["size"] = len(new_contents_zip)

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("meta.json", json.dumps(meta, indent=2))
        z.writestr("contents.zip", new_contents_zip)
    return out_buf.getvalue(), report


def _rebuild_zip(original_zip_bytes: bytes, replacements: dict) -> bytes:
    original = zipfile.ZipFile(io.BytesIO(original_zip_bytes))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in original.namelist():
            data = replacements.get(name, None)
            if data is None:
                data = original.read(name)
            z.writestr(name, data)
    return buf.getvalue()


STATUS_UNIVERSAL_TO_TACHI = {1: 1, 2: 2, 3: 5, 4: 6}  # from Aidoku-style status ints


def _merge_mangas(conn, new_mangas):
    from .convert import ConversionReport
    report = ConversionReport()
    cur = conn.cursor()

    existing = {(r["source"], r["url"]) for r in cur.execute("SELECT source, url FROM Manga")}
    cat_id_by_name = {r["name"]: r["id"] for r in cur.execute("SELECT id, name FROM Category")}
    max_cat_order = cur.execute("SELECT COALESCE(MAX(\"order\"), -1) FROM Category").fetchone()[0]

    for manga in new_mangas:
        key = (manga.source_id, manga.url)
        if key in existing:
            report.manga_already_present.append(manga.title)
            continue

        now_ms = _now_ms()
        cur.execute(
            "INSERT INTO Manga (url, title, initialized, artist, author, description, genre, "
            "status, thumbnail_url, in_library, default_category, in_library_at, source, "
            "create_at, update_at, dirty) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
            (manga.url, manga.title, 1, manga.artist, manga.author, manga.description,
             ", ".join(manga.genres), manga.status or 0, manga.thumbnail_url, 1,
             0 if manga.categories else 1,
             (manga.date_added_ms // 1000) if manga.date_added_ms else (now_ms // 1000),
             manga.source_id, now_ms, now_ms),
        )
        manga_id = cur.lastrowid
        report.manga_converted.append(manga.title)

        chapter_id_by_url = {}
        for ch in manga.chapters:
            cur.execute(
                "INSERT INTO Chapter (url, name, date_upload, chapter_number, scanlator, "
                "read, last_page_read, source_order, manga, create_at, update_at, dirty) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                (ch.url, ch.name, ch.date_upload_ms or 0, ch.chapter_number or -1.0,
                 ch.scanlator, int(ch.read), ch.last_page_read or 0, ch.source_order,
                 manga_id, now_ms, now_ms),
            )
            chapter_id_by_url[ch.url] = cur.lastrowid
            report.chapters_added += 1

        for h in manga.history:
            last_chapter_id = chapter_id_by_url.get(h.chapter_url)
            if last_chapter_id is None:
                continue
            cur.execute(
                "INSERT INTO History (create_at, update_at, manga_id, last_chapter_id, "
                "last_read_at, read_duration, dirty) VALUES (?,?,?,?,?,?,1)",
                (now_ms, now_ms, manga_id, last_chapter_id, (h.last_read_ms or 0) // 1000, h.read_duration),
            )
            report.history_added += 1

        for cat_name in manga.categories:
            if cat_name not in cat_id_by_name:
                max_cat_order += 1
                cur.execute(
                    "INSERT INTO Category (name, \"order\", create_at, update_at, dirty) "
                    "VALUES (?,?,?,?,1)", (cat_name, max_cat_order, now_ms, now_ms),
                )
                cat_id_by_name[cat_name] = cur.lastrowid
            cur.execute(
                "INSERT INTO CategoryManga (category, manga) VALUES (?,?)",
                (cat_id_by_name[cat_name], manga_id),
            )

        for t in manga.tracking:
            if t.sync_id != 2:
                continue
            cur.execute(
                "INSERT INTO TrackRecord (manga_id, sync_id, remote_id, title, "
                "last_chapter_read, total_chapters, status, score, remote_url, "
                "start_date, finish_date, create_at, update_at, dirty) "
                "VALUES (?,?,?,?,0,0,0,0,'',0,0,?,?,1)",
                (manga_id, t.sync_id, t.media_id, t.title, now_ms, now_ms),
            )

    return report


def _now_ms():
    import time
    return int(time.time() * 1000)
