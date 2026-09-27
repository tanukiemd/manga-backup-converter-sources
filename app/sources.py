"""Registry of known source-ID mappings between Tachiyomi-ecosystem
(Tachiyomi/Mihon/Komikku/...) numeric sourceIds and Aidoku string source ids.

Adding a source here means: given the Tachiyomi-side manga/chapter URL, we
know how to compute the Aidoku manga/chapter id, and vice versa. This is
inherently per-source hand-written logic (confirmed while building this: two
apps' extensions for the "same" website usually invent their own, unrelated
internal id schemes - there is no way to derive this generically from a
source name/baseURL match alone). Sources not listed here are reported as
"not convertible" rather than guessed at.
"""
import hashlib
import json
import re
from urllib.parse import parse_qs, urlparse


class SourceMapping:
    def __init__(self, name, tachi_source_ids, aidoku_id,
                 tachi_to_aidoku_manga_id, aidoku_manga_url_from_id,
                 tachi_to_aidoku_chapter_id, aidoku_chapter_url_from_id,
                 tachi_to_aidoku_manga_url=None,
                 tachi_manga_url_override=None, tachi_chapter_url_override=None,
                 aidoku_manga_url_override=None, aidoku_chapter_url_override=None,
                 lang_from_manga_id=None, blank_chapter_lang=False):
        self.name = name
        self.tachi_source_ids = set(tachi_source_ids)
        self.aidoku_id = aidoku_id
        self.tachi_to_aidoku_manga_id = tachi_to_aidoku_manga_id
        self.aidoku_manga_url_from_id = aidoku_manga_url_from_id
        self.tachi_to_aidoku_chapter_id = tachi_to_aidoku_chapter_id
        self.aidoku_chapter_url_from_id = aidoku_chapter_url_from_id
        # Used only when CREATING a brand new Aidoku manga entry: builds
        # Aidoku's own "url" field straight from the tachi-side url, so any
        # descriptive slug info survives (matters for sources like Comix
        # where the id is only a short prefix of the full slug - losing the
        # rest here breaks round-tripping, since the id alone can't
        # reconstruct the original tachi-side url later). Defaults to
        # aidoku_manga_url_from_id(id) when a source has no such info to lose.
        self.tachi_to_aidoku_manga_url = tachi_to_aidoku_manga_url
        # Exact url shapes each app stores, where they differ (verified against
        # real paired Mihon + Aidoku exports): the id carries across, the url
        # around it doesn't - e.g. MangaDex is "/chapter/<id>" in Mihon but
        # "https://mangadex.org/chapter/<id>" in Aidoku.
        self.tachi_manga_url_override = tachi_manga_url_override
        self.tachi_chapter_url_override = tachi_chapter_url_override
        self.aidoku_manga_url_override = aidoku_manga_url_override
        self.aidoku_chapter_url_override = aidoku_chapter_url_override
        self.lang_from_manga_id = lang_from_manga_id
        self.blank_chapter_lang = blank_chapter_lang
        # Filled in via _attach_languages() for sources that ship one
        # Tachiyomi sourceId per language but are a single Aidoku source.
        self.tachi_id_by_lang = {}
        self.lang_by_tachi_id = {}

    def tachi_source_id_for_lang(self, aidoku_lang=None) -> int:
        """Aidoku -> Tachiyomi: pick the per-language source matching the
        chapters' language (chapter ids differ per language on e.g. MangaDex,
        so the wrong one loses read progress), falling back to English."""
        if not self.tachi_id_by_lang:
            return min(self.tachi_source_ids)
        lang = (aidoku_lang or "").lower()
        lang = _AIDOKU_TO_TACHI_LANG.get(lang, lang)
        for candidate in (lang, lang.split("-")[0], "en"):
            if candidate in self.tachi_id_by_lang:
                return self.tachi_id_by_lang[candidate]
        return min(self.tachi_source_ids)

    def tachi_manga_url(self, aidoku_id, aidoku_url=""):
        if self.tachi_manga_url_override:
            return self.tachi_manga_url_override(aidoku_id)
        return self.aidoku_manga_url_from_id(aidoku_id, aidoku_url)

    def tachi_chapter_url(self, aidoku_manga_id, aidoku_chapter_id, aidoku_chapter_url=None):
        if self.tachi_chapter_url_override:
            return self.tachi_chapter_url_override(aidoku_manga_id, aidoku_chapter_id, aidoku_chapter_url)
        return aidoku_chapter_url or self.aidoku_chapter_url_from_id(aidoku_chapter_id)

    def aidoku_manga_url(self, aidoku_id, tachi_url, chapter_urls):
        if self.aidoku_manga_url_override:
            return self.aidoku_manga_url_override(aidoku_id)
        if self.tachi_to_aidoku_manga_url is not None:
            return self.tachi_to_aidoku_manga_url(tachi_url, chapter_urls)
        return self.aidoku_manga_url_from_id(aidoku_id)

    def aidoku_chapter_url(self, aidoku_manga_id, aidoku_chapter_id, tachi_chapter_url):
        if self.aidoku_chapter_url_override:
            return self.aidoku_chapter_url_override(aidoku_manga_id, aidoku_chapter_id, tachi_chapter_url)
        return tachi_chapter_url

    def tachi_source_id_for_manga(self, aidoku_manga_id, chapter_langs):
        if self.lang_from_manga_id:
            return self.tachi_source_id_for_lang(self.lang_from_manga_id(aidoku_manga_id))
        langs = [l for l in chapter_langs if l]
        return self.tachi_source_id_for_lang(max(set(langs), key=langs.count) if langs else None)

    def aidoku_chapter_lang(self, tachi_source_id: int) -> str:
        return "" if self.blank_chapter_lang else self.aidoku_lang_for(tachi_source_id)

    def aidoku_lang_for(self, tachi_source_id: int) -> str:
        lang = self.lang_by_tachi_id.get(tachi_source_id)
        if lang is None:
            return "en"
        return _TACHI_TO_AIDOKU_LANG.get(lang, lang)


# Aidoku's multi-language sources use MangaDex-style codes; the Tachiyomi
# extensions use BCP-47-ish ones for a few regional variants.
_AIDOKU_TO_TACHI_LANG = {"es-la": "es-419", "zh": "zh-hans", "zh-hk": "zh-hant"}
_TACHI_TO_AIDOKU_LANG = {v: k for k, v in _AIDOKU_TO_TACHI_LANG.items()}


def _tachi_source_id(name: str, lang: str, version: int = 1) -> int:
    """Tachiyomi's own HttpSource id: first 8 bytes of md5("name/lang/version")
    with the sign bit cleared."""
    digest = hashlib.md5(f"{name.lower()}/{lang}/{version}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _attach_languages(mapping, extension_name, langs):
    _attach_language_ids(mapping, {lang: _tachi_source_id(extension_name, lang) for lang in langs})


def _attach_language_ids(mapping, ids_by_lang):
    by_lang = {lang.lower(): i for lang, i in ids_by_lang.items()}
    # Guards against a typo silently routing titles to the wrong source.
    assert set(by_lang.values()) == mapping.tachi_source_ids, mapping.name
    mapping.tachi_id_by_lang = by_lang
    mapping.lang_by_tachi_id = {i: lang for lang, i in by_lang.items()}


def _mangadex_manga_id(tachi_url: str) -> str:
    return tachi_url.rstrip("/").split("/")[-1]


def _mangadex_manga_url(aidoku_id: str, aidoku_url: str = "") -> str:
    return f"https://mangadex.org/title/{aidoku_id}"


def _mangadex_chapter_id(tachi_chapter_url: str) -> str:
    return tachi_chapter_url.rstrip("/").split("/")[-1]


def _mangadex_chapter_url(aidoku_chapter_id: str) -> str:
    return f"https://mangadex.org/chapter/{aidoku_chapter_id}"


_MANGADEX_TACHI_IDS = {
    4638673959522768501, 987803387023224960, 3339599426223341161, 9127464796236242233,
    1553736397938752611, 3601180820582582605, 4150470519566206911, 5463447640980279236,
    1347402746269051958, 5860541308324630662, 5148895169070562838, 1493666528525752601,
    2072928884077964642, 8548374501079910130, 3578612018159256808, 425785191804166217,
    6750440049024086587, 2499283573021220255, 2819252027406613931, 8773024089257004344,
    8578871918181236609, 8254121249433835847, 4505830566611664829, 8952567078513962586,
    5098537545549490547, 3260701926561129943, 1424273154577029558, 6840513937945146538,
    4284949320785450865, 3686775439235747344, 3807502156582598786, 1952071260038453057,
    1411768577036936240, 1573550798452063564, 8884149958776527952, 3285208643537017688,
    764587568075398530, 737986167355114438, 1471784905273036181, 5967745367608513818,
    954368055061084457, 4872213291993424667, 3781216447842245147, 8033579885162383068,
    2655149515337070132, 5189216366882819742, 4774459486579224459, 2098905203823335614,
    3507378005483435886, 2875503798326600410, 4938773340256184018, 6400665728063187402,
    1145824452519314725, 4273071356706429527, 6886894829142702925, 1713554459881080228,
    3846770256925560569, 5779037855201976894, 72800122520214493, 2838715564514827672,
    9194073792736219759,
}  # one numeric sourceId per UI language (61 total) - confirmed via the Keiyoushi
   # extension index; Aidoku's "multi.mangadex" is a single source covering all of them.

MANGADEX = SourceMapping(
    name="MangaDex",
    tachi_source_ids=_MANGADEX_TACHI_IDS,
    aidoku_id="multi.mangadex",
    tachi_to_aidoku_manga_id=_mangadex_manga_id,
    aidoku_manga_url_from_id=_mangadex_manga_url,
    tachi_to_aidoku_chapter_id=_mangadex_chapter_id,
    aidoku_chapter_url_from_id=_mangadex_chapter_url,
    tachi_manga_url_override=lambda mid: f"/manga/{mid}",
    tachi_chapter_url_override=lambda mid, cid, _url: f"/chapter/{cid}",
    aidoku_chapter_url_override=lambda mid, cid, _url: f"https://mangadex.org/chapter/{cid}",
)


def _comix_extract_slug(url: str) -> str:
    # Different Comix extension versions/apps store the manga url either as
    # bare "<slug>" or as "title/<slug>" (confirmed via a real Tachimanga
    # backup, which used the "title/" form while the original Komikku sample
    # used the bare form) - handle both rather than assuming one.
    m = re.search(r"title/([^/]+)", url)
    if m:
        return m.group(1)
    return url.strip("/")


def _comix_manga_id(tachi_url: str, chapter_urls=()) -> str:
    slug = _comix_extract_slug(tachi_url)
    if "-" not in slug:
        for cu in chapter_urls:
            slug2 = _comix_extract_slug(cu)
            if "-" in slug2:
                slug = slug2
                break
    return slug.split("-")[0]


def _comix_manga_url(aidoku_id: str, aidoku_url: str = "") -> str:
    # Aidoku's own manga url is "https://comix.to/title/<full-slug>", but the
    # Tachiyomi-ecosystem Manga.url column stores the BARE slug with no
    # "title/" prefix (confirmed against both the original Komikku sample
    # and a real Tachimanga export - only Chapter urls carry "title/", not
    # the manga url itself).
    if aidoku_url:
        slug = aidoku_url.rstrip("/").split("/")[-1]
        return f"/{slug}"
    return f"/{aidoku_id}"


def _comix_tachi_to_aidoku_manga_url(tachi_url: str, chapter_urls=()) -> str:
    slug = _comix_extract_slug(tachi_url)
    if "-" not in slug:
        for cu in chapter_urls:
            slug2 = _comix_extract_slug(cu)
            if "-" in slug2:
                slug = slug2
                break
    return f"https://comix.to/title/{slug}"


def _comix_chapter_id(tachi_chapter_url: str) -> str:
    m = re.search(r"/(\d+)-[^/]*$", tachi_chapter_url)
    if not m:
        raise ValueError(f"unrecognized Comix chapter url: {tachi_chapter_url}")
    return m.group(1)


def _comix_chapter_url(aidoku_chapter_id: str) -> str:
    # We don't have enough info to reconstruct the full slugged Tachiyomi
    # chapter path from the numeric id alone; callers should prefer the
    # Aidoku chapter's own stored url when going Aidoku -> Tachiyomi.
    return f"/chapter/{aidoku_chapter_id}"


COMIX = SourceMapping(
    name="Comix",
    tachi_source_ids={7537715367149829912},
    aidoku_id="en.comix",
    tachi_to_aidoku_manga_id=_comix_manga_id,
    aidoku_manga_url_from_id=_comix_manga_url,
    tachi_to_aidoku_chapter_id=_comix_chapter_id,
    aidoku_chapter_url_from_id=_comix_chapter_url,
    tachi_to_aidoku_manga_url=_comix_tachi_to_aidoku_manga_url,
)

def _mangaplus_manga_id(tachi_url: str) -> str:
    m = re.search(r"titles/(\d+)", tachi_url)
    if not m:
        raise ValueError(f"unrecognized MangaPlus manga url: {tachi_url}")
    return m.group(1)


def _mangaplus_manga_url(aidoku_id: str, aidoku_url: str = "") -> str:
    return f"#/titles/{aidoku_id}"


def _mangaplus_chapter_id(tachi_chapter_url: str) -> str:
    m = re.search(r"viewer/(\d+)", tachi_chapter_url)
    if not m:
        raise ValueError(f"unrecognized MangaPlus chapter url: {tachi_chapter_url}")
    return m.group(1)


def _mangaplus_chapter_url(aidoku_chapter_id: str) -> str:
    return f"#/viewer/{aidoku_chapter_id}"


# Confirmed on real backups for 1 (en), 2 (es), 5 (pt-BR) and 8 (de).
_MANGAPLUS_LANG_BY_PREFIX = {"1": "en", "2": "es", "3": "fr", "4": "id", "5": "pt-br",
                             "6": "ru", "7": "th", "8": "de", "9": "vi"}


# Tachiyomi/Mihon/Komikku ship one numeric sourceId PER LANGUAGE for MangaPlus
# (en, es, fr, id, pt-BR, ru, th, vi, de - confirmed against the compiled
# Keiyoushi extension index), while Aidoku's "multi.mangaplus" is a single
# source covering all of them. Manga/chapter ids are the official numeric
# Shueisha titleId/chapterId in both ecosystems (confirmed against the actual
# extension source code on both sides), so this is as safe as MangaDex.
MANGAPLUS = SourceMapping(
    name="MangaPlus",
    tachi_source_ids={
        1998944621602463790,  # en
        1286073245950890830,  # es
        7642759409549978864,  # fr
        932564577108614127,   # id
        3444662672352788181,  # pt-BR
        3520485566708512181,  # ru
        6345211913721743017,  # th
        4696259977267090434,  # vi
        1893513843840146580,  # de
    },
    aidoku_id="multi.mangaplus",
    tachi_to_aidoku_manga_id=_mangaplus_manga_id,
    aidoku_manga_url_from_id=_mangaplus_manga_url,
    tachi_to_aidoku_chapter_id=_mangaplus_chapter_id,
    aidoku_chapter_url_from_id=_mangaplus_chapter_url,
    tachi_chapter_url_override=lambda mid, cid, _url: f"#/viewer/{cid}",
    aidoku_manga_url_override=lambda mid: f"https://mangaplus.shueisha.co.jp/titles/{mid}",
    aidoku_chapter_url_override=lambda mid, cid, _url: f"https://mangaplus.shueisha.co.jp/viewer/{cid}",
    # Aidoku stores no chapter language for MangaPlus, but the title id's
    # first digit is the edition's language (MangaPlus' own Language enum + 1).
    lang_from_manga_id=lambda mid: _MANGAPLUS_LANG_BY_PREFIX.get(str(mid)[:1]),
    blank_chapter_lang=True,
)

def _mangafire_manga_id(tachi_url: str) -> str:
    # MangaFire's own getHid() helper checks "." before "-" (confirmed
    # against a real backup using the "/manga/<slug>.<hid>" form - an older
    # or alternate url convention alongside the newer "/title/<hid>-<slug>"
    # seen elsewhere; the extension's own code handles both).
    last = tachi_url.rstrip("/").split("/")[-1]
    if "." in last:
        return last.rsplit(".", 1)[-1]
    if "-" in last:
        return last.split("-", 1)[0]
    return last


def _mangafire_manga_url(aidoku_id: str, aidoku_url: str = "") -> str:
    # Aidoku's own MangaFire extension doesn't retain the descriptive slug at
    # all (only the bare hid) - confirmed in its source, manga.url isn't even
    # set there. The bare form still resolves correctly on the Tachiyomi side
    # too (its getHid() parser falls back to the whole segment when there's
    # no "-"), it just won't byte-match a slugged original on a round-trip.
    return f"/title/{aidoku_id}"


def _mangafire_chapter_id(tachi_chapter_url: str) -> str:
    last = tachi_chapter_url.rstrip("/").split("/")[-1]
    m = re.match(r"(\d+)-", last)
    if not m:
        raise ValueError(f"unrecognized MangaFire chapter url: {tachi_chapter_url}")
    return m.group(1)


def _mangafire_chapter_url(aidoku_chapter_id: str) -> str:
    return f"/chapter/{aidoku_chapter_id}"


MANGAFIRE = SourceMapping(
    name="MangaFire",
    tachi_source_ids={
        6084907896154116083, 8098539940032331958, 3849324770075062403,
        6228021941803932286, 524110931382140732, 758400875161895515,
        7842137233968841729,
    },
    aidoku_id="multi.mangafire",
    tachi_to_aidoku_manga_id=_mangafire_manga_id,
    aidoku_manga_url_from_id=_mangafire_manga_url,
    tachi_to_aidoku_chapter_id=_mangafire_chapter_id,
    aidoku_chapter_url_from_id=_mangafire_chapter_url,
)

def _identity_manga_id(tachi_url: str) -> str:
    return tachi_url


def _identity_manga_url(aidoku_id: str, aidoku_url: str = "") -> str:
    return aidoku_id


def _identity_chapter_id(tachi_chapter_url: str) -> str:
    return tachi_chapter_url


def _identity_chapter_url(aidoku_chapter_id: str) -> str:
    return aidoku_chapter_id


def _make_identity_mapping(name, tachi_source_ids, aidoku_id):
    # Confirmed against real paired backups (Mihon + Aidoku, same manga/chapters
    # on both sides): manga.key and chapter.key are the exact relative-path
    # string used on the site itself, byte-identical to what Tachiyomi stores
    # as manga.url/chapter.url - no transformation needed in either direction.
    return SourceMapping(
        name=name,
        tachi_source_ids=tachi_source_ids,
        aidoku_id=aidoku_id,
        tachi_to_aidoku_manga_id=_identity_manga_id,
        aidoku_manga_url_from_id=_identity_manga_url,
        tachi_to_aidoku_chapter_id=_identity_chapter_id,
        aidoku_chapter_url_from_id=_identity_chapter_url,
    )


MANGAKAKALOT = _make_identity_mapping("Mangakakalot", {2528986671771677900}, "en.mangakakalot")
TCBSCANS = _make_identity_mapping("TCB Scans", {1435116756378369709}, "en.tcbscans")
WEEBCENTRAL = _make_identity_mapping("Weeb Central", {2131019126180322627}, "en.weebcentral")
BATCAVE = _make_identity_mapping("BatCave", {7422099479605463706}, "en.batcave")


def _asurascans_extract_slug(url: str) -> str:
    # Tachiyomi's own extension uses "/series/<slug>" while Aidoku's uses
    # "/comics/<slug>" for the same real site (confirmed against real paired
    # backups) - the directory differs but the slug itself is untruncated and
    # identical on both sides, so just take the last path segment.
    return url.rstrip("/").split("/")[-1]


def _asurascans_manga_id(tachi_url: str) -> str:
    return _asurascans_extract_slug(tachi_url)


def _asurascans_manga_url(aidoku_id: str, aidoku_url: str = "") -> str:
    return f"/series/{aidoku_id}"


def _asurascans_chapter_id(tachi_chapter_url: str) -> str:
    return _asurascans_extract_slug(tachi_chapter_url)


def _asurascans_chapter_url(aidoku_chapter_id: str) -> str:
    return f"/chapter/{aidoku_chapter_id}"


ASURASCANS = SourceMapping(
    name="AsuraScans",
    tachi_source_ids={6247824327199706550},
    aidoku_id="en.asurascans",
    tachi_to_aidoku_manga_id=_asurascans_manga_id,
    aidoku_manga_url_from_id=_asurascans_manga_url,
    tachi_to_aidoku_chapter_id=_asurascans_chapter_id,
    aidoku_chapter_url_from_id=_asurascans_chapter_url,
    tachi_chapter_url_override=lambda mid, cid, _url: f"/series/{mid}/chapter/{cid}",
    aidoku_manga_url_override=lambda mid: f"https://asurascans.com/comics/{mid}",
    aidoku_chapter_url_override=lambda mid, cid, _url: f"https://asurascans.com/comics/{mid}/chapter/{cid}",
)


def _readcomicsonline_extract_slug(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def _readcomicsonline_manga_id(tachi_url: str) -> str:
    return _readcomicsonline_extract_slug(tachi_url)


def _readcomicsonline_manga_url(aidoku_id: str, aidoku_url: str = "") -> str:
    return f"/comic/{aidoku_id}"


def _readcomicsonline_chapter_id(tachi_chapter_url: str) -> str:
    return _readcomicsonline_extract_slug(tachi_chapter_url)


def _readcomicsonline_chapter_url(aidoku_chapter_id: str) -> str:
    return aidoku_chapter_id


READCOMICSONLINE = SourceMapping(
    name="Read Comics Online",
    tachi_source_ids={7185601298150078890},
    aidoku_id="en.readcomicsonline",
    tachi_to_aidoku_manga_id=_readcomicsonline_manga_id,
    aidoku_manga_url_from_id=_readcomicsonline_manga_url,
    tachi_to_aidoku_chapter_id=_readcomicsonline_chapter_id,
    aidoku_chapter_url_from_id=_readcomicsonline_chapter_url,
)

_attach_languages(MANGADEX, "MangaDex", [
    "af", "ar", "az", "be", "bg", "bn", "ca", "cs", "cv", "da", "de", "el", "en", "eo", "es",
    "es-419", "et", "eu", "fa", "fi", "fil", "fr", "ga", "he", "hi", "hr", "hu", "id", "it",
    "ja", "jv", "ka", "kk", "ko", "la", "lt", "mn", "ms", "my", "ne", "nl", "no", "pl", "pt",
    "pt-BR", "ro", "ru", "sk", "sq", "sr", "sv", "ta", "te", "th", "tr", "uk", "ur", "uz",
    "vi", "zh-Hans", "zh-Hant",
])
_attach_languages(MANGAPLUS, "MANGA Plus by SHUEISHA", ["de", "en", "es", "fr", "id", "pt-BR", "ru", "th", "vi"])
_attach_languages(MANGAFIRE, "MangaFire", ["en", "es", "es-419", "fr", "ja", "pt", "pt-BR"])

# MangaDot (mangadot.net). Manga ids are identical in both apps; Mihon keeps
# each chapter as a small JSON blob around the same numeric id Aidoku uses
# (verified on real paired exports: 118/118, 208/208, 14/14 chapter ids).
def _mangadot_chapter_id(tachi_chapter_url: str) -> str:
    try:
        return str(json.loads(tachi_chapter_url)["id"])
    except (ValueError, KeyError, TypeError):
        raise ValueError(f"unrecognized MangaDot chapter url: {tachi_chapter_url}")


def _mangadot_tachi_chapter_url(mid, cid, aidoku_url=None) -> str:
    source = (parse_qs(urlparse(aidoku_url or "").query).get("source") or ["user"])[0]
    # Byte-exact with the extension's own serialisation, which Mihon matches on.
    return json.dumps({"id": str(cid), "source": source, "isVolume": False}, separators=(",", ":"))


def _mangadot_aidoku_chapter_url(mid, cid, tachi_url=None) -> str:
    try:
        source = json.loads(tachi_url).get("source") or "user"
    except (ValueError, TypeError, AttributeError):
        source = "user"
    return f"https://mangadot.net/chapter/{cid}?source={source}"


MANGADOT = SourceMapping(
    name="MangaDot",
    tachi_source_ids=set(),  # filled from the language table below
    aidoku_id="multi.mangadotnet",
    tachi_to_aidoku_manga_id=lambda url: url,
    aidoku_manga_url_from_id=lambda mid, url="": str(mid),
    tachi_to_aidoku_chapter_id=_mangadot_chapter_id,
    aidoku_chapter_url_from_id=lambda cid: _mangadot_tachi_chapter_url(None, cid),
    tachi_chapter_url_override=_mangadot_tachi_chapter_url,
    aidoku_manga_url_override=lambda mid: f"https://mangadot.net/manga/{mid}",
    aidoku_chapter_url_override=_mangadot_aidoku_chapter_url,
)
# Per-language source ids straight from the Keiyoushi index (index.pb,
# extension v1.6.23) - not all of them follow the usual md5 id scheme.
_MANGADOT_TACHI_ID_BY_LANG = {
    "ab": 4735885360393755385, "af": 626361877295636066, "am": 1214640310680383515,
    "ar": 5133570518916566066, "az": 8740468699151734392, "be": 6349207918477337222,
    "bg": 4621039982977056475, "bn": 4728703871864086205, "bs": 2106727426891515868,
    "ca": 4126429070202050423, "ceb": 1104434747623062236, "cs": 182506561627032263,
    "cv": 466560170889971500, "da": 522919629093846860, "de": 1739134904773959471,
    "el": 6280808899001059050, "en": 5900936305360403385, "eo": 3900938574086240284,
    "es": 1356109540530417190, "es-419": 5046796980408019790, "et": 7085366320872721673,
    "eu": 2365190675047124388, "fa": 6840185760082019759, "fi": 7568879765052968178,
    "fo": 403504858442756278, "fr": 6544312035114371248, "ga": 1990999442874191049,
    "gl": 9161576604389142963, "gn": 2649563537157849825, "gu": 7777361906352556467,
    "ha": 7370016116750489216, "he": 7524478288761759786, "hi": 4686432307246610016,
    "hr": 6919139667129890361, "ht": 4906990011623468194, "hu": 2744567066632059507,
    "hy": 3389751853142685462, "id": 8591108444263884327, "ig": 1212617635525738382,
    "is": 7457818185508918624, "it": 8788147393700258423, "ja": 2305771977147956314,
    "jv": 2450590764399511282, "ka": 7781185259229560796, "kk": 3501653098098324330,
    "km": 6558905765171140287, "kn": 735891950196570992, "ko": 8733946525904795862,
    "ku": 642272481774520917, "ky": 6432074668689969261, "la": 5980076819966447323,
    "lb": 7371980305504255093, "lo": 2817234851765014214, "lt": 3456620422576095825,
    "lv": 6496021153361901915, "mg": 3095899732404101103, "mi": 1243113298307153697,
    "mk": 3378671539429193821, "ml": 2065097680931770063, "mn": 9192319104809604483,
    "mo": 4385496560007026082, "mr": 2403752440512665902, "ms": 2379671138411944871,
    "mt": 763520574319176694, "my": 8689086897953658974, "ne": 1388001857060182903,
    "nl": 5339181991315919474, "no": 2111970709663576933, "ny": 5594683159745082451,
    "pl": 516446519459282312, "ps": 852113960420602047, "pt": 1374245104599191336,
    "pt-BR": 6883842335519142390, "rm": 7682832424883392487, "ro": 7223291528565862680,
    "ru": 8911989140118399619, "sd": 4791489272679823459, "sh": 5247335489585035333,
    "si": 5151209771353483688, "sk": 906841171861851373, "sl": 4524523410546767783,
    "sm": 6438885774622850088, "sn": 667651300545386994, "so": 3424023259825994677,
    "sq": 5004953853361383266, "sr": 2958846473073557482, "ss": 9084839605166631973,
    "st": 1437553406755071980, "sv": 4958143963089747877, "sw": 5128179410899824788,
    "ta": 1532736845269879240, "te": 8979608222684527323, "tg": 3300379104794255539,
    "th": 8348427309728988846, "ti": 2687394203984331406, "tk": 8728081113036876931,
    "tl": 5536176722691621839, "to": 5231909047029777422, "tr": 5964430973280552505,
    "uk": 3578850460057110410, "ur": 7589823463254376799, "uz": 5601626490491985162,
    "vi": 3741155905873931805, "yo": 4921151708715305490, "zh": 4593442970144109426,
    "zh-Hant": 2076066796458496830, "zh-tw": 7865090004429530491, "zu": 2441838299826051230,
}
MANGADOT.tachi_source_ids = set(_MANGADOT_TACHI_ID_BY_LANG.values())
_attach_language_ids(MANGADOT, _MANGADOT_TACHI_ID_BY_LANG)

REGISTRY = [
    MANGADEX, COMIX, MANGAPLUS, MANGAFIRE,
    ASURASCANS, MANGAKAKALOT, TCBSCANS, WEEBCENTRAL,
    BATCAVE, READCOMICSONLINE, MANGADOT,
]

BY_TACHI_SOURCE_ID = {}
for m in REGISTRY:
    for sid in m.tachi_source_ids:
        BY_TACHI_SOURCE_ID[sid] = m

BY_AIDOKU_ID = {m.aidoku_id: m for m in REGISTRY}
