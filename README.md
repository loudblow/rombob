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
The library is configured primarily through **Type Annotations**:
- **Byte Order:** Use `LE` (Little Endian) or `BE` (Big Endian) via `IntCodec`.
- **Length Overrides:** Use `Annotated[str, Len(10)]` to force a fixed-length field without a length header.
- **Optional Fields:** `Optional[T]` or `T | None` will trigger `OptionalCodec`, which checks the buffer length or a custom predicate before reading.
- **Custom Context:** The `Context` class can be initialized with a pre-existing buffer or a custom `data` dict to influence how `NamedCodec` behaves.

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
- Fixed- and dynamic-length `str`, `bytes`, `list`, `tuple`, `set`, `frozenset`
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
