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


@dataclass
class TachiHistoryEntry:
    chapter_url: str  # matches a TachiChapter.url within the same manga
    last_read_ms: int
    read_duration: int = 0


@dataclass
class TachiTrack:
    sync_id: int  # 2 = AniList
    media_id: int
    title: str


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
