# Rombob
Rombob is a lightweight library designed to handle binary data serialization and deserialization using standard Python [type hints]. It is designed to make getting started quick and easy. By defining your data structures as [dataclasses] or [named tuples], you can automatically generate codecs that handle byte-level transformations, byte-ordering, and variable-length encoding.

[dataclasses]: https://docs.python.org/3/library/dataclasses.html
[named tuples]: https://docs.python.org/3/library/typing.html#typing.NamedTuple
[type hints]: https://docs.python.org/3/library/typing.html

## Installation

It can be installed via Git for the latest unreleased code:
```bash
pip install https://github.com/loudblow/rombob.git@main
```

## A Simple Examle
```python
import typing
import dataclasses
import rombob

@dataclasses.dataclass
class Player:
    id: rombob.U8_B
    username: str  # Defaults to UTF-8 with a 2-byte length header

# Prepare data
player = Player(
	id=1,
	username="Archer",
)

# Serialize
encoded = rombob.encode(player)
print(encoded)  # b'\x01\x00\x06Archer'

# Deserialize
data = b'\x01\x00\x06Archer'
decoded_player = rombob.decode(data, Player)
print(decoded_player.id)  # 1
print(decoded_player.username)  # Archer
```

## Configuration Options
The library is configured primarily through **Type Annotations** (all of them
live in `rombob.metadata` and are importable from `rombob`):
- **Byte Order:** Use `LE` (Little Endian) or `BE` (Big Endian) via `IntCodec`.
- **Length:** `Annotated[str, Len(10)]` is exactly 10 bytes, no length header. `Len(ref="count")` takes the length from an earlier `Named` field (or from `Len(ref=lambda ctx: ...)`), and writing checks that it matches. `Prefix(U8_B)` changes the integer the length is stored with (U16 big-endian by default). `Len` works for `str`, `bytes`, collections and `str`/`bytes` literals.
- **Literals:** `Literal[b"MAGIC"]` and `Literal["ab", "cd"]` need no codec, their size is known. Only integer literals need an explicit one, e.g. `Annotated[Literal[1, 2], U8_B]`.
- **Constraints:** `Gt`, `Ge`, `Lt`, `Le`, `Range(lo, hi)` and `Predicate(func)` are checked when reading and when writing, e.g. `Annotated[U8_B, Range(1, 10)]`.
- **Optional Fields:** `Optional[T]` or `T | None` is present while there is data left. `Annotated[T | None, When(lambda ctx: "token" in ctx.data)]` (or `When(ref="has_token")`) makes presence depend on earlier `Named` fields; writing a value that disagrees with the condition fails.
- **Skipped Fields:** `Skip[int]` fields (they need a default) are neither read nor written. `ClassVar`s are ignored as well.
- **Reader / Writer:** `Reader` and `Writer` hold the buffer position and a shared `data` dict (filled by `Named` fields). Pass `reader=`/`writer=` to `decode`/`encode` to continue an existing buffer.
- **Errors:** pass `trace_errors=True` to `encode`/`decode` (or `Codec.encode`, etc.) to get the failing field in the message, e.g. `Msg.header.items[3].name`. The value is run once more on a slower path, only when it failed.

## Supported Data Types
Fields on the classes can be bools, integers, floats, strings, bytes, lists, tuples, sets, frozensets, named tuples, or other dataclasses:
```python
from rombob import (
    U8_B,  # 8-bit unsigned integer
    U16_B,  # 16-bit unsigned integer
    U24_B,  # 24-bit unsigned integer
    U32_B,  # 32-bit unsigned integer
    U64_B,  # 64-bit unsigned integer
    UVInt,  # variable-length unsigned integer
    I8_B,  # 8-bit signed integer
    I16_B,  # 16-bit signed integer
    I24_B,  # 24-bit signed integer
    I32_B,  # 32-bit signed integer
    I64_B,  # 64-bit signed integer
    F16_B,  # 16-bit float
    F32_B,  # 32-bit float
    F64_B,  # 64-bit float
    IVInt,  # variable-length signed integer
    Raw,  # reads and writes remaining data
)
```

`Rombob` also supports Python typing features:
- `typing.Literal`
- `typing.Generic` and `typing.TypeVar`
- Fixed- and dynamic-length `str`, `bytes`, `list`, `tuple[X, ...]`, `set`, `frozenset`
- Heterogeneous tuples: `tuple[int, str]`
- `typing.NamedTuple`
- `t.Optional`
- `dataclasses.dataclass`
- `enum.Enum`

### Type Aliases

| Python Type Name | Format / Encoding | Notes                                |
| ---------------- | ----------------- | ------------------------------------ |
| bool             | `?`               | Writes 1 or 0                        |
| str              | `U16(BE) + bytes` | UTF-8 string, with U16 length prefix |
| bytes            | `U16(BE) + bytes` | bytes with U16 length prefix         |
| int              | `I64(BE)`         | Signed 64-bit integer                |
| float            | `F64(BE)`         | IEEE754 double precision             |

## Contributing
```bash
# Install dev dependencies
poetry install --with dev

# Run tests
make test

# Format code
make format
```

## Reference
[bytechomp](https://github.com/AndrewSpittlemeister/bytechomp/tree/main)
[bstruct](https://github.com/flxbe/bstruct)
[pyserde](https://github.com/yukinarit/pyserde/tree/main)
[pdc_struct](https://github.com/boxcake/pdc_struct)
[dataclasses-struct](https://github.com/harrymander/dataclasses-struct)
