"""One fabricated manga per registered source in sources.py, with a URL
shaped exactly like that source's real extension would produce - not real
user data, just enough for each mapping's own regex/parsing logic to exercise
its real code path in CI. Catches "someone edited an extractor and broke it"
in a way empty-template smoke tests never could, since those never touch a
single per-source mapping function.

Manga/chapter urls were built by reading each source's own extractor in
sources.py (e.g. Comix needs a "-" in the slug and a numeric chapter prefix,
MangaPlus needs "titles/<digits>", MangaFire's chapter needs a leading
"<digits>-"). Not every source round-trips back to a byte-identical url
(e.g. MangaFire's Aidoku side never stores the descriptive slug - documented,
expected, not a bug), so the check here is "converts without error and isn't
skipped", not "url survives unchanged".
"""
from .model import TachiChapter, TachiManga
from .sources import REGISTRY

_FIXTURE_URLS = {
    "MangaDex": {
        "manga": "https://mangadex.org/title/test-mangadex-0001",
        "chapter": "https://mangadex.org/chapter/test-mangadex-ch-0001",
    },
    "Comix": {
        "manga": "test-comix-manga-123",
        "chapter": "https://comix.to/title/test-comix-manga-123/42-chapter-one",
    },
    "MangaPlus": {
        "manga": "https://mangaplus.shueisha.co.jp/titles/100001",
        "chapter": "https://mangaplus.shueisha.co.jp/viewer/1000001",
    },
    "MangaFire": {
        "manga": "https://mangafire.to/manga/test-manga-abc123",
        "chapter": "https://mangafire.to/read/test-manga-abc123/en/10-chapter-ten",
    },
    "AsuraScans": {
        "manga": "https://asuracomic.net/series/test-asura-manga",
        "chapter": "https://asuracomic.net/series/test-asura-manga/chapter-1",
    },
    "Mangakakalot": {
        "manga": "/manga/test-mangakakalot-manga",
        "chapter": "/manga/test-mangakakalot-manga/chapter-1",
    },
    "TCB Scans": {
        "manga": "/manga/test-tcb-manga",
        "chapter": "/manga/test-tcb-manga/chapter-1",
    },
    "Weeb Central": {
        "manga": "/series/test-weebcentral-manga",
        "chapter": "/series/test-weebcentral-manga/chapter-1",
    },
    "BatCave": {
        "manga": "/manga/test-batcave-manga",
        "chapter": "/manga/test-batcave-manga/chapter-1",
    },
    "Read Comics Online": {
        "manga": "/comic/test-readcomicsonline-manga",
        "chapter": "/comic/test-readcomicsonline-manga/chapter-1",
    },
}


def build_synthetic_mangas() -> list:
    """One TachiManga per REGISTRY source, each with one chapter (unread, so
    it also exercises the "chapter exists but no history entry" path)."""
    mangas = []
    for mapping in REGISTRY:
        urls = _FIXTURE_URLS.get(mapping.name)
        if urls is None:
            raise KeyError(
                f"No synthetic fixture urls defined for source {mapping.name!r} - "
                f"add one to app/fixtures.py._FIXTURE_URLS."
            )
        source_id = next(iter(mapping.tachi_source_ids))
        chapter = TachiChapter(
            url=urls["chapter"], name="Chapter 1", read=False,
            chapter_number=1.0, source_order=0,
        )
        mangas.append(TachiManga(
            source_id=source_id, url=urls["manga"], title=f"Synthetic Test Manga ({mapping.name})",
            genres=[], categories=[], chapters=[chapter], history=[], tracking=[],
        ))
    return mangas
