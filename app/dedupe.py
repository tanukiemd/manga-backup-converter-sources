"""Find the same manga tracked from multiple different sources within ONE
backup (e.g. added once via MangaDex, once via AsuraScans), suggest which
entry to keep (most chapters read, tied-broken by most recently read), and
produce a cleaned backup with the user's chosen duplicates removed.

Same format in, same format out - no cross-app conversion, no source-ID
mapping involved. Deliberately reads/writes each format NATIVELY (not
through the shared TachiManga model in convert.py) because Aidoku's native
identity is (sourceId, mangaId), not the translated Tachiyomi-side url that
read_aidoku() in convert.py produces for cross-app conversion - and that
function also silently drops any manga with no known source mapping, which
would be wrong here (duplicates can exist regardless of mapping status).
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


class _NativeEntry:
    def __init__(self, key, title, chapters_read, last_read_ms):
        self.key = key
        self.title = title
        self.chapters_read = chapters_read
        self.last_read_ms = last_read_ms or 0


# ---------------------------------------------------------------------------
# native readers: (source_id-or-sourceId, url-or-mangaId) -> entry, per format
# ---------------------------------------------------------------------------

def _read_native_tachibk(data: bytes) -> list:
    raw = bounded_gzip_decompress(data)
    top = pb.parse(raw)
    entries = []
    for f, w, v in top:
        if f != 1:
            continue
        d = pb.to_dict(v)
        if not bool(pb.g1(d, 100, 1)):  # favorite, defaults to true when absent
            continue
        chs = [pb.to_dict(c) for c in d.get(16, [])]
        chapters_read = sum(1 for c in chs if bool(pb.g1(c, 4, 0)))
        hist = [pb.to_dict(h) for h in d.get(104, [])]
        last_read = max((pb.g1(h, 2, 0) or 0 for h in hist), default=0)
        entries.append(_NativeEntry(
            (pb.g1(d, 1, 0), pb.as_str(d[2][0])), pb.as_str(d[3][0]),
            chapters_read, last_read,
        ))
    return entries


def _read_native_tmb(data: bytes) -> list:
    outer = zipfile.ZipFile(io.BytesIO(data))
    contents_zip_bytes = bounded_zip_read(outer, "contents.zip")
    inner = zipfile.ZipFile(io.BytesIO(contents_zip_bytes))
    db_name = "inner/tachimanga.db" if "inner/tachimanga.db" in inner.namelist() else "tachimanga.db"
    db_bytes = bounded_zip_read(inner, db_name)
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp.write(db_bytes)
        tmp_path = tmp.name
    conn = sqlite3.connect(tmp_path)
    conn.row_factory = sqlite3.Row
    entries = []
    for m in conn.execute("SELECT * FROM Manga WHERE in_library = 1").fetchall():
        chapters_read = conn.execute(
            "SELECT COUNT(*) FROM Chapter WHERE manga = ? AND read = 1", (m["id"],)
        ).fetchone()[0]
        last_read_s = conn.execute(
            "SELECT MAX(last_read_at) FROM History WHERE manga_id = ?", (m["id"],)
        ).fetchone()[0] or 0
        entries.append(_NativeEntry((m["source"], m["url"]), m["title"], chapters_read, last_read_s * 1000))
    conn.close()
    Path(tmp_path).unlink(missing_ok=True)
    return entries


def _read_native_aib(data: bytes) -> list:
    AI = plistlib.loads(data)
    read_chapters = {}
    last_read = {}
    for h in AI.get("history", []):
        key = (h["sourceId"], h["mangaId"])
        if h.get("completed"):
            read_chapters.setdefault(key, set()).add(h.get("chapterId"))
        when = h.get("dateRead")
        if when:
            ts = when.timestamp() * 1000
            last_read[key] = max(last_read.get(key, 0), ts)
    entries = []
    for m in AI.get("manga", []):
        key = (m["sourceId"], m["id"])
        entries.append(_NativeEntry(
            key, m.get("title", "(untitled)"),
            len(read_chapters.get(key, ())), last_read.get(key, 0),
        ))
    return entries


# ---------------------------------------------------------------------------
# native "remove these entries, keep everything else" writers, per format
# ---------------------------------------------------------------------------

def _remove_from_tachibk(data: bytes, keys_to_remove: set) -> bytes:
    raw = bounded_gzip_decompress(data)
    top = pb.parse(raw)
    kept = []
    for f, w, v in top:
        if f == 1:
            d = pb.to_dict(v)
            if (pb.g1(d, 1, 0), pb.as_str(d[2][0])) in keys_to_remove:
                continue
        kept.append((f, w, v))
    return gzip.compress(b"".join(_reencode_tuple(f, w, v) for f, w, v in kept))


def _remove_from_tmb(data: bytes, keys_to_remove: set) -> bytes:
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
    cur = conn.cursor()
    ids_to_delete = []
    for source, url in keys_to_remove:
        ids_to_delete += [r[0] for r in cur.execute(
            "SELECT id FROM Manga WHERE source = ? AND url = ?", (source, url)
        ).fetchall()]
    for mid in ids_to_delete:
        cur.execute("DELETE FROM Chapter WHERE manga = ?", (mid,))
        cur.execute("DELETE FROM History WHERE manga_id = ?", (mid,))
        cur.execute("DELETE FROM CategoryManga WHERE manga = ?", (mid,))
        cur.execute("DELETE FROM TrackRecord WHERE manga_id = ?", (mid,))
        cur.execute("DELETE FROM Manga WHERE id = ?", (mid,))
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
    return out_buf.getvalue()


def _remove_from_aib(data: bytes, keys_to_remove: set) -> bytes:
    AI = plistlib.loads(data)

    def kept(seq, key_fn):
        return [x for x in seq if key_fn(x) not in keys_to_remove]

    AI["manga"] = kept(AI.get("manga", []), lambda m: (m["sourceId"], m["id"]))
    AI["library"] = kept(AI.get("library", []), lambda l: (l["sourceId"], l["mangaId"]))
    AI["chapters"] = kept(AI.get("chapters", []), lambda c: (c["sourceId"], c["mangaId"]))
    AI["history"] = kept(AI.get("history", []), lambda h: (h["sourceId"], h["mangaId"]))
    AI["trackItems"] = kept(AI.get("trackItems", []), lambda t: (t["sourceId"], t["mangaId"]))
    return plistlib.dumps(AI, fmt=plistlib.FMT_BINARY)


_READERS = {"tachiyomi": _read_native_tachibk, "tachimanga": _read_native_tmb, "aidoku": _read_native_aib}
_REMOVERS = {"tachiyomi": _remove_from_tachibk, "tachimanga": _remove_from_tmb, "aidoku": _remove_from_aib}


def find_duplicates(data: bytes, app_name: str) -> dict:
    """Groups of manga sharing a normalized title (2+ entries), each with a
    suggested keeper index - most chapters read, tie-broken by most
    recently read. The frontend lets the user override the suggestion."""
    try:
        entries = _READERS[app_name](data)
    except _STRUCTURE_ERRORS as e:
        _reraise_as_format_error(app_name, e)

    by_title = {}
    for e in entries:
        by_title.setdefault(e.title.strip().lower(), []).append(e)

    groups = []
    for group in by_title.values():
        if len(group) < 2:
            continue
        best = max(group, key=lambda e: (e.chapters_read, e.last_read_ms))
        groups.append({
            "title": group[0].title,
            "entries": [
                {"key": list(e.key), "chapters_read": e.chapters_read, "last_read_ms": e.last_read_ms}
                for e in group
            ],
            "suggested_keeper": group.index(best),
        })
    groups.sort(key=lambda g: g["title"].lower())
    return {"app": app_name, "total_manga": len(entries), "duplicate_groups": groups}


def remove_duplicates(data: bytes, app_name: str, keys_to_remove: list) -> bytes:
    """keys_to_remove: list of [a, b] pairs as returned by find_duplicates
    (JSON round-trips tuples as lists, hence the tuple() conversion)."""
    keyset = {tuple(k) for k in keys_to_remove}
    try:
        return _REMOVERS[app_name](data, keyset)
    except _STRUCTURE_ERRORS as e:
        _reraise_as_format_error(app_name, e)
