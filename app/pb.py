"""Minimal protobuf wire-format encode/decode helpers (no .proto compilation needed)."""
import struct
from collections import defaultdict


def decode_varint(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def parse(b):
    """Decode a flat list of (field_number, wire_type, raw_value) tuples."""
    i = 0
    out = []
    n = len(b)
    while i < n:
        k, i = decode_varint(b, i)
        field, wire = k >> 3, k & 7
        if wire == 0:
            v, i = decode_varint(b, i)
        elif wire == 1:
            v = b[i:i + 8]
            i += 8
        elif wire == 5:
            v = b[i:i + 4]
            i += 4
        elif wire == 2:
            length, i = decode_varint(b, i)
            v = b[i:i + length]
            i += length
        else:
            raise ValueError(f"unsupported wire type {wire}")
        out.append((field, wire, v))
    return out


def to_dict(buf):
    """Group parsed (field, wire, value) tuples by field number -> list of values."""
    d = defaultdict(list)
    for f, w, v in parse(buf):
        d[f].append(v)
    return d


def g1(d, key, default=None):
    return d[key][0] if d.get(key) else default


def as_str(v):
    return v.decode("utf-8", "replace")


def as_float(b):
    return struct.unpack("<f", b)[0]


# ---- encoding ----

def enc_varint(n):
    if n < 0:
        n &= (1 << 64) - 1
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def enc_tag(field, wire):
    return enc_varint((field << 3) | wire)


def enc_varint_field(field, n):
    return enc_tag(field, 0) + enc_varint(int(n))


def enc_bytes_field(field, b):
    return enc_tag(field, 2) + enc_varint(len(b)) + b


def enc_str_field(field, s):
    return enc_bytes_field(field, s.encode("utf-8"))


def enc_float_field(field, f):
    return enc_tag(field, 5) + struct.pack("<f", f)


def enc_message(field, submessage_bytes):
    return enc_bytes_field(field, submessage_bytes)
