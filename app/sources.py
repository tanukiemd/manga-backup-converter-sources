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
import re


class SourceMapping:
    def __init__(self, name, tachi_source_ids, aidoku_id,
                 tachi_to_aidoku_manga_id, aidoku_manga_url_from_id,
                 tachi_to_aidoku_chapter_id, aidoku_chapter_url_from_id,
                 tachi_to_aidoku_manga_url=None):
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

REGISTRY = [
    MANGADEX, COMIX, MANGAPLUS, MANGAFIRE,
    ASURASCANS, MANGAKAKALOT, TCBSCANS, WEEBCENTRAL,
    BATCAVE, READCOMICSONLINE,
]

BY_TACHI_SOURCE_ID = {}
for m in REGISTRY:
    for sid in m.tachi_source_ids:
        BY_TACHI_SOURCE_ID[sid] = m

BY_AIDOKU_ID = {m.aidoku_id: m for m in REGISTRY}
