"""Bounded decompression helpers.

Backup files are gzip (.tachibk) or zip-in-zip (.tmb) containers, and both
formats let a small attacker-controlled input decompress to something much
larger (a "decompression bomb") - a single-layer gzip/DEFLATE stream can
realistically hit ~1000:1 ratios, and .tmb nests two zip layers, which
multiplies that further. Since Caddy caps uploads at 20MB, an unbounded
gzip.decompress()/ZipFile.read() on that input could still balloon into
tens of GB in memory - enough to OOM the whole host, not just this
container, since other services share the same box.

These helpers cap decompressed output and raise a clear, catchable error
instead, so a bomb turns into an ordinary "conversion failed" response
rather than a crash.
"""
import zlib
import zipfile

MAX_DECOMPRESSED_BYTES = 200 * 1024 * 1024  # 200 MB - generous for even a huge library


class DecompressionBombError(ValueError):
    pass


def bounded_gzip_decompress(data: bytes, max_size: int = MAX_DECOMPRESSED_BYTES) -> bytes:
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)  # 16+MAX_WBITS selects gzip framing
    result = d.decompress(data, max_size + 1)
    if d.unconsumed_tail:
        raise DecompressionBombError(
            f"This backup decompresses to more than {max_size // (1024 * 1024)}MB - "
            f"refusing to process it."
        )
    result += d.flush()
    if len(result) > max_size:
        raise DecompressionBombError(
            f"This backup decompresses to more than {max_size // (1024 * 1024)}MB - "
            f"refusing to process it."
        )
    return result


def bounded_zip_read(zf: zipfile.ZipFile, name: str, max_size: int = MAX_DECOMPRESSED_BYTES) -> bytes:
    info = zf.getinfo(name)
    if info.file_size > max_size:
        raise DecompressionBombError(
            f"'{name}' claims to be over {max_size // (1024 * 1024)}MB uncompressed - "
            f"refusing to process it."
        )
    with zf.open(name) as f:
        data = f.read(max_size + 1)
    if len(data) > max_size:
        raise DecompressionBombError(
            f"'{name}' decompresses to more than {max_size // (1024 * 1024)}MB - "
            f"refusing to process it."
        )
    return data
