""""Wrapped"-style summary of a single backup: total manga, chapters read,
top sources, top genres, oldest entry. Read-only - the shareable card image
itself is drawn client-side via Canvas (see index.html), so the computed
numbers never round-trip back through the server as an image.
"""
from collections import Counter

from .convert import _STRUCTURE_ERRORS, _reraise_as_format_error
from .dedupe import _read_native_aib, _read_native_tachibk, _read_native_tmb  # noqa: F401 (re-exported readers)
from .sources import BY_AIDOKU_ID, BY_TACHI_SOURCE_ID


def _source_label(app_name: str, source_key) -> str:
    if app_name == "aidoku":
        mapping = BY_AIDOKU_ID.get(source_key)
        return mapping.name if mapping else str(source_key)
    mapping = BY_TACHI_SOURCE_ID.get(source_key)
    return mapping.name if mapping else f"Source #{source_key}"


def _read_full(data: bytes, app_name: str):
    """Unlike dedupe.py's lightweight _NativeEntry, this needs genres and
    date_added too, so it goes through the same per-format parsing but
    keeps the richer TachiManga objects convert.py already produces -
    fine here since, unlike dedupe/repair, nothing gets written back."""
    from . import convert
    from . import tachimanga as tm
    if app_name == "tachiyomi":
        return convert.read_tachibk(data)
    elif app_name == "tachimanga":
        mangas, _ = tm.read_tmb(data)
        return mangas
    elif app_name == "aidoku":
        # Read the plist directly (not the cross-app translated backup) so
        # unmapped sources still count and genres/date_added are available.
        import plistlib
        AI = plistlib.loads(data)
        lib_by_key = {(l["sourceId"], l["mangaId"]): l for l in AI.get("library", [])}
        out = []
        for m in AI.get("manga", []):
            key = (m["sourceId"], m["id"])
            lib = lib_by_key.get(key)
            out.append(_AidokuStub(
                source_key=m["sourceId"], title=m.get("title", "(untitled)"),
                genres=m.get("tags") or [],
                date_added=lib.get("dateAdded") if lib else None,
            ))
        return out
    raise ValueError(f"unknown app {app_name}")


class _AidokuStub:
    """Aidoku manga read natively (own sourceId, not cross-app translated),
    just the fields wrapped_stats() needs."""
    def __init__(self, source_key, title, genres, date_added):
        self.source_key = source_key
        self.title = title
        self.genres = genres
        self.date_added = date_added  # datetime or None


# Lucky Star "reader type" for the share card: each girl collects points from
# genres that fit her (substring match, any language the tags come in), plus
# a bonus from the library's shape. Ties go to Konata, the site's #1.
READER_TYPE_GENRES = {
    "konata": ("action", "isekai", "game", "fantasy", "comedy", "shounen", "adventure", "martial"),
    "kagami": ("drama", "psycholog", "mystery", "thriller", "historical", "seinen", "tragedy", "horror"),
    "tsukasa": ("romance", "slice of life", "shoujo", "school", "cooking", "comedy", "josei", "fluff"),
    "miyuki": ("sci", "medical", "mecha", "sports", "supernatural", "josei", "music", "award"),
}


def reader_type(genre_counter: Counter, total_manga: int, total_chapters_read: int) -> str:
    scores = {girl: 0.0 for girl in READER_TYPE_GENRES}
    for genre, n in genre_counter.items():
        g = genre.lower()
        for girl, keys in READER_TYPE_GENRES.items():
            if any(k in g for k in keys):
                scores[girl] += n
    total = sum(scores.values()) or 1
    scores = {girl: v / total for girl, v in scores.items()}
    if total_manga and total_chapters_read / total_manga >= 60:
        scores["konata"] += 0.25  # binges long series
    if len(genre_counter) >= 25:
        scores["miyuki"] += 0.2  # reads a bit of everything
    return max(scores, key=lambda girl: (scores[girl], girl == "konata"))


def compute_stats(data: bytes, app_name: str) -> dict:
    try:
        mangas = _read_full(data, app_name)
    except _STRUCTURE_ERRORS as e:
        _reraise_as_format_error(app_name, e)

    # The backup's own source list names sources we have no mapping for,
    # instead of showing "Source #7537715367149829912".
    native_readers = {"tachiyomi": _read_native_tachibk, "tachimanga": _read_native_tmb}
    own_names = {}
    if app_name in native_readers:
        try:
            own_names = {e.key[0]: e.source_name for e in native_readers[app_name](data)}
        except _STRUCTURE_ERRORS:
            pass

    total_manga = len(mangas)
    total_chapters_read = 0
    source_counter = Counter()
    genre_counter = Counter()
    oldest = None  # (title, sortable_timestamp)

    for m in mangas:
        if app_name == "aidoku":
            source_key = m.source_key
            genres = m.genres
            added_ts = m.date_added.timestamp() if m.date_added else None
        else:
            source_key = m.source_id
            genres = m.genres
            added_ts = (m.date_added_ms / 1000) if m.date_added_ms else None
            total_chapters_read += sum(1 for c in m.chapters if c.read)

        name = own_names.get(source_key)
        if not name or name == str(source_key):
            name = _source_label(app_name, source_key)
        source_counter[name] += 1
        for g in genres:
            if g:
                genre_counter[g] += 1
        if added_ts is not None and (oldest is None or added_ts < oldest[1]):
            oldest = (m.title, added_ts)

    if app_name == "aidoku":
        # Aidoku's native manga list here doesn't carry per-chapter read
        # state (that lives in history) - approximate with completed reads.
        import plistlib
        AI = plistlib.loads(data)
        total_chapters_read = sum(1 for h in AI.get("history", []) if h.get("completed"))

    return {
        "app": app_name,
        "total_manga": total_manga,
        "total_chapters_read": total_chapters_read,
        "top_sources": source_counter.most_common(5),
        "top_genres": genre_counter.most_common(5),
        "oldest_entry_title": oldest[0] if oldest else None,
        "reader_type": reader_type(genre_counter, total_manga, total_chapters_read),
    }
