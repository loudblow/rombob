import dataclasses
import enum
import typing as t

import pytest
from models import Foo

import rombob as rb
from rombob import (
    BE,
    F32_B,
    I24_B,
    I48_L,
    LE,
    U8_B,
    U16_B,
    U16_L,
    U24_B,
    U24_L,
    U32_B,
    U48_B,
    BytesCodec,
    BytesOperationError,
    EnumCodec,
    IntCodec,
    Len,
    Named,
    OptionalCodec,
    StringCodec,
    StructCodec,
    UVInt,
    ValidatorCodec,
    Writer,
    decode,
    encode,
    get_codec,
)


class Color(enum.IntEnum):
    RED = 1
    GREEN = 2


def roundtrip(value, hint=None):
    "Encode/decode through both compiled and plain codecs and compare"
    hint = hint or type(value)
    compiled = get_codec(hint)
    plain = get_codec(hint, compile=False)
    assert compiled is not plain
    data = encode(value, codec=compiled)
    assert encode(value, codec=plain) == data
    assert decode(data, codec=compiled) == value
    assert decode(data, codec=plain) == value
    return data


# - - - - - segment layout - - - - - #


def test_repr_single_segment():
    assert repr(get_codec(Foo)) == (
        "ClassCodec(cls=Foo, segments=[StructSegment(format='>BHI10s5B')])"
    )


def test_repr_plain_codec_has_no_segments():
    assert repr(get_codec(Foo, compile=False)) == (
        "ClassCodec(cls=Foo, fields=['byte', 'short', 'long', "
        "'fixed_string', 'fixed_list'])"
    )


def test_repr_group_dynamic_group():
    @dataclasses.dataclass
    class Mixed:
        a: U8_B
        b: U16_B
        n: UVInt
        c: U32_B

    assert repr(get_codec(Mixed)) == (
        "ClassCodec(cls=Mixed, segments=[StructSegment(format='>BH'), "
        "DynamicSegment(codec=VarIntCodec), StructSegment(format='>I')])"
    )


def test_repr_byte_order_split():
    @dataclasses.dataclass
    class Orders:
        a: U16_B
        b: U16_L
        c: U16_L
        d: U16_B

    assert repr(get_codec(Orders)) == (
        "ClassCodec(cls=Orders, segments=[StructSegment(format='>H'), "
        "StructSegment(format='<HH'), StructSegment(format='>H')])"
    )


def test_repr_one_byte_items_join_any_group():
    @dataclasses.dataclass
    class Joined:
        a: rb.U8_L
        b: U16_L
        c: rb.I8_B
        d: t.Annotated[bytes, Len(3)]
        e: U16_L

    assert repr(get_codec(Joined)) == (
        "ClassCodec(cls=Joined, segments=[StructSegment(format='<BHb3sH')])"
    )


def test_repr_nested_classes_are_flattened():
    @dataclasses.dataclass
    class Inner:
        a: U8_B
        b: U24_B

    @dataclasses.dataclass
    class Middle:
        inner: Inner
        c: U16_B

    @dataclasses.dataclass
    class Outer:
        head: U8_B
        middle: Middle
        tail: U32_B

    assert repr(get_codec(Outer)) == (
        "ClassCodec(cls=Outer, segments=[StructSegment(format='>BBBHHI')])"
    )
    value = Outer(1, Middle(Inner(2, 0xABCDEF), 3), 4)
    assert roundtrip(value) == bytes.fromhex("01 02 abcdef 0003 00000004")


def test_repr_nested_class_with_dynamic_field_is_not_flattened():
    @dataclasses.dataclass
    class Inner:
        a: U8_B
        n: UVInt

    @dataclasses.dataclass
    class Outer:
        x: U8_B
        inner: Inner
        y: U8_B

    assert repr(get_codec(Outer)) == (
        "ClassCodec(cls=Outer, segments=[StructSegment(format='>B'), "
        "DynamicSegment(codec=ClassCodec), StructSegment(format='>B')])"
    )
    roundtrip(Outer(1, Inner(2, 300), 3))


def test_repr_optional_is_a_boundary():
    @dataclasses.dataclass
    class Opt:
        a: U8_B
        b: U16_B | None

    assert repr(get_codec(Opt)) == (
        "ClassCodec(cls=Opt, segments=[StructSegment(format='>B'), "
        "OptionalSegment(format='>H')])"
    )
    assert roundtrip(Opt(1, 2)) == b"\x01\x00\x02"
    assert roundtrip(Opt(1, None)) == b"\x01"


def test_generated_source_is_available():
    codec = get_codec(Foo)
    assert "def read(" in codec.source
    assert "def write(" in codec.source


# - - - - - compiled vs plain - - - - - #


@dataclasses.dataclass
class Everything:
    lit: t.Annotated[t.Literal[1, 2], StructCodec(">B")]
    wide_lit: t.Annotated[t.Literal[0x0102, 0x0304], StructCodec(">H")]
    color: t.Annotated[Color, StructCodec(">B")]
    u24: U24_B
    i24: rb.I24_L
    u48: rb.U48_B
    i48: rb.I48_L
    f: rb.F32_B
    flag: bool
    text: t.Annotated[str, Len(4)]
    raw: t.Annotated[bytes, Len(2)]
    arr: t.Annotated[tuple[rb.I16_L, ...], Len(3)]
    named: Named[U8_B]
    validated: t.Annotated[
        int,
        ValidatorCodec(
            codec=StructCodec(">H"),
            read_validator=lambda v: v + 1,
            write_validator=lambda v: v - 1,
        ),
    ]
    var: UVInt
    opt: U16_B | None = None


def test_everything_roundtrip():
    value = Everything(
        lit=2,
        wide_lit=0x0304,
        color=Color.GREEN,
        u24=0xFFFFFF,
        i24=-0x800000,
        u48=0xFFFFFFFFFFFF,
        i48=-0x800000000000,
        f=1.5,
        flag=True,
        text="héa",
        raw=b"\x00\xff",
        arr=(-1, 0, 1),
        named=9,
        validated=10,
        var=300,
        opt=7,
    )
    data = roundtrip(value)
    assert data[:3] == b"\x02\x03\x04"


def test_named_is_set_by_compiled_codec():
    @dataclasses.dataclass
    class Cls:
        a: Named[U8_B]
        b: Named[UVInt]

    codec = get_codec(Cls)
    w = Writer()
    codec.write(Cls(1, 300), w)
    assert w.data == {"a": 1, "b": 300}
    r = w.to_reader()
    assert codec.read(r) == Cls(1, 300)
    assert r.data == {"a": 1, "b": 300}


def test_predicate_sees_named_value():
    @dataclasses.dataclass
    class Cls:
        has_tail: Named[U8_B]
        tail: t.Annotated[
            int,
            OptionalCodec(
                codec=StructCodec(">H"),
                predicate=lambda ctx: ctx.data["has_tail"] == 1,
            ),
        ] = None

    assert roundtrip(Cls(1, 5)) == b"\x01\x00\x05"
    assert roundtrip(Cls(0, None)) == b"\x00"


def test_namedtuple():
    class Pair(t.NamedTuple):
        a: U8_B
        b: U24_L

    assert repr(get_codec(Pair)) == (
        "ClassCodec(cls=Pair, segments=[StructSegment(format='<BHB')])"
    )
    value = Pair(1, 0x030201)
    assert roundtrip(value) == b"\x01\x01\x02\x03"


def test_generic_class():
    T = t.TypeVar("T")

    @dataclasses.dataclass
    class Box(t.Generic[T]):
        item: T

    assert get_codec(Box[int]) is not get_codec(Box[str])
    assert get_codec(Box[int]) is get_codec(Box[int])
    assert repr(get_codec(Box[int])) == (
        "ClassCodec(cls=Box, segments=[StructSegment(format='>q')])"
    )
    roundtrip(Box(5), Box[int])
    roundtrip(Box("ab"), Box[str])


def test_kw_only_dataclass():
    @dataclasses.dataclass(kw_only=True)
    class Kw:
        a: U8_B
        b: U8_B

    assert roundtrip(Kw(a=1, b=2)) == b"\x01\x02"


# - - - - - literals - - - - - #


def test_literal_fails_fast_on_raw_bytes():
    @dataclasses.dataclass
    class Cls:
        id: t.Annotated[t.Literal[7], StructCodec(">B")]
        a: U32_B

    codec = get_codec(Cls)
    assert "not in" in codec.source.split("unpack")[0] or "view[off" in (
        codec.source
    )
    # the buffer is too short for the rest, but the literal is checked first
    with pytest.raises(BytesOperationError, match="Literal"):
        decode(b"\x08", codec=codec)
    assert decode(b"\x07\x00\x00\x00\x01", codec=codec) == Cls(7, 1)


@pytest.mark.parametrize("compile", [True, False])
def test_literal_write_validates(compile):
    @dataclasses.dataclass
    class Cls:
        id: t.Annotated[t.Literal[1, 2], StructCodec(">H")]

    codec = get_codec(Cls, compile=compile)
    assert encode(Cls(2), codec=codec) == b"\x00\x02"
    with pytest.raises(BytesOperationError, match="Literal"):
        encode(Cls(3), codec=codec)
    with pytest.raises(BytesOperationError, match="Literal"):
        decode(b"\x00\x03", codec=codec)


def test_literal_negative_signed():
    @dataclasses.dataclass
    class Cls:
        id: t.Annotated[t.Literal[-1], StructCodec(">b")]

    assert roundtrip(Cls(-1)) == b"\xff"


# - - - - - enums, wrong sizes - - - - - #


@pytest.mark.parametrize("compile", [True, False])
def test_enum_unknown_value(compile):
    @dataclasses.dataclass
    class Cls:
        color: t.Annotated[Color, StructCodec(">B")]

    codec = get_codec(Cls, compile=compile)
    with pytest.raises(BytesOperationError, match="not a valid Color"):
        decode(b"\x09", codec=codec)
    with pytest.raises(BytesOperationError):
        encode(Cls(9), codec=codec)


@pytest.mark.parametrize("compile", [True, False])
def test_wrong_fixed_lengths(compile):
    codec = get_codec(Foo, compile=compile)
    good = Foo(1, 2, 3, "abcdefghij", [1, 2, 3, 4, 5])
    assert decode(encode(good, codec=codec), codec=codec) == good
    for bad in (
        Foo(1, 2, 3, "short", [1, 2, 3, 4, 5]),
        Foo(1, 2, 3, "abcdefghij", [1, 2, 3, 4]),
        Foo(1, 2, 3, "abcdefghij", [1, 2, 3, 4, 5, 6]),
        Foo(256, 2, 3, "abcdefghij", [1, 2, 3, 4, 5]),
    ):
        w = Writer(bytearray(b"keep"))
        with pytest.raises(BytesOperationError):
            encode(bad, codec=codec, writer=w)
        assert bytes(w.buffer) == b"keep"


def test_zero_length_fixed_str_and_bytes():
    @dataclasses.dataclass
    class Cls:
        s: t.Annotated[str, Len(0)]
        n: U8_B

    # Len(0) is a string of exactly zero bytes
    assert roundtrip(Cls("", 1)) == b"\x01"
    with pytest.raises(BytesOperationError):
        encode(Cls("x", 1))

    codec = rb.StringCodec(length=0)
    assert decode(b"rest", codec=codec) == ""
    assert encode("", codec=codec) == b""
    with pytest.raises(BytesOperationError):
        encode("a", codec=codec)


# - - - - - 24/48 bit integers - - - - - #


@pytest.mark.parametrize("length, bits", [(3, 24), (6, 48)])
@pytest.mark.parametrize("order", [BE, LE])
@pytest.mark.parametrize("signed", [True, False])
def test_wide_ints(length, bits, order, signed):
    codec = IntCodec(length=length, byteorder=order, signed=signed)
    hint = t.Annotated[int, codec]

    @dataclasses.dataclass
    class Cls:
        first: U8_B
        value: hint
        last: U8_B

    assert "StructSegment" in repr(get_codec(Cls))
    lo, hi = (
        (-(1 << (bits - 1)), (1 << (bits - 1)) - 1)
        if signed
        else (0, (1 << bits) - 1)
    )
    for v in (lo, hi, 0, 1, hi // 2):
        data = roundtrip(Cls(1, v, 2))
        assert (
            data == b"\x01" + v.to_bytes(length, order, signed=signed) + b"\x02"
        )
    for bad in (lo - 1, hi + 1):
        with pytest.raises(BytesOperationError):
            encode(Cls(1, bad, 2))
        with pytest.raises(BytesOperationError):
            encode(Cls(1, bad, 2), codec=get_codec(Cls, compile=False))


# - - - - - literals/enums over every fixed-size codec - - - - - #


class StrEnum_(enum.Enum):
    AB = "ab"
    CD = "cd"


class BytesEnum_(enum.Enum):
    AB = b"ab"
    CD = b"cd"


# (hint, good value, good bytes, bad bytes)
LITERAL_CASES = {
    "u8": (t.Annotated[t.Literal[1, 2], U8_B], 2, b"\x02", b"\x03"),
    "u24": (
        t.Annotated[t.Literal[1, 2], U24_B],
        2,
        b"\x00\x00\x02",
        b"\x00\x00\x03",
    ),
    "u24_le": (
        t.Annotated[t.Literal[0x010203], U24_L],
        0x010203,
        b"\x03\x02\x01",
        b"\x00\x00\x00",
    ),
    "i24": (
        t.Annotated[t.Literal[-2], I24_B],
        -2,
        b"\xff\xff\xfe",
        b"\x00\x00\x01",
    ),
    "u48": (
        t.Annotated[t.Literal[5], U48_B],
        5,
        b"\x00\x00\x00\x00\x00\x05",
        b"\x00\x00\x00\x00\x00\x06",
    ),
    "f32": (
        t.Annotated[t.Literal[1.5], F32_B],
        1.5,
        b"\x3f\xc0\x00\x00",
        b"\x00\x00\x00\x00",
    ),
    "bool": (
        t.Annotated[t.Literal[True], StructCodec("?")],
        True,
        b"\x01",
        b"\x00",
    ),
    "str": (t.Annotated[t.Literal["ab", "cd"], Len(2)], "cd", b"cd", b"zz"),
    "bytes": (t.Annotated[t.Literal[b"ab"], Len(2)], b"ab", b"ab", b"zz"),
    "int_enum_u8": (
        t.Annotated[
            t.Literal[Color.GREEN],
            EnumCodec(codec=StructCodec(">B"), cls=Color),
        ],
        Color.GREEN,
        b"\x02",
        b"\x01",
    ),
    "int_enum_u24": (
        t.Annotated[
            t.Literal[Color.GREEN],
            EnumCodec(codec=U24_B.__metadata__[0], cls=Color),
        ],
        Color.GREEN,
        b"\x00\x00\x02",
        b"\x00\x00\x01",
    ),
    "int_enum_i48": (
        t.Annotated[
            t.Literal[Color.RED],
            EnumCodec(codec=I48_L.__metadata__[0], cls=Color),
        ],
        Color.RED,
        b"\x01\x00\x00\x00\x00\x00",
        b"\x02\x00\x00\x00\x00\x00",
    ),
    "str_enum": (
        t.Annotated[
            t.Literal[StrEnum_.CD],
            EnumCodec(codec=StringCodec(length=2), cls=StrEnum_),
        ],
        StrEnum_.CD,
        b"cd",
        b"ab",
    ),
    "bytes_enum": (
        t.Annotated[
            t.Literal[BytesEnum_.AB],
            EnumCodec(codec=BytesCodec(length=2), cls=BytesEnum_),
        ],
        BytesEnum_.AB,
        b"ab",
        b"cd",
    ),
}


# floats and bools can't be matched on raw bytes (-0.0 == 0.0, 2 is True), so
# they are checked after unpacking
NO_FAIL_FAST = {"f32", "bool"}


@pytest.mark.parametrize("name", LITERAL_CASES)
def test_literal_matrix_compiled_matches_plain(name):
    hint, value, good, bad = LITERAL_CASES[name]

    @dataclasses.dataclass
    class Cls:
        id: hint  # type: ignore[valid-type]
        tail: U8_B = 0

    assert roundtrip(Cls(value, 9)) == good + b"\x09"
    for compile in (True, False):
        codec = get_codec(Cls, compile=compile)
        with pytest.raises(BytesOperationError, match="Literal"):
            decode(bad + b"\x09", codec=codec)
        assert decode(good + b"\x09", codec=codec) == Cls(value, 9)
    if name not in NO_FAIL_FAST:
        # the literal is checked before the rest of the buffer is touched
        with pytest.raises(BytesOperationError, match="Literal"):
            decode(bad, codec=get_codec(Cls))


@pytest.mark.parametrize(
    "name",
    [
        "u8",
        "u24",
        "u24_le",
        "i24",
        "u48",
        "int_enum_u8",
        "int_enum_u24",
        "int_enum_i48",
    ],
)
def test_factory_accepts_every_fixed_int_literal(name):
    hint, value, good, bad = LITERAL_CASES[name]
    factory = rb.Factory("id")

    @factory.register
    @dataclasses.dataclass
    class Cls:
        id: hint  # type: ignore[valid-type]
        tail: U8_B = 0

    assert factory.encode(Cls(value, 4)) == good + b"\x04"
    assert factory.decode(good + b"\x04") == Cls(value, 4)
    assert factory.decode(bad + b"\x04") is None


# - - - - - enums and validators over every fixed-size codec - - - - - #

ENUM_CASES = {
    "u8": (
        Color,
        StructCodec(">B"),
        {Color.RED: b"\x01", Color.GREEN: b"\x02"},
    ),
    "u24": (
        Color,
        U24_B.__metadata__[0],
        {Color.RED: b"\x00\x00\x01", Color.GREEN: b"\x00\x00\x02"},
    ),
    "i48_le": (
        Color,
        I48_L.__metadata__[0],
        {
            Color.RED: b"\x01\x00\x00\x00\x00\x00",
            Color.GREEN: b"\x02\x00\x00\x00\x00\x00",
        },
    ),
    "str": (
        StrEnum_,
        StringCodec(length=2),
        {StrEnum_.AB: b"ab", StrEnum_.CD: b"cd"},
    ),
    "bytes": (
        BytesEnum_,
        BytesCodec(length=2),
        {BytesEnum_.AB: b"ab", BytesEnum_.CD: b"cd"},
    ),
}


@pytest.mark.parametrize("name", ENUM_CASES)
def test_enum_matrix_compiled_matches_plain(name):
    enum_cls, inner, raws = ENUM_CASES[name]
    hint = t.Annotated[enum_cls, inner]

    @dataclasses.dataclass
    class Cls:
        a: hint  # type: ignore[valid-type]
        b: U8_B
        c: hint  # type: ignore[valid-type]

    first, second = list(raws)
    value = Cls(first, 7, second)
    data = roundtrip(value)
    assert data == raws[first] + b"\x07" + raws[second]
    assert type(decode(data, codec=get_codec(Cls)).a) is enum_cls
    bad = bytes(len(raws[first]))
    if name in ("str", "bytes"):
        bad = b"zz"
    for compile in (True, False):
        codec = get_codec(Cls, compile=compile)
        with pytest.raises(BytesOperationError):
            decode(bad + b"\x07" + raws[second], codec=codec)
        with pytest.raises(BytesOperationError):
            decode(raws[first] + b"\x07" + bad, codec=codec)


def test_validator_over_wide_ints_compiled_matches_plain():
    @dataclasses.dataclass
    class Cls:
        a: t.Annotated[int, U24_B, rb.Gt(5)]
        b: t.Annotated[int, I48_L, rb.Lt(100)]

    roundtrip(Cls(6, -3))
    for compile in (True, False):
        codec = get_codec(Cls, compile=compile)
        with pytest.raises(BytesOperationError):
            decode(b"\x00\x00\x01" + bytes(6), codec=codec)
        with pytest.raises(BytesOperationError):
            encode(Cls(6, 100), codec=codec)
