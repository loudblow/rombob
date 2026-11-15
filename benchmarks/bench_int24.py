import struct
import timeit

N = 200_000


def bench(name, fn):
    best = min(timeit.repeat(fn, number=N, repeat=5)) / N * 1e9
    print(f"{name:58s} {best:7.0f} ns")


# ---------- isolated 24-bit read ----------
buf = memoryview(bytes(range(64)))
from_bytes = int.from_bytes
s3 = struct.Struct(">3s").unpack_from
sBH = struct.Struct(">BH").unpack_from
sI = struct.Struct(">I").unpack_from

print("== isolated U24_B read ==")
bench(
    "int.from_bytes(buf[o:o+3], byteorder=, signed=) [now]",
    lambda: from_bytes(buf[4:7], byteorder="big", signed=False),
)
bench(
    "int.from_bytes(buf[o:o+3], 'big') positional",
    lambda: from_bytes(buf[4:7], "big"),
)
bench(
    "unpack_from('>3s') + from_bytes", lambda: from_bytes(s3(buf, 4)[0], "big")
)


def bh():
    a, b = sBH(buf, 4)
    return (a << 16) | b


bench("unpack_from('>BH') + (a<<16)|b", bh)
bench(
    "unpack_from('>I', o-1) & 0xFFFFFF  (needs 1 byte before)",
    lambda: sI(buf, 3)[0] & 0xFFFFFF,
)

# ---------- in-class: U8 U16 U24 U32 U24 U16 ----------
print("== class-level: U8 U16 U24 U32 U24 U16 (6 fields) ==")
data = memoryview(bytes(range(16)))

g1 = struct.Struct(">BH").unpack_from
g2 = struct.Struct(">I").unpack_from
g3 = struct.Struct(">H").unpack_from


def split_groups():  # IntCodec breaks the group: 3 structs + 2 from_bytes
    o = 0
    a, b = g1(data, o)
    o += 3
    c = from_bytes(data[o : o + 3], "big")
    o += 3
    (d,) = g2(data, o)
    o += 4
    e = from_bytes(data[o : o + 3], "big")
    o += 3
    (f,) = g3(data, o)
    return (a, b, c, d, e, f)


one_3s = struct.Struct(">BH3sI3sH").unpack_from


def single_3s():
    a, b, c, d, e, f = one_3s(data, 0)
    return (a, b, from_bytes(c, "big"), d, from_bytes(e, "big"), f)


one_bh = struct.Struct(">BHBHIBHH").unpack_from


def single_bh():
    a, b, c1, c2, d, e1, e2, f = one_bh(data, 0)
    return (a, b, (c1 << 16) | c2, d, (e1 << 16) | e2, f)


assert split_groups() == single_3s() == single_bh()
bench("3 groups + 2x from_bytes (IntCodec breaks group)", split_groups)
bench("1 struct '>BH3sI3sH' + 2x from_bytes", single_3s)
bench("1 struct '>BHBHIBHH' + shifts", single_bh)

# ---------- 48-bit ----------
print("== U48_B read ==")
bench("from_bytes(buf[o:o+6], 'big')", lambda: from_bytes(buf[4:10], "big"))
sHI = struct.Struct(">HI").unpack_from


def hi():
    a, b = sHI(buf, 4)
    return (a << 32) | b


bench("unpack_from('>HI') + (a<<32)|b", hi)

# ---------- signed I24 ----------
print("== I24_B read (signed) ==")
bench(
    "from_bytes(..., 'big', signed=True)",
    lambda: from_bytes(buf[4:7], "big", signed=True),
)


def bh_signed():
    a, b = struct.Struct(">bH").unpack_from(buf, 4)
    return (a << 16) | b


sbH = struct.Struct(">bH").unpack_from


def bh_signed2():
    a, b = sbH(buf, 4)
    return (a << 16) | b


assert bh_signed2() == from_bytes(buf[4:7], "big", signed=True)
bench("unpack_from('>bH') + (a<<16)|b  (sign via 'b')", bh_signed2)

# ---------- write ----------
print("== write U8 U16 U24 U32 ==")
to_bytes = int.to_bytes
w_split1 = struct.Struct(">BH").pack
w_split2 = struct.Struct(">I").pack
w_one = struct.Struct(">BHBHI").pack
vals = (1, 2, 0x030405, 6)


def w_split():
    a, b, c, d = vals
    return w_split1(a, b) + to_bytes(c, 3, "big") + w_split2(d)


def w_shift():
    a, b, c, d = vals
    return w_one(a, b, c >> 16, c & 0xFFFF, d)


assert w_split() == w_shift()
bench("pack + to_bytes + pack + concat", w_split)
bench("single pack with c>>16, c&0xFFFF", w_shift)
