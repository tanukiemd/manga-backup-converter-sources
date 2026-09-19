"""Compare two backups of the SAME app: what's newly added, what's no longer
present, and whose reading progress changed since the older backup. Read-only
- never writes anything back, unlike convert.py.
"""
from . import convert


def _read_any(app_name: str, data: bytes) -> list:
    from . import tachimanga as tm
    if app_name == "tachiyomi":
        return convert.read_tachibk(data)
    elif app_name == "tachimanga":
        mangas, _ = tm.read_tmb(data)
        return mangas
    elif app_name == "aidoku":
        mangas, _ = convert.read_aidoku(data)
        return mangas
    raise ValueError(f"unknown app {app_name}")


def compare_backups(bytes_a: bytes, bytes_b: bytes, app_name: str) -> dict:
    try:
        mangas_a = _read_any(app_name, bytes_a)
        mangas_b = _read_any(app_name, bytes_b)
    except convert._STRUCTURE_ERRORS as e:
        convert._reraise_as_format_error(app_name, e)

    by_key_a = {(m.source_id, m.url): m for m in mangas_a}
    by_key_b = {(m.source_id, m.url): m for m in mangas_b}
    keys_a, keys_b = set(by_key_a), set(by_key_b)

    added = sorted(
        ({"title": by_key_b[k].title} for k in keys_b - keys_a),
        key=lambda x: x["title"].lower(),
    )
    removed = sorted(
        ({"title": by_key_a[k].title} for k in keys_a - keys_b),
        key=lambda x: x["title"].lower(),
    )

    progress_changed = []
    unchanged_count = 0
    for k in keys_a & keys_b:
        ma, mb = by_key_a[k], by_key_b[k]
        read_a = {c.url for c in ma.chapters if c.read}
        read_b = {c.url for c in mb.chapters if c.read}
        newly_read = len(read_b - read_a)
        new_chapters = max(0, len(mb.chapters) - len(ma.chapters))
        if newly_read or new_chapters:
            progress_changed.append({
                "title": mb.title,
                "newly_read": newly_read,
                "new_chapters": new_chapters,
            })
        else:
            unchanged_count += 1
    progress_changed.sort(key=lambda x: x["title"].lower())

    return {
        "app": app_name,
        "total_a": len(mangas_a),
        "total_b": len(mangas_b),
        "added": added,
        "removed": removed,
        "progress_changed": progress_changed,
        "unchanged_count": unchanged_count,
    }
