"""Readers/writers that move manga library data between:
  - .tachibk  (Tachiyomi / Mihon / Komikku - protobuf+gzip)
  - .tmb      (Tachimanga - SQLite in a zip, see tachimanga.py)
  - .aib      (Aidoku - binary plist)

via the shared TachiManga model (model.py). Tachiyomi-ecosystem <-> Tachimanga
needs no source-id translation (same ids, same url conventions - Tachimanga
runs the real Tachiyomi extension jars). Aidoku always goes through the
SourceMapping registry in sources.py.

Design decision: every writer merges into an existing backup from the
*target* app rather than fabricating one from scratch - see the note in the
old version of this file / project notes for why (undocumented internal
fields in both Aidoku's and Tachiyomi's backup schemas).
"""
import gzip
import re
import datetime as dt
from collections import defaultdict

import plistlib

from . import pb
from .model import TachiManga, TachiChapter, TachiHistoryEntry, TachiTrack
from .sources import BY_TACHI_SOURCE_ID, BY_AIDOKU_ID

UTC = dt.timezone.utc
STATUS_TACHI_TO_AIDOKU = {1: 1, 2: 2, 4: 2, 5: 3, 6: 4}
STATUS_AIDOKU_TO_TACHI = {1: 1, 2: 2, 3: 5, 4: 6}


def _ms_to_dt(x):
    return dt.datetime.fromtimestamp(x / 1000, UTC).replace(tzinfo=None)


def _dt_to_ms(d):
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return int(d.timestamp() * 1000)


def _sec_to_dt(x):
    return dt.datetime.fromtimestamp(x, UTC).replace(tzinfo=None)


class ConversionReport:
    def __init__(self):
        self.manga_converted = []
        self.manga_skipped_no_source = []
        self.manga_already_present = []
        self.chapters_added = 0
        self.history_added = 0
        self.errors = []

    def as_dict(self):
        return {
            "manga_converted": self.manga_converted,
            "manga_skipped_no_source": self.manga_skipped_no_source,
            "manga_already_present": self.manga_already_present,
            "chapters_added": self.chapters_added,
            "history_added": self.history_added,
            "errors": self.errors,
        }


def _reencode_tuple(field, wire, value):
    if wire == 0:
        return pb.enc_tag(field, 0) + pb.enc_varint(value)
    if wire == 2:
        return pb.enc_tag(field, 2) + pb.enc_varint(len(value)) + value
    if wire == 5:
        return pb.enc_tag(field, 5) + value
    if wire == 1:
        return pb.enc_tag(field, 1) + value
    raise ValueError(f"unsupported wire type {wire}")


def _split_title(name):
    vol = None
    m = re.match(r"^Vol\.\s*([\d.]+)\s+", name)
    if m:
        vol = float(m.group(1))
        name = name[m.end():]
    m = re.match(r"^Ch(?:apter|\.)\s*[\d.]+\s*(?:[:\-]\s*(.*))?$", name)
    if m:
        return vol, (m.group(1) or "").strip() or None
    return vol, name


def _nsfw_viewer(genres):
    gl = {g.lower() for g in genres}
    nsfw = 2 if gl & {"adult", "hentai", "smut", "pornographic", "erotica", "mature"} else (
        1 if gl & {"ecchi", "suggestive"} else 0)
    return nsfw, gl


# ---------------------------------------------------------------------------
# .tachibk (Tachiyomi / Mihon / Komikku)
# ---------------------------------------------------------------------------

def read_tachibk(tachibk_bytes: bytes) -> list:
    raw = gzip.decompress(tachibk_bytes)
    top = pb.parse(raw)

    catname_by_order = {}
    for f, w, v in top:
        if f == 2:
            d = pb.to_dict(v)
            catname_by_order[pb.g1(d, 2, 0)] = pb.as_str(d[1][0])

    mangas = []
    for f, w, v in top:
        if f != 1:
            continue
        d = pb.to_dict(v)
        if not bool(pb.g1(d, 100, 1)):  # favorite, defaults to true when absent
            continue

        chs_raw = [pb.to_dict(c) for c in d.get(16, [])]
        hist_by_url = {pb.as_str(pb.to_dict(h)[1][0]): pb.to_dict(h) for h in d.get(104, [])}

        chapters, history = [], []
        for c in chs_raw:
            u = pb.as_str(c[1][0])
            read = bool(pb.g1(c, 4, 0))
            page = pb.g1(c, 6, 0)
            chapters.append(TachiChapter(
                url=u, name=pb.as_str(c[2][0]),
                scanlator=pb.as_str(c[3][0]) if c.get(3) else None,
                read=read, last_page_read=page,
                date_upload_ms=pb.g1(c, 8),
                chapter_number=pb.as_float(c[9][0]) if c.get(9) else None,
                source_order=pb.g1(c, 10, 0),
                last_modified_s=pb.g1(c, 11),
            ))
            if read or page:
                h = hist_by_url.get(u)
                when_ms = (pb.g1(h, 2) if h and pb.g1(h, 2) else
                           (pb.g1(c, 11) * 1000 if pb.g1(c, 11) else pb.g1(c, 7)))
                history.append(TachiHistoryEntry(
                    chapter_url=u, last_read_ms=when_ms or 0,
                    read_duration=pb.g1(h, 3, 0) if h else 0,
                ))

        tracking = []
        for t in d.get(18, []):
            t = pb.to_dict(t)
            if pb.g1(t, 1) == 2:
                media_id = pb.g1(t, 100) or pb.g1(t, 3)
                if media_id is not None:
                    tracking.append(TachiTrack(
                        sync_id=2, media_id=media_id,
                        title=pb.as_str(t[5][0]) if t.get(5) else pb.as_str(d[3][0]),
                    ))

        mangas.append(TachiManga(
            source_id=pb.g1(d, 1, 0), url=pb.as_str(d[2][0]), title=pb.as_str(d[3][0]),
            artist=pb.as_str(d[4][0]) if d.get(4) else None,
            author=pb.as_str(d[5][0]) if d.get(5) else None,
            description=pb.as_str(d[6][0]) if d.get(6) else None,
            genres=[pb.as_str(x) for x in d.get(7, [])],
            status=pb.g1(d, 8, 0),
            thumbnail_url=pb.as_str(d[9][0]) if d.get(9) else None,
            date_added_ms=pb.g1(d, 13),
            categories=[catname_by_order[c] for c in d.get(17, []) if c in catname_by_order],
            chapters=chapters, history=history, tracking=tracking,
        ))
    return mangas


def write_into_tachibk(target_tachibk_bytes: bytes, mangas: list):
    report = ConversionReport()
    target_raw = gzip.decompress(target_tachibk_bytes)
    top = pb.parse(target_raw)

    cats = []
    for f, w, v in top:
        if f == 2:
            d = pb.to_dict(v)
            cats.append({"order": pb.g1(d, 2, 0), "id": pb.g1(d, 3, 0), "name": pb.as_str(d[1][0])})
    cat_order_by_name = {c["name"]: c["order"] for c in cats}
    next_order = max([c["order"] for c in cats], default=-1) + 1
    next_id = max([c["id"] for c in cats], default=0) + 1

    have_manga_keys = set()
    for f, w, v in top:
        if f == 1:
            d = pb.to_dict(v)
            have_manga_keys.add((pb.g1(d, 1, 0), pb.as_str(d[2][0])))

    new_category_blobs, new_manga_blobs = [], []

    for manga in mangas:
        if (manga.source_id, manga.url) in have_manga_keys:
            report.manga_already_present.append(manga.title)
            continue

        cat_orders = []
        for cn in manga.categories:
            if cn not in cat_order_by_name:
                cat_order_by_name[cn] = next_order
                new_category_blobs.append(pb.enc_message(2,
                    pb.enc_str_field(1, cn) + pb.enc_varint_field(2, next_order) + pb.enc_varint_field(3, next_id)))
                next_order += 1
                next_id += 1
            cat_orders.append(cat_order_by_name[cn])

        buf = bytearray()
        buf += pb.enc_varint_field(1, manga.source_id)
        buf += pb.enc_str_field(2, manga.url)
        buf += pb.enc_str_field(3, manga.title)
        if manga.artist:
            buf += pb.enc_str_field(4, manga.artist)
        if manga.author:
            buf += pb.enc_str_field(5, manga.author)
        if manga.description:
            buf += pb.enc_str_field(6, manga.description)
        for g in manga.genres:
            buf += pb.enc_str_field(7, g)
        buf += pb.enc_varint_field(8, manga.status or 0)
        if manga.thumbnail_url:
            buf += pb.enc_str_field(9, manga.thumbnail_url)
        if manga.date_added_ms:
            buf += pb.enc_varint_field(13, manga.date_added_ms)

        for ch in manga.chapters:
            cbuf = bytearray()
            cbuf += pb.enc_str_field(1, ch.url)
            cbuf += pb.enc_str_field(2, ch.name)
            if ch.scanlator:
                cbuf += pb.enc_str_field(3, ch.scanlator)
            cbuf += pb.enc_varint_field(4, 1 if ch.read else 0)
            if ch.last_page_read:
                cbuf += pb.enc_varint_field(6, ch.last_page_read)
            if ch.date_upload_ms:
                cbuf += pb.enc_varint_field(8, ch.date_upload_ms)
            if ch.chapter_number is not None:
                cbuf += pb.enc_float_field(9, float(ch.chapter_number))
            cbuf += pb.enc_varint_field(10, ch.source_order or 0)
            buf += pb.enc_message(16, bytes(cbuf))
            report.chapters_added += 1

        for h in manga.history:
            hbuf = pb.enc_str_field(1, h.chapter_url) + pb.enc_varint_field(2, h.last_read_ms or 0)
            if h.read_duration:
                hbuf += pb.enc_varint_field(3, h.read_duration)
            buf += pb.enc_message(104, hbuf)
            report.history_added += 1

        for cat_order in cat_orders:
            buf += pb.enc_varint_field(17, cat_order)

        for t in manga.tracking:
            if t.sync_id != 2:
                continue
            tbuf = pb.enc_varint_field(1, 2) + pb.enc_str_field(5, t.title)
            try:
                tbuf += pb.enc_varint_field(100, int(t.media_id))
            except (TypeError, ValueError):
                pass
            buf += pb.enc_message(18, bytes(tbuf))

        new_manga_blobs.append(pb.enc_message(1, bytes(buf)))
        report.manga_converted.append(manga.title)

    original_reencoded = b"".join(_reencode_tuple(f, w, v) for f, w, v in top)
    result = original_reencoded + b"".join(new_category_blobs) + b"".join(new_manga_blobs)
    return gzip.compress(result), report


# ---------------------------------------------------------------------------
# .aib (Aidoku)
# ---------------------------------------------------------------------------

def read_aidoku(aib_bytes: bytes):
    """Returns (list[TachiManga], skipped_titles)."""
    AI = plistlib.loads(aib_bytes)
    lib_by_key = {(l["sourceId"], l["mangaId"]): l for l in AI.get("library", [])}
    chapters_by_manga = defaultdict(list)
    for c in AI.get("chapters", []):
        chapters_by_manga[(c["sourceId"], c["mangaId"])].append(c)
    history_by_manga = defaultdict(list)
    for h in AI.get("history", []):
        history_by_manga[(h["sourceId"], h["mangaId"])].append(h)
    track_by_manga = defaultdict(list)
    for t in AI.get("trackItems", []):
        track_by_manga[(t["sourceId"], t["mangaId"])].append(t)

    mangas, skipped = [], []
    for m in AI.get("manga", []):
        title = m.get("title", "(untitled)")
        mapping = BY_AIDOKU_ID.get(m["sourceId"])
        if mapping is None:
            skipped.append(title)
            continue

        tachi_source_id = next(iter(mapping.tachi_source_ids))
        tachi_url = mapping.aidoku_manga_url_from_id(m["id"], m.get("url", ""))
        lib = lib_by_key.get((m["sourceId"], m["id"]))

        chapters, url_by_id = [], {}
        for c in chapters_by_manga.get((m["sourceId"], m["id"]), []):
            churl = c.get("url") or mapping.aidoku_chapter_url_from_id(c["id"])
            chapters.append(TachiChapter(
                url=churl,
                name=c.get("title") or f"Chapter {c.get('chapter', '')}".strip(),
                scanlator=c.get("scanlator"),
                date_upload_ms=_dt_to_ms(c["dateUploaded"]) if c.get("dateUploaded") else None,
                chapter_number=c.get("chapter"),
                source_order=c.get("sourceOrder", 0),
            ))
            url_by_id[c["id"]] = churl

        history, read_urls = [], set()
        for h in history_by_manga.get((m["sourceId"], m["id"]), []):
            churl = url_by_id.get(h["chapterId"])
            if churl is None:
                continue
            if h.get("completed"):
                read_urls.add(churl)
            history.append(TachiHistoryEntry(
                chapter_url=churl,
                last_read_ms=_dt_to_ms(h["dateRead"]) if h.get("dateRead") else 0,
            ))
        for ch in chapters:
            ch.read = ch.url in read_urls

        tracking = []
        for t in track_by_manga.get((m["sourceId"], m["id"]), []):
            if t.get("trackerId") != "anilist":
                continue
            try:
                media_id = int(t["id"])
            except (KeyError, ValueError):
                continue
            tracking.append(TachiTrack(sync_id=2, media_id=media_id, title=t.get("title", title)))

        mangas.append(TachiManga(
            source_id=tachi_source_id, url=tachi_url, title=title,
            artist=m.get("artist"), author=m.get("author"), description=m.get("desc"),
            genres=m.get("tags") or [],
            status=STATUS_AIDOKU_TO_TACHI.get(m.get("status", 0), 0),
            thumbnail_url=m.get("cover"),
            date_added_ms=_dt_to_ms(lib["dateAdded"]) if lib and lib.get("dateAdded") else None,
            categories=lib["categories"] if lib else [],
            chapters=chapters, history=history, tracking=tracking,
        ))
    return mangas, skipped


def write_into_aidoku(target_aib_bytes: bytes, mangas: list):
    report = ConversionReport()
    AI = plistlib.loads(target_aib_bytes)
    for key in ("library", "history", "manga", "chapters", "trackItems", "categories"):
        AI.setdefault(key, [])

    have_manga = {(m["sourceId"], m["id"]) for m in AI["manga"]}
    have_lib = {(l["sourceId"], l["mangaId"]): l for l in AI["library"]}
    have_ch = {(c["sourceId"], c["mangaId"], c["id"]) for c in AI["chapters"]}
    have_hist = {(h["sourceId"], h["mangaId"], h["chapterId"]) for h in AI["history"]}
    have_trk = {(t["sourceId"], t["mangaId"], t["trackerId"]) for t in AI["trackItems"]}
    # AI["categories"] holds category objects ({"title","sort","group"}), not
    # plain strings (confirmed against a real 0.9 backup - differs from what
    # the original project notes assumed). library[].categories are plain
    # title strings though. Keep the original objects around so existing
    # "sort"/"group" values survive, and work with titles for comparisons.
    category_objs_by_title = {
        (c["title"] if isinstance(c, dict) else c): c for c in AI["categories"]
    }
    all_categories = list(category_objs_by_title.keys())
    # Same story as categories: most entries are plain source-id strings, but
    # e.g. the "local" source is a richer {"id","apiVersion","config"} object
    # (confirmed against a real backup) - normalize for comparison, keep
    # original entries as-is when writing back.
    source_entries = AI.get("sources", [])
    existing_source_ids = {(s["id"] if isinstance(s, dict) else s) for s in source_entries}
    used_source_ids = set()
    new = defaultdict(list)

    for manga in mangas:
        mapping = BY_TACHI_SOURCE_ID.get(manga.source_id)
        if mapping is None:
            report.manga_skipped_no_source.append(manga.title)
            continue

        try:
            if mapping.name == "Comix":
                mid = mapping.tachi_to_aidoku_manga_id(manga.url, [c.url for c in manga.chapters])
            else:
                mid = mapping.tachi_to_aidoku_manga_id(manga.url)
        except Exception as e:
            report.errors.append(f"{manga.title}: id mapping failed ({e})")
            continue

        sid = mapping.aidoku_id
        key = (sid, mid)
        used_source_ids.add(sid)
        nsfw, gl = _nsfw_viewer(manga.genres)
        viewer = 4 if gl & {"manhwa", "manhua", "webtoon", "long strip"} else 1

        if key not in have_manga:
            m = {"id": mid, "sourceId": sid, "title": manga.title}
            if manga.author:
                m["author"] = manga.author
            if manga.artist:
                m["artist"] = manga.artist
            if manga.description:
                m["desc"] = manga.description
            m["tags"] = manga.genres
            if manga.thumbnail_url:
                m["cover"] = manga.thumbnail_url
            if mapping.tachi_to_aidoku_manga_url is not None:
                aidoku_url = mapping.tachi_to_aidoku_manga_url(manga.url, [c.url for c in manga.chapters])
            else:
                aidoku_url = mapping.aidoku_manga_url_from_id(mid)
            m.update({
                "url": aidoku_url, "status": STATUS_TACHI_TO_AIDOKU.get(manga.status, 0),
                "nsfw": nsfw, "viewer": viewer, "neverUpdate": False, "chapterFlags": 0, "editedKeys": 0,
            })
            new["manga"].append(m)
            report.manga_converted.append(manga.title)
        else:
            report.manga_already_present.append(manga.title)

        for ch in manga.chapters:
            try:
                cid = mapping.tachi_to_aidoku_chapter_id(ch.url)
            except Exception:
                continue
            if (sid, mid, cid) in have_ch:
                continue
            vol, chtitle = _split_title(ch.name)
            entry = {"sourceId": sid, "mangaId": mid, "id": cid}
            if chtitle:
                entry["title"] = chtitle
            if ch.scanlator:
                entry["scanlator"] = ch.scanlator
            entry["url"] = ch.url
            entry["lang"] = "en"
            if ch.chapter_number is not None:
                entry["chapter"] = ch.chapter_number
            if vol is not None:
                entry["volume"] = vol
            if ch.date_upload_ms:
                entry["dateUploaded"] = _ms_to_dt(ch.date_upload_ms)
            entry["locked"] = False
            entry["sourceOrder"] = ch.source_order
            new["chapters"].append(entry)
            report.chapters_added += 1

        lastread, lastchap = None, None
        for h in manga.history:
            try:
                cid = mapping.tachi_to_aidoku_chapter_id(h.chapter_url)
            except Exception:
                continue
            when = _ms_to_dt(h.last_read_ms) if h.last_read_ms else None
            if when and (lastread is None or when > lastread):
                lastread = when
            if (sid, mid, cid) in have_hist:
                continue
            new["history"].append({
                "dateRead": when or dt.datetime.now(UTC).replace(tzinfo=None),
                "sourceId": sid, "chapterId": cid, "mangaId": mid,
                "progress": -1, "total": 0, "completed": True,
            })
            report.history_added += 1
        for ch in manga.chapters:
            if ch.date_upload_ms:
                up = _ms_to_dt(ch.date_upload_ms)
                if lastchap is None or up > lastchap:
                    lastchap = up

        if key in have_lib:
            lib = have_lib[key]
            merged_cats = set(lib["categories"]) | set(manga.categories)
            for cn in merged_cats:
                if cn not in all_categories:
                    all_categories.append(cn)
            order = {cn: i for i, cn in enumerate(all_categories)}
            lib["categories"] = sorted(merged_cats, key=lambda cn: order[cn])
        else:
            now = dt.datetime.now(UTC).replace(tzinfo=None)
            lib = {"lastOpened": lastread or now, "lastUpdated": now, "lastUpdatedChapters": now}
            if lastchap:
                lib["lastChapter"] = lastchap
            if lastread:
                lib["lastRead"] = lastread
            lib.update({
                "dateAdded": _ms_to_dt(manga.date_added_ms) if manga.date_added_ms else now,
                "categories": manga.categories, "mangaId": mid, "sourceId": sid,
            })
            new["library"].append(lib)
            for cn in manga.categories:
                if cn not in all_categories:
                    all_categories.append(cn)

        for t in manga.tracking:
            if t.sync_id != 2 or (sid, mid, "anilist") in have_trk:
                continue
            new["trackItems"].append({
                "id": str(t.media_id), "trackerId": "anilist", "mangaId": mid, "sourceId": sid,
                "title": t.title, "chapterOffset": 0,
            })

    for k in new:
        AI[k] = AI[k] + new[k]
    final_titles = list(dict.fromkeys(all_categories))
    AI["categories"] = [
        category_objs_by_title.get(title) if isinstance(category_objs_by_title.get(title), dict)
        else {"title": title, "sort": i, "group": False}
        for i, title in enumerate(final_titles)
    ]
    if "sources" in AI:
        new_ids = used_source_ids - existing_source_ids
        AI["sources"] = source_entries + sorted(new_ids)
    AI["date"] = dt.datetime.now(UTC).replace(tzinfo=None)
    AI["automatic"] = False
    return plistlib.dumps(AI, fmt=plistlib.FMT_BINARY), report


# ---------------------------------------------------------------------------
# top-level dispatch
# ---------------------------------------------------------------------------

APPS = ("tachiyomi", "tachimanga", "aidoku")


APP_LABELS_FOR_ERRORS = {
    "tachiyomi": "Tachiyomi/Mihon/Komikku",
    "tachimanga": "Tachimanga",
    "aidoku": "Aidoku",
}

# Errors that mean "the file parsed as the right container format (gzip/zip/
# plist) but its internal structure wasn't what we expected" - most likely
# because the app updated its backup schema. Caught around both the read and
# write side so a future format change fails with a clear message instead of
# a raw KeyError or silently-wrong output.
_STRUCTURE_ERRORS = (KeyError, TypeError, IndexError, AttributeError)


def _reraise_as_format_error(app_name: str, exc: Exception):
    raise ValueError(
        f"This {APP_LABELS_FOR_ERRORS.get(app_name, app_name)} backup doesn't have the "
        f"structure this tool expects ({type(exc).__name__}: {exc}). The app may have "
        f"changed its backup format since this converter was last updated - "
        f"please report this."
    ) from exc


def convert_backup(source_bytes: bytes, source_app: str, target_bytes: bytes, target_app: str):
    from . import tachimanga as tm

    if source_app == target_app:
        raise ValueError("Source and target app must be different.")

    try:
        if source_app == "tachiyomi":
            mangas = read_tachibk(source_bytes)
            skipped = []
        elif source_app == "tachimanga":
            mangas, _ = tm.read_tmb(source_bytes)
            skipped = []
        elif source_app == "aidoku":
            mangas, skipped = read_aidoku(source_bytes)
        else:
            raise ValueError(f"unknown source app {source_app}")
    except _STRUCTURE_ERRORS as e:
        _reraise_as_format_error(source_app, e)

    try:
        if target_app == "tachiyomi":
            out_bytes, report = write_into_tachibk(target_bytes, mangas)
        elif target_app == "tachimanga":
            out_bytes, report = tm.write_into_tmb(target_bytes, mangas)
        elif target_app == "aidoku":
            out_bytes, report = write_into_aidoku(target_bytes, mangas)
        else:
            raise ValueError(f"unknown target app {target_app}")
    except _STRUCTURE_ERRORS as e:
        _reraise_as_format_error(target_app, e)

    report.manga_skipped_no_source = skipped + report.manga_skipped_no_source
    return out_bytes, report


def analyze_coverage(source_bytes: bytes, source_app: str, target_app: str):
    """Read-only dry run: reports which manga in the source backup would
    transfer to target_app without writing anything or needing a target
    file. Used by the "check coverage first" flow so people can see what
    they'd get before committing to a real conversion."""
    from . import tachimanga as tm

    if source_app == target_app:
        raise ValueError("Source and target app must be different.")

    try:
        if source_app == "aidoku":
            mangas, skipped_titles = read_aidoku(source_bytes)
        elif source_app == "tachimanga":
            mangas, skipped_titles = tm.read_tmb(source_bytes)
            skipped_titles = []
        elif source_app == "tachiyomi":
            mangas = read_tachibk(source_bytes)
            skipped_titles = []
        else:
            raise ValueError(f"unknown source app {source_app}")
    except _STRUCTURE_ERRORS as e:
        _reraise_as_format_error(source_app, e)

    identity = {"tachiyomi", "tachimanga"} >= {source_app, target_app}

    transferable = []
    not_transferable = list(skipped_titles)
    for manga in mangas:
        if identity:
            transferable.append({"title": manga.title, "source": None})
            continue
        if target_app == "aidoku":
            mapping = BY_TACHI_SOURCE_ID.get(manga.source_id)
        else:
            # manga came from read_aidoku(), which already only returns
            # entries with a known mapping - so this is always transferable
            # when going aidoku -> tachiyomi-ecosystem.
            mapping = True
        if mapping:
            source_name = mapping.name if mapping is not True else None
            transferable.append({"title": manga.title, "source": source_name})
        else:
            not_transferable.append(manga.title)

    return {
        "total": len(transferable) + len(not_transferable),
        "transferable": transferable,
        "not_transferable": not_transferable,
        "identity": identity,
    }
