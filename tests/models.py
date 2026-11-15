"""Plain model classes shared by several test modules."""

import dataclasses
import enum
import typing as t

from rombob import U8_B, U16_B, U32_B, Len


class EnumIntegers(enum.IntEnum):
    a = 0
    b = 1


class EnumStrings(str, enum.Enum):
    a = "a"
    b = "bb"


class Address(t.NamedTuple):
    ip: str
    port: U16_B


@dataclasses.dataclass
class Foo:
    byte: U8_B
    short: U16_B
    long: U32_B
    fixed_string: t.Annotated[str, Len(10)]
    fixed_list: t.Annotated[list[U8_B], Len(5)]
