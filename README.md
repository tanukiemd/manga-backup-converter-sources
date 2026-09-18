# manga-backup-converter-sources

Source-ID mapping tables used by [chococornet.moe/convert](https://chococornet.moe/convert/) -
a free tool to convert manga library backups between **Tachiyomi / Mihon / Komikku**,
**Tachimanga** and **Aidoku**, keeping read progress, categories and tracking.

## Why this repo exists

Tachiyomi-ecosystem apps (Tachiyomi, Mihon, Komikku, Tachimanga) all run the same
extension ecosystem and share numeric source IDs and URL conventions, so
converting between them needs no translation at all. **Aidoku is a completely
separate app with its own extensions**, so every manga entry has to be mapped
individually: given a Tachiyomi-side manga/chapter URL, this file defines how
to compute the matching Aidoku manga/chapter ID, and vice versa.

There is no way to derive this generically - two independently-written
extensions for the "same" website almost always invent their own, unrelated
internal ID scheme. Every mapping in this file was reverse-engineered against
**real paired backups** (the same manga added in both apps) or against the
actual open-source extension code on both sides - never guessed. Sources not
listed here are reported by the converter as "not transferable" instead of
being silently mismatched.

## Contributing a new source

Want to add a source that isn't mapped yet? Pull requests welcome. To verify a
mapping properly:

1. Add the same manga (ideally with a few chapters, at least one marked read)
   to your library in both apps, using the same source in each.
2. Create a backup from both apps.
3. Compare the manga/chapter URLs or IDs in each backup - `.tachibk` is
   gzip+protobuf, `.aib` is a binary plist, `.tmb` (Tachimanga) is a zip
   containing a SQLite db. Figure out the transform between them.
4. Add a `SourceMapping` entry following the existing examples in
   `sources.py`, plus a code comment saying what you verified it against.

Please don't add a mapping based only on reading the extension source - as
several existing entries in this file document, that alone has produced wrong
guesses (different extension versions can use different URL formats for the
same site). Verify against real backup data if at all possible.

## License

MIT - see [LICENSE](LICENSE).
