import dataclasses
import enum
import typing as t

import pytest

import rombob as rb
from rombob import (
    BE,
    LE,
    U8_B,
    U16_B,
    U16_L,
    U24_B,
    U24_L,
    U32_B,
    BytesOperationError,
    ClassCodec,
    Factory,
    IntCodec,
    Len,
    Named,
    OptionalCodec,
    Reader,
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


@dataclasses.dataclass
class Foo:
    byte: U8_B
    short: U16_B
    long: U32_B
    fixed_string: t.Annotated[str, Len(10)]
    fixed_list: t.Annotated[list[U8_B], Len(5)]


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


# - - - - - factory with wide ids - - - - - #


def test_factory_two_byte_id_at_offset():
    factory = Factory("id")

    @factory.register
    @dataclasses.dataclass
    class A:
        version: U8_B
        id: t.Annotated[t.Literal[0x0102], StructCodec(">H")]
        x: U8_B

    @factory.register
    @dataclasses.dataclass
    class B:
        version: U8_B
        id: t.Annotated[t.Literal[0x0201, 0x0202], StructCodec(">H")]

    assert factory.decode(b"\x09\x01\x02\x05") == A(9, 0x0102, 5)
    assert factory.decode(b"\x09\x02\x02") == B(9, 0x0202)
    assert factory.decode(b"\x09\x03\x03") is None
    assert factory.encode(B(1, 0x0201)) == b"\x01\x02\x01"
    with pytest.raises(BytesOperationError):
        factory.decode(b"\x09\x01")


def test_factory_rejects_mismatching_layout():
    factory = Factory("id")

    @factory.register
    @dataclasses.dataclass
    class A:
        id: t.Annotated[t.Literal[1], StructCodec(">H")]

    @dataclasses.dataclass
    class WrongSize:
        id: t.Annotated[t.Literal[2], StructCodec(">B")]

    @dataclasses.dataclass
    class WrongOffset:
        pad: U8_B
        id: t.Annotated[t.Literal[3], StructCodec(">H")]

    @dataclasses.dataclass
    class NotStatic:
        n: UVInt
        id: t.Annotated[t.Literal[4], StructCodec(">H")]

    for cls in (WrongSize, WrongOffset, NotStatic):
        with pytest.raises(BytesOperationError):
            factory.register(cls)


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


# - - - - - Reader / Writer - - - - - #


def test_reader_basics():
    r = Reader(b"\x01\x02\x03\x04\x05")
    assert r.remaining == 5
    assert bytes(r.peek(2)) == b"\x01\x02"
    assert bytes(r.peek(2, 1)) == b"\x02\x03"
    assert r.offset == 0
    assert bytes(r.take(2)) == b"\x01\x02"
    assert r.unpack(rb.StructCodec(">H")) == (0x0304,)
    assert r.rest() == b"\x05"
    assert r.remaining == 0
    with pytest.raises(BytesOperationError):
        r.take(1)
    with pytest.raises(BytesOperationError):
        r.peek(1)


@pytest.mark.parametrize("data", [b"\x01\x02", bytearray(b"\x01\x02")])
def test_reader_accepts_buffers(data):
    assert bytes(Reader(data).take(2)) == b"\x01\x02"
    assert bytes(Reader(memoryview(data)).take(2)) == b"\x01\x02"


def test_to_reader_and_to_writer_share_data():
    w = Writer()
    w.data["k"] = 1
    r = w.to_reader()
    assert r.data is w.data
    assert r.to_writer().data is w.data


def test_writer_basics():
    w = Writer()
    w.write(b"ab")
    w.pack(rb.StructCodec(">H"), 1)
    assert w.getvalue() == b"ab\x00\x01"
    assert isinstance(w.getvalue(), bytes)
    assert w.to_reader().rest() == b"ab\x00\x01"


def test_underflow_is_an_error():
    with pytest.raises(BytesOperationError):
        decode(b"\x01", cls=Foo)
    with pytest.raises(BytesOperationError):
        decode(b"\x01", codec=rb.StringCodec())
    with pytest.raises(BytesOperationError):
        decode(b"\x00\x05ab", codec=rb.StringCodec())


def test_truncated_varint():
    with pytest.raises(BytesOperationError, match="Truncated"):
        decode(b"\x80\x80", codec=get_codec(UVInt))
    with pytest.raises(BytesOperationError):
        decode(b"", codec=get_codec(UVInt))
    assert decode(b"\x7f", codec=get_codec(UVInt)) == 127


def test_encode_rolls_back_user_writer():
    @dataclasses.dataclass
    class Cls:
        a: U8_B
        b: t.Annotated[str, Len(2)]

    w = Writer(bytearray(b"prefix"))
    with pytest.raises(BytesOperationError):
        encode(Cls(1, "wrong"), writer=w)
    assert bytes(w.buffer) == b"prefix"

    assert encode(Cls(1, "ok"), writer=w) == b"prefix\x01ok"


def test_error_mentions_offset():
    data = b"\x01\x00\x02" + b"\x00" * 3  # truncated for Foo
    with pytest.raises(BytesOperationError, match="offset"):
        decode(data, cls=Foo)

    r = Reader(b"abc\x80")
    r.offset = 3
    with pytest.raises(BytesOperationError, match="offset 3"):
        decode(b"", codec=get_codec(UVInt), reader=r)


def test_decode_advances_given_reader():
    r = Reader(b"\x01\x02\x03")
    assert decode(b"", codec=get_codec(U8_B), reader=r) == 1
    assert decode(b"", codec=get_codec(U16_B), reader=r) == 0x0203
    assert r.remaining == 0


def test_decoded_values_do_not_reference_input():
    buf = bytearray(b"\x00\x02ab")
    value = decode(buf, codec=rb.BytesCodec())
    buf[2] = 0
    assert value == b"ab"
    buf.append(0)  # no exports left: resizing works
    assert isinstance(value, bytes)
