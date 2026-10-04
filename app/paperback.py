"""Reader for Paperback (.pas4) backups -> shared TachiManga model.

A .pas4 is a zip of JSON files keyed by uuid: __LIBRARY_MANGA_V4 (library
entries + tabs), __SOURCE_MANGA_V4 (source + manga id), __MANGA_INFO_V4
(title/cover/author...), __CHAPTER_V4 and __CHAPTER_PROGRESS_MARKER_V4-N
(read state). Paperback's source ids are plain names ("MangaFox") and its
manga/chapter ids are the site's own slugs, so mapping to a Mihon extension
only needs that site's url shape - listed per source below (checked against
the extensions' source code and the live sites). Sources without an entry
are reported as not convertible. Paperback only has a reader here; the
direction Mihon -> Paperback isn't supported.
"""
import io
import json
import zipfile

from .model import TachiChapter, TachiHistoryEntry, TachiManga
from .safety import bounded_zip_read
from .sources import _tachi_source_id

APPLE_EPOCH_OFFSET_S = 978307200  # Paperback stores seconds since 2001-01-01

# Paperback source id -> (Mihon source id, manga url, chapter url)
PAPERBACK_SOURCES = {
    "Mangahub": (_tachi_source_id("MangaHub", "en"),
                 lambda m: f"/manga/{m}", lambda m, c: f"/{m}/chapter-{c}"),
    "MangaFox": (_tachi_source_id("MangaFox", "en"),
                 lambda m: f"/manga/{m}/", lambda m, c: f"/manga/{m}/{c}/1.html"),
    "MangaKatana": (_tachi_source_id("MangaKatana", "en"),
                    lambda m: f"/manga/{m}", lambda m, c: f"/manga/{m}/{c}"),
    "MangaHere": (_tachi_source_id("Mangahere", "en", 2),
                  lambda m: f"/manga/{m}/", lambda m, c: f"/manga/{m}/{c}/1.html"),
}

_STATUS = {"ongoing": 1, "completed": 2, "ended": 2}
_NAMES = {"Mangahub": "MangaHub", "MangaFox": "MangaFox", "MangaKatana": "MangaKatana",
          "MangaHere": "Mangahere"}


def _read(zf, prefix):
    out = {}
    for name in zf.namelist():
        if name == prefix or name.startswith(prefix + "-"):
            out.update(json.loads(bounded_zip_read(zf, name)))
    return out


def _ms(apple_s):
    if not apple_s:
        return None
    return int((apple_s + APPLE_EPOCH_OFFSET_S) * 1000)


def read_paperback(data: bytes, skipped_sources: list = None):
    """Returns (list[TachiManga], skipped_titles). If given, `skipped_sources`
    gets one ("paperback:<source>", <source>) per skipped title, the shape the
    report's unmapped-source counter expects."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    library = _read(zf, "__LIBRARY_MANGA_V4")
    sources = _read(zf, "__SOURCE_MANGA_V4")
    infos = _read(zf, "__MANGA_INFO_V4")
    chapters = _read(zf, "__CHAPTER_V4")
    progress = _read(zf, "__CHAPTER_PROGRESS_MARKER_V4")

    chapters_by_source = {}
    for cid, ch in chapters.items():
        chapters_by_source.setdefault(ch["sourceManga"]["id"], []).append(ch)

    mangas, skipped = [], []
    for entry in library.values():
        src = sources[entry["primarySource"]["id"]]
        info = infos.get(src["mangaInfo"]["id"], {})
        title = (info.get("titles") or [src["mangaId"]])[0]
        mapping = PAPERBACK_SOURCES.get(src["sourceId"])
        if not mapping:
            skipped.append(title)
            if skipped_sources is not None:
                skipped_sources.append((f"paperback:{src['sourceId']}", src["sourceId"]))
            continue
        source_id, manga_url, chapter_url = mapping

        # Mihon lists newest chapter first (source_order 0)
        raw = sorted(chapters_by_source.get(src["id"], []),
                     key=lambda c: c.get("sortingIndex", 0), reverse=True)
        tchapters, history = [], []
        for order, ch in enumerate(raw):
            url = chapter_url(src["mangaId"], ch["chapterId"])
            marker = progress.get(ch["id"])
            read = bool(marker and marker.get("completed"))
            last_page = int(marker["lastPage"]) if marker and not read and marker.get("lastPage") else 0
            tchapters.append(TachiChapter(
                url=url, name=ch.get("name") or f"Chapter {ch.get('chapNum')}",
                scanlator=ch.get("group") or None, read=read, last_page_read=last_page,
                date_upload_ms=_ms(ch.get("time")), chapter_number=float(ch.get("chapNum") or 0),
                source_order=order,
            ))
            if marker and (read or last_page):
                history.append(TachiHistoryEntry(chapter_url=url, last_read_ms=_ms(marker.get("time")) or 0))

        genres = [t["label"].strip() for g in info.get("tags", []) for t in g.get("tags", [])]
        mangas.append(TachiManga(
            source_id=source_id, url=manga_url(src["mangaId"]), title=title,
            artist=info.get("artist") or None, author=info.get("author") or None,
            description=info.get("desc") or None, genres=genres,
            status=_STATUS.get(str(info.get("status", "")).lower(), 0),
            thumbnail_url=info.get("image") or None,
            date_added_ms=_ms(entry.get("dateBookmarked")),
            categories=[t["name"].strip() for t in entry.get("libraryTabs", [])],
            chapters=tchapters, history=history, source_name=_NAMES.get(src["sourceId"]),
        ))
    return mangas, skipped
