import dataclasses
import timeit
from typing import Annotated, Literal

import rombob as r
from rombob import U8_B, U16_B


@dataclasses.dataclass
class A:
    id: Annotated[Literal[1], r.StructCodec(">B")]
    x: U16_B


@dataclasses.dataclass
class B:
    id: Annotated[Literal[2], r.StructCodec(">B")]
    x: U16_B
    y: U8_B


f = r.Factory("id")
f.register(A)
f.register(B)
a, b = A(1, 5), B(2, 6, 7)
da, db = f.encode(a), f.encode(b)
assert f.decode(da) == a and f.decode(db) == b
unk = bytes([9, 0, 0])


def run(fn, n=200_000, rep=7):
    return min(timeit.repeat(fn, number=n, repeat=rep)) / n * 1e9


print(f"Factory.encode   {run(lambda: f.encode(b)):7.0f} ns")
print(f"Factory.decode   {run(lambda: f.decode(db)):7.0f} ns")
print(f"Factory.decode(unknown) {run(lambda: f.decode(unk)):7.0f} ns")
c = r.get_codec(B)
print(f"r.encode(codec)  {run(lambda: r.encode(b, codec=c)):7.0f} ns")
print(f"r.decode(codec)  {run(lambda: r.decode(db, codec=c)):7.0f} ns")
w = r.Writer()
rr = r.Reader(db)


def _enc_to():
    del w.buffer[:]
    f.encode_to(b, w)


def _dec_from():
    rr.offset = 0
    f.decode_from(rr)


print(f"Factory.encode_to   {run(_enc_to):7.0f} ns")
print(f"Factory.decode_from {run(_dec_from):7.0f} ns")
print(f"c.encode         {run(lambda: c.encode(b)):7.0f} ns")
print(f"c.decode         {run(lambda: c.decode(db)):7.0f} ns")
