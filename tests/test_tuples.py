"""`tuple[X, ...]` (variable length) and `tuple[X, Y]` (a fixed record)."""

import dataclasses
import typing as t

import pytest

from rombob import (
    U8_B,
    U16_B,
    BytesOperationError,
    ClassCodec,
    CollectionCodec,
    Len,
    Prefix,
    Range,
    StructCodec,
    Writer,
    get_codec,
)

# - - - - - tuple[X, ...] - - - - - #


@pytest.mark.parametrize(
    "hint, value, data",
    (
        (tuple[str, ...], (), b"\x00\x00"),
        (tuple[str, ...], ("a", "b"), b"\x00\x02\x00\x01a\x00\x01b"),
        (tuple[U8_B, ...], (1, 2, 3), b"\x00\x03\x01\x02\x03"),
        (t.Tuple[U8_B, ...], (1,), b"\x00\x01\x01"),  # noqa: UP006
        (t.Annotated[tuple[U8_B, ...], Len(2)], (1, 2), b"\x01\x02"),
        (t.Annotated[tuple[U8_B, ...], Prefix(U8_B)], (1, 2), b"\x02\x01\x02"),
        (
            tuple[tuple[U8_B, ...], ...],
            ((1,), ()),
            b"\x00\x02\x00\x01\x01\x00\x00",
        ),
        (tuple[U16_B, ...] | None, (1, 2), b"\x00\x02\x00\x01\x00\x02"),
    ),
)
def test_variable_tuple(rt, hint, value, data):
    assert rt(value, hint) == data


def test_variable_tuple_is_a_collection():
    codec = get_codec(tuple[U8_B, ...])
    assert codec == CollectionCodec(cls=tuple, item_codec=StructCodec(">B"))


def test_variable_tuple_is_decoded_as_a_tuple(compile):
    codec = get_codec(tuple[U8_B, ...], compile=compile)
    assert type(codec.decode(b"\x00\x01\x05")) is tuple


# - - - - - tuple[X, Y] - - - - - #


@pytest.mark.parametrize(
    "hint, value, data",
    (
        (tuple[U8_B, str], (1, "x"), b"\x01\x00\x01x"),
        (tuple[U8_B, U16_B], (1, 2), b"\x01\x00\x02"),
        (t.Tuple[U8_B, U16_B], (1, 2), b"\x01\x00\x02"),  # noqa: UP006
        (tuple[int, str], (1, "x"), b"\x00" * 7 + b"\x01\x00\x01x"),
        (tuple[U8_B], (5,), b"\x05"),  # a tuple of one, not a variable one
        (tuple[U8_B, U8_B, U8_B], (1, 2, 3), b"\x01\x02\x03"),
        (tuple[tuple[U8_B, U8_B], str], ((1, 2), "z"), b"\x01\x02\x00\x01z"),
        (tuple[U8_B, tuple[U8_B, ...]], (1, (2, 3)), b"\x01\x00\x02\x02\x03"),
        (tuple[U8_B, str] | None, (1, "x"), b"\x01\x00\x01x"),
        (tuple[t.Annotated[bytes, Len(2)], U8_B], (b"ab", 1), b"ab\x01"),
        (tuple[t.Annotated[U8_B, Range(1, 3)], str], (2, ""), b"\x02\x00\x00"),
    ),
)
def test_heterogeneous_tuple(rt, hint, value, data):
    assert rt(value, hint) == data


def test_heterogeneous_tuple_is_a_record():
    codec = get_codec(tuple[U8_B, str])
    assert isinstance(codec, ClassCodec)
    assert [name for name, _ in codec.fields] == ["_0", "_1"]
    assert get_codec(tuple[U8_B, str]) is codec  # memoized


def test_heterogeneous_tuple_is_decoded_as_a_tuple(compile):
    codec = get_codec(tuple[U8_B, str], compile=compile)
    assert type(codec.decode(b"\x01\x00\x00")) is tuple
    codec = get_codec(tuple[U8_B], compile=compile)
    assert codec.decode(b"\x01") == (1,)


def test_heterogeneous_tuple_accepts_lists_when_writing(compile):
    codec = get_codec(tuple[U8_B, U8_B], compile=compile)
    assert codec.encode([1, 2]) == b"\x01\x02"


@dataclasses.dataclass
class WithTuples:
    point: tuple[U8_B, U16_B]
    label: tuple[U8_B, str]
    pair: t.Annotated[tuple[U8_B, ...], Len(2)]
    last: U8_B


def test_tuples_in_a_class(rt):
    value = WithTuples((1, 2), (3, "z"), (4, 5), 6)
    assert rt(value) == b"\x01\x00\x02\x03\x00\x01z\x04\x05\x06"


def test_fixed_tuples_are_fused_into_the_struct_of_the_class():
    text = repr(get_codec(WithTuples))
    assert "StructSegment(format='>BH')" in text
    assert "StructSegment(format='>2BB')" in text


def test_fixed_tuples_are_fused_but_nested_ones_too(rt):
    @dataclasses.dataclass
    class Nested:
        a: tuple[tuple[U8_B, U8_B], U16_B]
        b: U8_B

    assert "StructSegment(format='>BBHB')" in repr(get_codec(Nested))
    assert rt(Nested(((1, 2), 3), 4)) == b"\x01\x02\x00\x03\x04"


@pytest.mark.parametrize("bad", ((1,), (1, 2, 3), (), None, 5))
def test_wrong_tuple_size_when_writing(compile, bad):
    codec = get_codec(tuple[U8_B, U8_B], compile=compile)
    with pytest.raises(BytesOperationError):
        codec.encode(bad)
    codec = get_codec(tuple[U8_B, str], compile=compile)
    with pytest.raises(BytesOperationError):
        codec.encode(bad)


@pytest.mark.parametrize("bad", ((1,), (1, 2, 3)))
def test_wrong_tuple_size_in_a_fused_field(compile, bad):
    @dataclasses.dataclass
    class Cls:
        point: tuple[U8_B, U8_B]

    codec = get_codec(Cls, compile=compile)
    with pytest.raises(BytesOperationError, match="tuple size"):
        codec.encode(Cls(bad))


def test_wrong_tuple_size_leaves_the_writer_intact(compile):
    codec = get_codec(tuple[U8_B, str], compile=compile)
    w = Writer(bytearray(b"keep"))
    with pytest.raises(BytesOperationError):
        codec.encode_to((1, "a", "b"), w)
    assert bytes(w.buffer) == b"keep"


def test_truncated_tuple(compile):
    codec = get_codec(tuple[U8_B, str], compile=compile)
    for data in (b"", b"\x01", b"\x01\x00\x02a"):
        with pytest.raises(BytesOperationError):
            codec.decode(data)


# - - - - - unsupported shapes - - - - - #


@pytest.mark.parametrize(
    "hint",
    (
        tuple[int, ..., str],
        tuple[..., int],
        tuple[()],
        tuple,
        list,
        t.Annotated[tuple[U8_B, str], Len(2)],
        t.Annotated[tuple[U8_B, str], Prefix(U8_B)],
    ),
)
def test_unsupported_tuples(hint):
    with pytest.raises(BytesOperationError):
        get_codec(hint)
