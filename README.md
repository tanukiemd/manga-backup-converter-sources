# manga-backup-converter-sources

The open-source conversion engine and source-ID mapping tables behind
[chococornet.moe/convert](https://chococornet.moe/convert/) - a free tool to
convert manga library backups between **Tachiyomi / Mihon / Komikku**,
**Tachimanga** and **Aidoku**, keeping read progress, categories and tracking.

This repo has the engine plus a few CLI wrappers around it:

- **`app/`** - the actual conversion engine (protobuf/plist parsing, the
  merge logic, the source-ID mapping tables). This is the exact same code
  the website runs.
- **`cli.py`** - a command-line wrapper around that engine so you can
  convert a backup entirely on your own machine, no upload, no server, no
  internet connection needed once you've cloned this repo.
- **`compare_backups.py`** - same idea, for the "compare two backups of the
  same app" feature: newly added manga, manga no longer present, reading
  progress changes. Read-only, writes nothing back.
- **`find_duplicates.py`** - finds manga added from multiple different
  sources within one backup and writes a cleaned copy with the extras
  removed (keeping whichever has the most chapters read by default). Same
  format in, same format out.
- **`repair_backup.py`** - drops entries missing a url or title, collapses
  duplicate chapters within the same manga, and removes category tags
  pointing at a category that no longer exists. Same format in, same
  format out.
- **`wrapped_stats.py`** - total manga, chapters read, top sources, top
  genres, and oldest entry from a backup. The website turns this into a
  shareable image in the browser; here it's just printed (or dumped as
  JSON with `--json`).

## Using the CLI

Requires Python 3.10+, no extra dependencies (the engine only uses the
standard library).

```bash
git clone https://github.com/tanukiemd/manga-backup-converter-sources.git
cd manga-backup-converter-sources

python cli.py --from tachiyomi --to aidoku \
  --source my_library.tachibk \
  --out converted.aib
```

Add `--target existing_backup.aib` to merge into a backup you already have
in the target app, instead of starting from an empty one. Run
`python cli.py --help` for the full option list.

To compare two backups of the same app instead of converting between apps:

```bash
python compare_backups.py --app tachiyomi --old old_library.tachibk --new new_library.tachibk
```

Add `--json out.json` to also save the full result. Run
`python compare_backups.py --help` for the full option list.

To find (and optionally remove) manga duplicated across multiple sources
within one backup:

```bash
python find_duplicates.py --app tachiyomi --backup library.tachibk
python find_duplicates.py --app tachiyomi --backup library.tachibk --apply --out cleaned.tachibk
```

The second form keeps whichever entry in each duplicate group has the most
chapters read. Run `python find_duplicates.py --help` for the full option
list, including how to override the suggestion per group.

To clean up broken entries, duplicate chapters, and dangling category
references in a backup:

```bash
python repair_backup.py --app tachiyomi --backup library.tachibk
python repair_backup.py --app tachiyomi --backup library.tachibk --apply --out repaired.tachibk
```

To see your manga stats (total manga, chapters read, top sources, top genres, oldest entry):

```bash
python wrapped_stats.py --app tachiyomi --backup library.tachibk
```

## Why the source-ID mapping exists

Tachiyomi-ecosystem apps (Tachiyomi, Mihon, Komikku, Tachimanga) all run the
same extension ecosystem and share numeric source IDs and URL conventions,
so converting between them needs no translation at all. **Aidoku is a
completely separate app with its own extensions**, so every manga entry has
to be mapped individually: given a Tachiyomi-side manga/chapter URL,
`app/sources.py` defines how to compute the matching Aidoku manga/chapter
ID, and vice versa.

There is no way to derive this generically - two independently-written
extensions for the "same" website almost always invent their own, unrelated
internal ID scheme. Every mapping in this file was reverse-engineered
against **real paired backups** (the same manga added in both apps) or
against the actual open-source extension code on both sides - never
guessed. Sources not listed here are reported by the converter as "not
transferable" instead of being silently mismatched.

## Contributing a new source

Want to add a source that isn't mapped yet? Pull requests welcome. To verify
a mapping properly:

1. Add the same manga (ideally with a few chapters, at least one marked
   read) to your library in both apps, using the same source in each.
2. Create a backup from both apps.
3. Compare the manga/chapter URLs or IDs in each backup - `.tachibk` is
   gzip+protobuf, `.aib` is a binary plist, `.tmb` (Tachimanga) is a zip
   containing a SQLite db. Figure out the transform between them.

   `diff_tool.py` automates the tedious part of this step: point it at both
   backups and it matches manga by title, lines up the raw URLs/IDs for
   each match, and checks a few common id patterns (last URL segment,
   before/after a `-` or `.`) for you:

   ```bash
   python diff_tool.py --tachi library.tachibk --aidoku library.aib
   ```

   It only ever prints a suggestion - it never edits `sources.py` itself,
   and won't find anything for sources that need more custom logic than
   the patterns it checks for.
4. Add a `SourceMapping` entry following the existing examples in
   `app/sources.py`, plus a code comment saying what you verified it
   against.
5. Add yourself to the [Contributors](#contributors) list below in the same PR.

Please don't add a mapping based only on reading the extension source - as
several existing entries in this file document, that alone has produced
wrong guesses (different extension versions can use different URL formats
for the same site). Verify against real backup data if at all possible.

Can't easily figure out the transform by hand? The website's "test backup"
upload lets you send a real paired backup for manual review instead -
that's often faster than reverse-engineering it yourself.

## Contributors

People who've added a verified source mapping - thank you!

- [@tanukiemd](https://github.com/tanukiemd) - initial mapping set (MangaDex, MangaFire, MangaPlus, Comix, AsuraScans, Mangakakalot, TCB Scans, Weeb Central, BatCave, Read Comics Online)

Added a mapping? Add your line above in the same PR - GitHub handle and
which source(s) you mapped.

## License

MIT - see [LICENSE](LICENSE).
