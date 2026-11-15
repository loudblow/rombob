import dataclasses
import typing as t

import pytest
from models import Address, EnumIntegers, EnumStrings, Foo

from rombob import (
    BE,
    F16_B,
    F16_L,
    F32_B,
    F32_L,
    F64_B,
    F64_L,
    I8_B,
    I8_L,
    I16_B,
    I16_L,
    I24_B,
    I24_L,
    I32_B,
    I32_L,
    I48_B,
    I48_L,
    I64_B,
    I64_L,
    LE,
    U8_B,
    U8_L,
    U16_B,
    U16_L,
    U24_B,
    U24_L,
    U32_B,
    U32_L,
    U48_B,
    U48_L,
    U64_B,
    U64_L,
    BytesCodec,
    ClassCodec,
    CollectionCodec,
    EnumCodec,
    IntCodec,
    IVInt,
    Len,
    LiteralCodec,
    Named,
    NamedCodec,
    OptionalCodec,
    Raw,
    RawCodec,
    StringCodec,
    StructCodec,
    UVInt,
    VarIntCodec,
    encode,
    get_codec,
)

T = t.TypeVar("T")


@dataclasses.dataclass
class BinutilDC:
    CLASSVAR: t.ClassVar[int] = 123
    address: Address
    named: Named[str]


# - - - - - get_codec - - - - - #


@pytest.mark.parametrize(
    "hint, expected",
    (
        (bool, StructCodec("?")),
        (int, StructCodec(">q")),
        (float, StructCodec(">d")),
        (I8_L, StructCodec("<b")),
        (I8_B, StructCodec(">b")),
        (U8_L, StructCodec("<B")),
        (U8_B, StructCodec(">B")),
        (I16_L, StructCodec("<h")),
        (I16_B, StructCodec(">h")),
        (U16_L, StructCodec("<H")),
        (U16_B, StructCodec(">H")),
        (I24_L, IntCodec(length=3, byteorder=LE, signed=True)),
        (I24_B, IntCodec(length=3, byteorder=BE, signed=True)),
        (U24_L, IntCodec(length=3, byteorder=LE, signed=False)),
        (U24_B, IntCodec(length=3, byteorder=BE, signed=False)),
        (I32_L, StructCodec("<i")),
        (I32_B, StructCodec(">i")),
        (U32_L, StructCodec("<I")),
        (U32_B, StructCodec(">I")),
        (I48_L, IntCodec(length=6, byteorder=LE, signed=True)),
        (I48_B, IntCodec(length=6, byteorder=BE, signed=True)),
        (U48_L, IntCodec(length=6, byteorder=LE, signed=False)),
        (U48_B, IntCodec(length=6, byteorder=BE, signed=False)),
        (I64_L, StructCodec("<q")),
        (I64_B, StructCodec(">q")),
        (U64_L, StructCodec("<Q")),
        (U64_B, StructCodec(">Q")),
        (F16_L, StructCodec("<e")),
        (F16_B, StructCodec(">e")),
        (F32_L, StructCodec("<f")),
        (F32_B, StructCodec(">f")),
        (F64_L, StructCodec("<d")),
        (F64_B, StructCodec(">d")),
        (IVInt, VarIntCodec(signed=True)),
        (UVInt, VarIntCodec(signed=False)),
        (str, StringCodec(len_codec=StructCodec(">H"))),
        (bytes, BytesCodec(len_codec=StructCodec(">H"))),
        (
            list[str],
            CollectionCodec(
                cls=list,
                item_codec=StringCodec(),
                len_codec=StructCodec(">H"),
            ),
        ),
        (
            tuple[tuple[U8_B, ...], ...],
            CollectionCodec(
                cls=tuple,
                len_codec=StructCodec(">H"),
                item_codec=CollectionCodec(
                    cls=tuple,
                    len_codec=StructCodec(">H"),
                    item_codec=StructCodec(">B"),
                ),
            ),
        ),
        (
            t.Annotated[tuple[str, ...], Len(1)],
            CollectionCodec(
                cls=tuple,
                len_codec=StructCodec(">H"),
                item_codec=StringCodec(),
                length=1,
            ),
        ),
        (
            set[str],
            CollectionCodec(
                cls=set,
                len_codec=StructCodec(">H"),
                item_codec=StringCodec(),
            ),
        ),
        (
            frozenset[str],
            CollectionCodec(
                cls=frozenset,
                len_codec=StructCodec(">H"),
                item_codec=StringCodec(),
            ),
        ),
        (Raw, RawCodec()),
        (t.Annotated[bytes, Len(1)], BytesCodec(length=1)),
        (str | None, OptionalCodec(codec=StringCodec())),
        # TODO ValidatorCodec
        (EnumStrings, EnumCodec(codec=StringCodec(), cls=EnumStrings)),
        (
            t.Annotated[EnumIntegers, U8_B],
            EnumCodec(codec=StructCodec(">B"), cls=EnumIntegers),
        ),
        (
            t.Annotated[t.Literal[1, 2, 3], StructCodec(">B")],
            LiteralCodec(codec=StructCodec(">B"), literals=(1, 2, 3)),
        ),
        (Named[str], StringCodec()),
        (
            Address,
            ClassCodec(
                cls=Address,
                fields={
                    "ip": StringCodec(),
                    "port": StructCodec(">H"),
                }.items(),
            ),
        ),
        (
            BinutilDC,
            ClassCodec(
                cls=BinutilDC,
                fields={
                    "address": ClassCodec(
                        cls=Address,
                        fields={
                            "ip": StringCodec(),
                            "port": StructCodec(">H"),
                        }.items(),
                    ),
                    "named": NamedCodec(codec=StringCodec(), key="named"),
                }.items(),
            ),
        ),
    ),
)
def test_get_codec(hint, expected):
    assert get_codec(hint) == expected


# - - - - - codec cache - - - - - #


def test_get_codec_is_memoized():
    assert get_codec(Foo) is get_codec(Foo)
    assert get_codec(Foo) is not get_codec(Foo, compile=False)
    assert get_codec(list[int]) is get_codec(list[int])


def test_same_name_classes_get_different_codecs():
    def make():
        @dataclasses.dataclass
        class Same:
            a: U8_B

        return Same

    a, b = make(), make()
    assert a.__name__ == b.__name__
    assert get_codec(a) is not get_codec(b)
    assert get_codec(a).cls is a
    assert get_codec(b).cls is b


def test_unhashable_hint_still_works():
    hint = t.Annotated[int, {"a": 1}, StructCodec(">H")]
    codec = get_codec(hint)
    assert codec == StructCodec(">H")
    assert encode(5, codec=codec) == b"\x00\x05"


def test_codecs_are_plain_classes():
    assert isinstance(StructCodec(">B"), StructCodec)
    assert StructCodec(">B") == StructCodec(">B")
    assert StructCodec(">B") != StructCodec(">H")
    assert hash(StructCodec(">B")) == hash(StructCodec(">B"))
    assert isinstance(get_codec(Foo), ClassCodec)
    with pytest.raises(Exception):  # noqa: B017, PT011
        get_codec(Foo).cls = int  # frozen
