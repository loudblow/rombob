<div align="center">

# 🧩 Rombob

**Binary serialization for Python, driven by plain type hints.**

Describe your wire format as a [dataclass] or a [NamedTuple] — get a fast, validated encoder and decoder for free. Zero dependencies, pure python.

[Installation](#-installation) ·
[Quick Start](#-quick-start) ·
[Advanced Example](#-advanced-example) ·
[Annotations](#-annotations-cheat-sheet) ·
[Types](#-supported-types) ·
[Contributing](#-contributing)

</div>

---

## ✨ Why Rombob?

- 🏷️ **Just type hints** — no schema files, no code generation step, no base classes.
- ⚡ **Fast** — consecutive fixed-size fields are compiled into a single `struct` call.
- 🔗 **Dependent fields** — lengths and optional fields can depend on values read earlier.
- 🛡️ **Validated** — constraints (`Range`, `Gt`, `Predicate`, ...) are checked on read *and* write.
- 🔍 **Readable errors** — `trace_errors=True` points at the exact failing field, e.g. `Packet.points[0].x`.
- 🧠 **Stateless codecs** — build once, share freely.

## 📦 Installation

Install the latest unreleased code straight from Git:

```bash
pip install git+https://github.com/loudblow/rombob.git@main
```

## 🚀 Quick Start

```python
import dataclasses
import rombob


@dataclasses.dataclass
class Player:
    id: rombob.U8_B   # 1 byte, big-endian
    username: str     # UTF-8 with a 2-byte length prefix


# 📤 Serialize
encoded = rombob.encode(Player(id=1, username="Archer"))
print(encoded)  # b'\x01\x00\x06Archer'

# 📥 Deserialize
player = rombob.decode(encoded, cls=Player)
print(player)  # Player(id=1, username='Archer')
```

## 🔬 Advanced Example

A tiny network packet that uses most of the features at once: magic bytes, an enum,
a length taken from an earlier field, a conditional field, validation, nested
structures, and a raw tail.

```python
import dataclasses
import enum
from typing import Annotated, Literal

import rombob
from rombob import (
    I16_L, U8_B, Len, Named, Prefix, Range, Raw, When,
)


class Kind(enum.IntEnum):
    PING = 1
    CHAT = 2


@dataclasses.dataclass
class Point:
    x: I16_L                                    # little-endian int16
    y: I16_L


@dataclasses.dataclass
class Packet:
    magic: Literal[b"RB"]                       # constant, checked on read
    version: Annotated[Literal[1, 2], U8_B]     # only 1 or 2 is accepted
    kind: Annotated[Kind, U8_B]                 # enum stored as one byte
    count: Named[U8_B]                          # remembered as "count"
    points: Annotated[list[Point], Len(ref="count")]   # length = count
    has_token: Named[bool]
    token: Annotated[str | None, When(ref="has_token")]  # only if has_token
    hp: Annotated[U8_B, Range(0, 100)]          # validated 0..100
    tags: Annotated[list[Annotated[str, Prefix(U8_B)]], Prefix(U8_B)]
    payload: Raw                                # everything that is left


packet = Packet(
    magic=b"RB",
    version=1,
    kind=Kind.CHAT,
    count=2,
    points=[Point(1, 2), Point(-3, 4)],
    has_token=True,
    token="secret",
    hp=80,
    tags=["a", "bc"],
    payload=b"\xde\xad",
)

data = rombob.encode(packet)
assert rombob.decode(data, cls=Packet) == packet
```

Something went wrong? Ask for a trace and get the exact location:

```python
import dataclasses

rombob.encode(dataclasses.replace(packet, hp=200), trace_errors=True)
# BytesOperationError: Encoding failed at length 22 (Packet.hp):
#     200 violates Range(lo=0, hi=100)

rombob.decode(data[:5], cls=Packet, trace_errors=True)
# BytesOperationError: Decoding failed at offset 5 (Packet.points[0].x): ...
```

## 🧰 Annotations Cheat Sheet

Everything lives in `rombob.metadata` and is importable from `rombob`.

| Annotation | What it does | Example |
| ---------- | ------------ | ------- |
| `LE` / `BE` | Byte order for `IntCodec` (or use the `*_L` / `*_B` aliases) | `U16_L` |
| `Len(n)` | Exact length, no length prefix | `Annotated[str, Len(10)]` |
| `Len(ref=...)` | Length from an earlier `Named` field (or `lambda ctx: ...`); checked on write | `Len(ref="count")` |
| `Prefix(codec)` | Integer type of the length prefix (U16 big-endian by default) | `Prefix(U8_B)` |
| `Named[T]` | Remember the value so later fields can refer to it | `Named[U8_B]` |
| `When(...)` | Make a field conditional on earlier fields | `When(ref="has_token")` |
| `Optional[T]` / `T \| None` | Present while there is data left | `int \| None` |
| `Skip[T]` | Neither read nor written (needs a default) | `Skip[int]` |
| `Gt` `Ge` `Lt` `Le` `Range` | Numeric constraints, checked on read and write | `Range(1, 10)` |
| `Predicate(func)` | Any custom check | `Predicate(lambda v: v % 2 == 0)` |
| `Literal[...]` | Constants; `bytes`/`str` literals need no codec, `int` literals do | `Annotated[Literal[1, 2], U8_B]` |

## 🧱 Supported Types

Fields can be bools, integers, floats, strings, bytes, lists, tuples, sets,
frozensets, enums, named tuples, or other dataclasses — plus `Optional`, `Literal`,
`Generic`/`TypeVar`, fixed- and variable-length collections, and heterogeneous
tuples such as `tuple[int, str]`.

### Plain Python types (defaults)

| Python type | Encoding | Notes |
| ----------- | -------- | ----- |
| `bool` | `?` | Writes 1 or 0 |
| `str` | `U16(BE)` length + UTF-8 bytes | |
| `bytes` | `U16(BE)` length + bytes | |
| `int` | `I64(BE)` | Signed 64-bit |
| `float` | `F64(BE)` | IEEE 754 double |

### Aliases

Every alias comes in two flavors: `_B` (big-endian) and `_L` (little-endian).

| Family | Aliases |
| ------ | ------- |
| Unsigned ints | `U8` `U16` `U24` `U32` `U48` `U64` |
| Signed ints | `I8` `I16` `I24` `I32` `I48` `I64` |
| Floats | `F16` `F32` `F64` |
| Variable-length | `UVInt` (unsigned), `IVInt` (signed) |
| Rest of the buffer | `Raw` |

## ⚙️ Going Further

- **Fast paths** — `Codec.encode/decode` with an explicit codec, or `Factory` for
  dispatch by primary field. See `rombob.get_codec(cls)` to build and inspect a codec.
- **Streaming** — pass `reader=` / `writer=` to `decode` / `encode` to continue an
  existing buffer.
- **Benchmarks** — see [`benchmarks/`](benchmarks) (`bench.py`, `bench_int24.py`).

## 🤝 Contributing

```bash
make install   # poetry install + pre-commit hooks
make test      # pytest + coverage
make format    # ruff format
make lint      # pre-commit run
```

Pull requests and issues are welcome!

## 📚 References & Inspiration

- [bytechomp](https://github.com/AndrewSpittlemeister/bytechomp/tree/main)
- [bstruct](https://github.com/flxbe/bstruct)
- [pyserde](https://github.com/yukinarit/pyserde/tree/main)
- [pdc_struct](https://github.com/boxcake/pdc_struct)
- [dataclasses-struct](https://github.com/harrymander/dataclasses-struct)

[dataclass]: https://docs.python.org/3/library/dataclasses.html
[NamedTuple]: https://docs.python.org/3/library/typing.html#typing.NamedTuple
