"""Shared intermediate representation for one manga + its chapters/history/
tracking, used to move data between .tachibk, .tmb (Tachimanga) and .aib
(Aidoku) readers/writers without every pair needing its own glue code.

Tachiyomi/Mihon/Komikku and Tachimanga share the same numeric source_id and
url conventions (confirmed against a real Tachimanga export - it runs the
actual Tachiyomi extension jars), so converting between those two needs no
source mapping at all. Aidoku uses a different id scheme entirely, so that
direction always goes through sources.py's SourceMapping registry.
"""
from dataclasses import dataclass, field


@dataclass
class TachiChapter:
    url: str
    name: str
    scanlator: str = None
    read: bool = False
    last_page_read: int = 0
    date_upload_ms: int = None
    chapter_number: float = None
    source_order: int = 0
    last_modified_s: int = None
    bookmark: bool = False
    last_read_ms: int = None  # per-chapter read time, where the app keeps one (Tachimanga)


@dataclass
class TachiHistoryEntry:
    chapter_url: str  # matches a TachiChapter.url within the same manga
    last_read_ms: int
    read_duration: int = 0


@dataclass
class TachiTrack:
    # Tachiyomi tracker ids (1 MyAnimeList, 2 AniList, 3 Kitsu, 7 MangaUpdates,
    # ...) - Tachimanga uses the same ones. Aidoku only gets AniList.
    sync_id: int
    media_id: int
    title: str
    library_id: int = None
    tracking_url: str = ""
    last_chapter_read: float = 0.0
    total_chapters: int = 0
    score: float = 0.0
    status: int = 0
    started_ms: int = 0
    finished_ms: int = 0


@dataclass
class TachiManga:
    source_id: int
    url: str
    title: str
    artist: str = None
    author: str = None
    description: str = None
    genres: list = field(default_factory=list)
    status: int = 0
    thumbnail_url: str = None
    date_added_ms: int = None
    categories: list = field(default_factory=list)
    chapters: list = field(default_factory=list)
    history: list = field(default_factory=list)
    tracking: list = field(default_factory=list)
    source_name: str = None  # as stored in the backup itself, if it says
