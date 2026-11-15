import dataclasses
import enum
import operator
import struct
import timeit
from typing import Annotated, Literal

import rombob as r
from rombob import U8_B, U16_B, U32_B, Len


class Color(enum.IntEnum):
    RED = 1
    GREEN = 2


@dataclasses.dataclass
class Foo:
    id: Annotated[Literal[7], r.StructCodec(">B")]
    byte: U8_B
    short: U16_B
    long: U32_B
    color: Annotated[Color, r.StructCodec(">B")]
    fixed_string: Annotated[str, Len(10)]
    fixed_list: Annotated[list[U8_B], Len(5)]


foo = Foo(7, 1, 2, 3, Color.GREEN, "abcdefghij", [1, 2, 3, 4, 5])
data = bytes(r.encode(foo))
assert r.decode(data, cls=Foo) == foo
codec = r.get_codec(Foo)

# Hand-"compiled" equivalent
S = struct.Struct(">BBHLB10s5B")
unpack_from = S.unpack_from
get = operator.attrgetter("id", "byte", "short", "long", "color")
e2m = Color._value2member_map_


def fast_decode(buf, off=0):
    v = unpack_from(buf, off)
    if v[0] != 7:
        raise r.BytesOperationError
    return Foo(v[0], v[1], v[2], v[3], e2m[v[4]], v[5].decode(), list(v[6:11]))


def fast_encode(x):
    return S.pack(*get(x), x.fixed_string.encode(), *x.fixed_list)


assert fast_decode(data) == foo and fast_encode(foo) == data

N = 50_000
cases = {
    "decode(cls=Foo)  [get_codec each call]": lambda: r.decode(data, cls=Foo),
    "decode(codec=...) [codec reused]": lambda: r.decode(data, codec=codec),
    "fast_decode (single Struct)": lambda: fast_decode(data),
    "encode(foo)      [get_codec each call]": lambda: r.encode(foo),
    "encode(codec=...) [codec reused]": lambda: r.encode(foo, codec=codec),
    "fast_encode (single Struct)": lambda: fast_encode(foo),
    "get_codec(Foo) alone": lambda: r.get_codec(Foo),
}
for name, fn in cases.items():
    best = min(timeit.repeat(fn, number=N, repeat=5)) / N * 1e6
    print(f"{name:42s} {best:8.2f} us")
