"""Annotations: Len, Prefix, Len(ref), constraints, When, Skip, Literal."""

import dataclasses
import enum
import typing as t

import pytest

from rombob import (
    I8_B,
    U8_B,
    U16_B,
    U16_L,
    U32_L,
    BytesCodec,
    BytesOperationError,
    CollectionCodec,
    Ge,
    Gt,
    IVInt,
    Le,
    Len,
    LiteralCodec,
    Lt,
    Named,
    OptionalCodec,
    Predicate,
    Prefix,
    Range,
    Reader,
    RefLenCodec,
    Skip,
    StringCodec,
    StructCodec,
    UVInt,
    When,
    Writer,
    decode,
    encode,
    get_codec,
)

# - - - - - the annotations themselves - - - - - #


@pytest.mark.parametrize(
    "factory",
    (
        lambda: Len(),
        lambda: Len(1, "ref"),
        lambda: Len(-1),
        lambda: Len(1.5),
        lambda: Len(True),
        lambda: When(),
        lambda: When(lambda ctx: True, "ref"),
    ),
)
def test_invalid_annotations(factory):
    with pytest.raises(ValueError):
        factory()


def test_annotations_are_values():
    assert Len(3) == Len(3) and Len(3) != Len(4)
    assert Len(ref="a") == Len(ref="a")
    assert Gt(1) == Gt(1) and Gt(1) != Ge(1)
    assert Range(1, 2) == Range(1, 2)
    assert Prefix(U8_B) == Prefix(U8_B)
    assert When(ref="a") == When(ref="a")
    assert len({Gt(1), Gt(1), Lt(1)}) == 2
    assert "Range" in repr(Range(1, 2))


def test_hints_with_annotations_are_memoized():
    hint = t.Annotated[U8_B, Range(1, 5), Predicate(bool)]
    assert get_codec(hint) is get_codec(hint)
    hint = t.Annotated[bytes, Len(ref="n")]
    assert get_codec(hint) is get_codec(hint)


# - - - - - Len - - - - - #


@pytest.mark.parametrize(
    "hint, value, data",
    (
        (t.Annotated[str, Len(3)], "abc", b"abc"),
        (t.Annotated[str, Len(2)], "é", b"\xc3\xa9"),  # bytes, not chars
        (t.Annotated[bytes, Len(3)], b"\x00\x01\x02", b"\x00\x01\x02"),
        (t.Annotated[list[U8_B], Len(2)], [1, 2], b"\x01\x02"),
        (t.Annotated[tuple[U8_B, ...], Len(2)], (1, 2), b"\x01\x02"),
        (t.Annotated[set[U8_B], Len(2)], {1, 2}, b"\x01\x02"),
        (t.Annotated[frozenset[U8_B], Len(2)], frozenset({1, 2}), b"\x01\x02"),
        (t.Annotated[list[str], Len(2)], ["a", "b"], b"\x00\x01a\x00\x01b"),
        (t.Annotated[str, Len(0)], "", b""),
        (t.Annotated[bytes, Len(0)], b"", b""),
        (t.Annotated[list[U8_B], Len(0)], [], b""),
    ),
)
def test_fixed_length(rt, hint, value, data):
    assert rt(value, hint) == data


@pytest.mark.parametrize(
    "hint, value",
    (
        (t.Annotated[str, Len(3)], "ab"),
        (t.Annotated[str, Len(2)], "éé"),
        (t.Annotated[bytes, Len(3)], b"abcd"),
        (t.Annotated[bytes, Len(0)], b"x"),
        (t.Annotated[list[U8_B], Len(2)], [1]),
        (t.Annotated[tuple[U8_B, ...], Len(2)], (1, 2, 3)),
    ),
)
def test_fixed_length_mismatch(compile, hint, value):
    codec = get_codec(hint, compile=compile)
    with pytest.raises(BytesOperationError):
        codec.encode(value)


def test_fixed_length_is_not_stored(compile):
    codec = get_codec(t.Annotated[bytes, Len(3)], compile=compile)
    r = Reader(b"abcdef")
    assert codec.decode_from(r) == b"abc"
    assert r.remaining == 3
    with pytest.raises(BytesOperationError):
        codec.decode(b"ab")


@pytest.mark.parametrize(
    "hint, expected",
    (
        (t.Annotated[bytes, Len(4)], BytesCodec(length=4)),
        (t.Annotated[str, Len(4)], StringCodec(length=4)),
        (
            t.Annotated[list[U8_B], Len(4)],
            CollectionCodec(cls=list, item_codec=StructCodec(">B"), length=4),
        ),
        (
            t.Annotated[bytes, Prefix(U8_B)],
            BytesCodec(len_codec=StructCodec(">B")),
        ),
        (
            t.Annotated[bytes, Len(ref="n")],
            BytesCodec(len_codec=RefLenCodec(ref="n")),
        ),
    ),
)
def test_len_codecs(hint, expected):
    assert get_codec(hint) == expected


class Color(enum.IntEnum):
    red = 1


@dataclasses.dataclass
class Plain:
    a: U8_B


@pytest.mark.parametrize(
    "hint",
    (
        t.Annotated[int, Len(2)],
        t.Annotated[float, Len(2)],
        t.Annotated[Color, Len(2)],
        t.Annotated[Plain, Len(2)],
        t.Annotated[t.Literal[1, 2], Len(2)],
        t.Annotated[int, Prefix(U8_B)],
        t.Annotated[bytes, Len(2), Len(3)],
        t.Annotated[bytes, Prefix(U8_B), Prefix(U16_B)],
        t.Annotated[bytes, Len(2), Prefix(U8_B)],
        t.Annotated[bytes, Len(2), StructCodec(">H")],
        t.Annotated[list[U8_B], Len(2), StructCodec(">H")],
    ),
)
def test_misused_len_is_an_error(hint):
    with pytest.raises(BytesOperationError):
        get_codec(hint)


# - - - - - Prefix - - - - - #


@pytest.mark.parametrize(
    "hint, value, data",
    (
        (t.Annotated[str, Prefix(U8_B)], "hi", b"\x02hi"),
        (t.Annotated[bytes, Prefix(U32_L)], b"ab", b"\x02\x00\x00\x00ab"),
        (t.Annotated[list[U8_B], Prefix(U16_L)], [7], b"\x01\x00\x07"),
        (
            t.Annotated[bytes, Prefix(UVInt)],
            b"x" * 200,
            b"\xc8\x01" + b"x" * 200,
        ),
        (t.Annotated[str, Prefix(StructCodec(">B"))], "a", b"\x01a"),
        (t.Annotated[str, Prefix(U8_B)], "", b"\x00"),
    ),
)
def test_prefix(rt, hint, value, data):
    assert rt(value, hint) == data


def test_prefix_overflow(compile):
    codec = get_codec(t.Annotated[bytes, Prefix(U8_B)], compile=compile)
    assert len(codec.encode(b"x" * 255)) == 256
    with pytest.raises(BytesOperationError):
        codec.encode(b"x" * 256)


@dataclasses.dataclass
class Prefixed:
    a: U8_B
    s: t.Annotated[str, Prefix(U8_B)]
    items: t.Annotated[list[I8_B], Prefix(IVInt)]
    b: U16_B


def test_prefix_in_class(rt):
    value = Prefixed(1, "ab", [-1, 2], 3)
    assert rt(value) == b"\x01\x02ab\x04\xff\x02\x00\x03"


# - - - - - Len(ref=...) - - - - - #


@dataclasses.dataclass
class Counted:
    count: Named[U8_B]
    items: t.Annotated[list[U8_B], Len(ref="count")]
    size: Named[U16_B]
    data: t.Annotated[bytes, Len(ref=lambda ctx: ctx.data["size"] - 1)]
    text: t.Annotated[str, Len(ref="count")]


def test_len_ref(rt):
    value = Counted(2, [7, 8], 4, b"abc", "hi")
    assert rt(value) == b"\x02\x07\x08\x00\x04abchi"


def test_len_ref_empty(rt):
    assert rt(Counted(0, [], 1, b"", "")) == b"\x00\x00\x01"


@pytest.mark.parametrize(
    "value",
    (
        Counted(3, [7, 8], 4, b"abc", "hi"),  # list is shorter than count
        Counted(1, [7, 8], 4, b"abc", "h"),
        Counted(2, [7, 8], 4, b"ab", "hi"),  # callable says 3
        Counted(2, [7, 8], 4, b"abc", "hii"),
    ),
)
def test_len_ref_must_match_when_writing(compile, value):
    codec = get_codec(Counted, compile=compile)
    with pytest.raises(BytesOperationError, match="Len"):
        codec.encode(value)


def test_len_ref_truncated(compile):
    codec = get_codec(Counted, compile=compile)
    with pytest.raises(BytesOperationError):
        codec.decode(b"\x02\x07\x08\x00\x04ab")


@dataclasses.dataclass
class NoSuchName:
    a: U8_B
    data: t.Annotated[bytes, Len(ref="nope")]


@dataclasses.dataclass
class BadLength:
    n: Named[I8_B]
    data: t.Annotated[bytes, Len(ref="n")]


@dataclasses.dataclass
class StrLength:
    n: Named[str]
    data: t.Annotated[bytes, Len(ref="n")]


def test_len_ref_needs_an_earlier_named_field(compile):
    codec = get_codec(NoSuchName, compile=compile)
    with pytest.raises(BytesOperationError, match="Named"):
        codec.encode(NoSuchName(1, b""))
    with pytest.raises(BytesOperationError, match="Named"):
        codec.decode(b"\x01")


def test_len_ref_must_be_a_valid_length(compile):
    codec = get_codec(BadLength, compile=compile)
    with pytest.raises(BytesOperationError, match="valid length"):
        codec.decode(b"\xffab")
    with pytest.raises(BytesOperationError, match="valid length"):
        codec.encode(BadLength(-1, b""))
    codec = get_codec(StrLength, compile=compile)
    with pytest.raises(BytesOperationError, match="valid length"):
        codec.decode(b"\x00\x01aab")


def test_len_ref_callable_gets_the_reader_and_the_writer(compile):
    seen = []

    def length(ctx):
        seen.append(type(ctx).__name__)
        return 2

    @dataclasses.dataclass
    class Cls:
        data: t.Annotated[bytes, Len(ref=length)]

    codec = get_codec(Cls, compile=compile)
    assert codec.decode(codec.encode(Cls(b"ab"))) == Cls(b"ab")
    assert seen == ["Writer", "Reader"]


# - - - - - Literal - - - - - #


Magic = t.Literal[b"1234"]


@dataclasses.dataclass
class Header:
    magic: Magic
    n: U8_B


@pytest.mark.parametrize(
    "hint, expected",
    (
        (Magic, LiteralCodec(codec=BytesCodec(length=4), literals=(b"1234",))),
        (
            t.Literal["ab", "cd"],
            LiteralCodec(codec=StringCodec(length=2), literals=("ab", "cd")),
        ),
        (
            t.Literal["é"],
            LiteralCodec(codec=StringCodec(length=2), literals=("é",)),
        ),
        (
            t.Literal[b""],
            LiteralCodec(codec=BytesCodec(length=0), literals=(b"",)),
        ),
        (
            t.Annotated[t.Literal[b"ab"], Len(2)],
            LiteralCodec(codec=BytesCodec(length=2), literals=(b"ab",)),
        ),
        # different sizes: nothing to infer, so the usual prefixed bytes
        (
            t.Literal[b"a", b"bcd"],
            LiteralCodec(codec=BytesCodec(), literals=(b"a", b"bcd")),
        ),
        (
            t.Annotated[t.Literal[b"a"], Prefix(U8_B)],
            LiteralCodec(
                codec=BytesCodec(len_codec=StructCodec(">B")), literals=(b"a",)
            ),
        ),
        # integers still take their codec from the annotation
        (
            t.Annotated[t.Literal[1, 2], U8_B],
            LiteralCodec(codec=StructCodec(">B"), literals=(1, 2)),
        ),
        (
            t.Literal[1, 2],
            LiteralCodec(codec=StructCodec(">q"), literals=(1, 2)),
        ),
    ),
)
def test_literal_codec(hint, expected):
    assert get_codec(hint) == expected


@pytest.mark.parametrize(
    "hint, value, data",
    (
        (Magic, b"1234", b"1234"),
        (t.Literal["ab", "cd"], "cd", b"cd"),
        (t.Literal[b"a", b"bcd"], b"bcd", b"\x00\x03bcd"),
        (t.Annotated[t.Literal[b"a"], Prefix(U8_B)], b"a", b"\x01a"),
        (t.Annotated[t.Literal[1, 2], U8_B], 2, b"\x02"),
    ),
)
def test_literal_roundtrip(rt, hint, value, data):
    assert rt(value, hint) == data


def test_literal_in_class(rt):
    assert rt(Header(b"1234", 7)) == b"1234\x07"


def test_literal_in_class_is_a_fixed_struct():
    assert "'>4sB'" in repr(get_codec(Header))


@pytest.mark.parametrize("magic", (b"1235", b"0000", b"\x00\x00\x00\x00"))
def test_literal_rejects_other_values_when_reading(compile, magic):
    codec = get_codec(Header, compile=compile)
    with pytest.raises(BytesOperationError):
        codec.decode(magic + b"\x07")


@pytest.mark.parametrize("value", (b"1235", b"123", b"12345", b""))
def test_literal_rejects_other_values_when_writing(compile, value):
    codec = get_codec(Header, compile=compile)
    with pytest.raises(BytesOperationError):
        codec.encode(Header(value, 7))


def test_literal_truncated(compile):
    codec = get_codec(Header, compile=compile)
    with pytest.raises(BytesOperationError):
        codec.decode(b"123")
    with pytest.raises(BytesOperationError):
        codec.decode(b"1234")


@pytest.mark.parametrize(
    "hint",
    (
        t.Annotated[t.Literal[b"xy"], Len(3)],
        t.Annotated[t.Literal["ab", "c"], Len(2)],
        t.Annotated[t.Literal[1], Len(1)],
        t.Annotated[t.Literal[b"ab"], Len(2), StructCodec(">H")],
    ),
)
def test_literal_len_mismatch(hint):
    with pytest.raises(BytesOperationError):
        get_codec(hint)


# - - - - - constraints - - - - - #


@pytest.mark.parametrize(
    "constraint, good, bad",
    (
        (Gt(5), (6, 255), (5, 4, 0)),
        (Ge(5), (5, 6), (4, 0)),
        (Lt(5), (4, 0), (5, 6, 255)),
        (Le(5), (5, 0), (6, 255)),
        (Range(1, 3), (1, 2, 3), (0, 4)),
        (Predicate(lambda v: v % 2 == 0), (0, 2, 254), (1, 255)),
        (Predicate(lambda v: v % 2), (1, 3), (0, 2)),  # truthy is enough
    ),
)
@pytest.mark.parametrize("base", (U8_B, UVInt), ids=["struct", "dynamic"])
def test_constraints(compile, base, constraint, good, bad):
    @dataclasses.dataclass
    class Cls:
        a: t.Annotated[base, constraint]
        b: U8_B = 0

    codec = get_codec(Cls, compile=compile)
    for v in good:
        data = codec.encode(Cls(v))
        assert codec.decode(data) == Cls(v)
    for v in bad:
        with pytest.raises(BytesOperationError, match="violates"):
            codec.encode(Cls(v))
        # the same check when reading
        raw = get_codec(base).encode(v)
        with pytest.raises(BytesOperationError, match="violates"):
            codec.decode(raw + b"\x00")


def test_constraints_on_floats(compile):
    @dataclasses.dataclass
    class Cls:
        x: t.Annotated[t.Annotated[float, StructCodec(">d")], Gt(0.5), Le(1.5)]

    codec = get_codec(Cls, compile=compile)
    assert codec.decode(codec.encode(Cls(1.5))) == Cls(1.5)
    for bad in (0.5, 1.6, float("nan"), float("inf"), -float("inf")):
        with pytest.raises(BytesOperationError, match="violates"):
            codec.encode(Cls(bad))


def test_several_constraints_are_all_checked(compile):
    odd = Predicate(lambda v: v % 2 == 1)
    codec = get_codec(t.Annotated[U8_B, Ge(1), Le(7), odd], compile=compile)
    assert codec.decode(codec.encode(5)) == 5
    for bad in (0, 2, 9):
        with pytest.raises(BytesOperationError):
            codec.encode(bad)


def test_constraints_apply_to_the_whole_value(compile):
    short = Predicate(lambda v: len(v) < 3)
    for hint, good, bad in (
        (t.Annotated[str, short], "ab", "abc"),
        (t.Annotated[list[U8_B], short], [1, 2], [1, 2, 3]),
    ):
        codec = get_codec(hint, compile=compile)
        assert codec.decode(codec.encode(good)) == good
        with pytest.raises(BytesOperationError):
            codec.encode(bad)


def test_constraint_applies_to_the_present_value_of_an_optional(compile):
    codec = get_codec(t.Annotated[U8_B | None, Range(1, 3)], compile=compile)
    assert codec.decode(codec.encode(None)) is None  # absence is not checked
    assert codec.decode(codec.encode(2)) == 2
    for bad in (0, 4):
        with pytest.raises(BytesOperationError):
            codec.encode(bad)


def test_constraint_inside_an_optional_hint(compile):
    for hint in (
        t.Optional[t.Annotated[U8_B, Range(1, 3)]],  # noqa: UP045
        t.Annotated[U8_B, Range(1, 3)] | None,
    ):
        codec = get_codec(hint, compile=compile)
        assert codec.decode(codec.encode(3)) == 3
        with pytest.raises(BytesOperationError):
            codec.encode(4)


# - - - - - optional hints - - - - - #


@pytest.mark.parametrize(
    "hint",
    (
        Named[U8_B | None],
        Named[U8_B] | None,
        t.Optional[Named[U8_B]],  # noqa: UP045
        t.Annotated[U8_B | None, Range(0, 9)],
        t.Annotated[U8_B, Range(0, 9)] | None,
        t.Annotated[bytes | None, Len(2)],
        Named[t.Annotated[U8_B, Range(0, 9)] | None],
    ),
)
def test_optional_shapes(rt, hint):
    value = b"ab" if "bytes" in repr(hint) else 5
    assert rt(value, hint)
    assert rt(None, hint) == b""


def test_named_optional_remembers_none():
    @dataclasses.dataclass
    class Cls:
        a: Named[U8_B | None]

    r = Reader(b"")
    assert decode(b"", cls=Cls, reader=r) == Cls(None)
    assert r.data == {"a": None}
    w = Writer()
    encode(Cls(None), writer=w)
    assert w.data == {"a": None}


def test_optional_inner_length_is_fixed():
    codec = get_codec(t.Annotated[bytes | None, Len(2)])
    assert isinstance(codec, OptionalCodec)
    assert codec.codec == BytesCodec(length=2)


@pytest.mark.parametrize("hint", (int | str, t.Union[int, str, bytes]))  # noqa: UP007
def test_union_without_none_is_unsupported(hint):
    with pytest.raises(BytesOperationError, match="union"):
        get_codec(hint)


# - - - - - When - - - - - #


@dataclasses.dataclass
class Packet:
    flag: Named[U8_B]
    token: t.Annotated[U16_B | None, When(ref="flag")] = None
    extra: t.Annotated[U8_B | None, When(lambda ctx: ctx.data["flag"] == 2)] = (
        None
    )


@pytest.mark.parametrize(
    "value, data",
    (
        (Packet(0), b"\x00"),
        (Packet(1, 5), b"\x01\x00\x05"),
        (Packet(3, 5), b"\x03\x00\x05"),
        (Packet(2, 5, 9), b"\x02\x00\x05\x09"),
    ),
)
def test_when(rt, value, data):
    assert rt(value) == data


@pytest.mark.parametrize(
    "value",
    (
        Packet(0, 5),  # given, but flag is 0
        Packet(1, None),  # missing, but flag is 1
        Packet(1, 5, 9),  # extra only with flag == 2
        Packet(2, 5, None),  # extra is missing
    ),
)
def test_when_disagreement_is_an_error(compile, value):
    codec = get_codec(Packet, compile=compile)
    w = Writer(bytearray(b"keep"))
    with pytest.raises(BytesOperationError, match="When"):
        encode(value, codec=codec, writer=w)
    assert bytes(w.buffer) == b"keep"


def test_when_truncated(compile):
    codec = get_codec(Packet, compile=compile)
    with pytest.raises(BytesOperationError):
        codec.decode(b"\x01\x00")  # the token is cut short
    assert codec.decode(b"\x00") == Packet(0)


@dataclasses.dataclass
class DynamicWhen:
    flag: Named[U8_B]
    text: t.Annotated[str | None, When(ref="flag")] = None
    fixed: t.Annotated[bytes | None, Len(2), When(ref="flag")] = None


def test_when_with_dynamic_and_fixed_inner_types(rt, compile):
    assert rt(DynamicWhen(0)) == b"\x00"
    assert rt(DynamicWhen(1, "ab", b"xy")) == b"\x01\x00\x02abxy"
    codec = get_codec(DynamicWhen, compile=compile)
    for bad in (DynamicWhen(1, "ab", None), DynamicWhen(0, "a", None)):
        with pytest.raises(BytesOperationError, match="When"):
            codec.encode(bad)


def test_when_predicate_gets_the_reader_and_the_writer(compile):
    seen = []

    def present(ctx):
        seen.append((type(ctx).__name__, ctx.data["a"]))
        return True

    @dataclasses.dataclass
    class Cls:
        a: Named[U8_B]
        b: t.Annotated[U8_B | None, When(present)]

    codec = get_codec(Cls, compile=compile)
    assert codec.decode(codec.encode(Cls(7, 1))) == Cls(7, 1)
    assert seen == [("Writer", 7), ("Reader", 7)]


def test_when_predicate_sees_the_current_offset(compile):
    offsets = []

    def present(ctx):
        offsets.append(ctx.offset)
        return True

    @dataclasses.dataclass
    class Cls:
        a: U8_B
        b: U16_B
        c: t.Annotated[U8_B | None, When(present)]

    codec = get_codec(Cls, compile=compile)
    codec.decode(b"\x01\x00\x02\x03")
    assert offsets == [3]


@dataclasses.dataclass
class NoNamed:
    token: t.Annotated[U8_B | None, When(ref="nope")]


def test_when_ref_needs_an_earlier_named_field(compile):
    codec = get_codec(NoNamed, compile=compile)
    with pytest.raises(BytesOperationError, match="Named"):
        codec.encode(NoNamed(None))
    with pytest.raises(BytesOperationError, match="Named"):
        codec.decode(b"")


def test_when_needs_an_optional_type():
    with pytest.raises(BytesOperationError, match="optional"):
        get_codec(t.Annotated[U8_B, When(ref="a")])


# - - - - - Skip - - - - - #


@dataclasses.dataclass
class Skipping:
    a: U8_B
    cache: Skip[dict] = dataclasses.field(default_factory=dict)
    const: Skip[int] = 42
    b: U8_B = 0
    VERSION: t.ClassVar[int] = 3


def test_skipped_fields_are_not_encoded(compile):
    codec = get_codec(Skipping, compile=compile)
    assert codec.encode(Skipping(1, {"x": 1}, 7, 2)) == b"\x01\x02"
    assert [name for name, _ in codec.fields] == ["a", "b"]


def test_skipped_fields_take_their_defaults(compile):
    codec = get_codec(Skipping, compile=compile)
    first, second = codec.decode(b"\x05\x06"), codec.decode(b"\x05\x06")
    assert first == Skipping(5, {}, 42, 6)
    assert first.cache is not second.cache  # default_factory is respected


def test_skipped_fields_do_not_need_to_be_in_the_data(rt):
    assert rt(Skipping(1, {}, 42, 2)) == b"\x01\x02"


@dataclasses.dataclass
class InitFalse:
    a: U8_B
    derived: Skip[int] = dataclasses.field(init=False, default=0)
    b: U8_B = 0


@dataclasses.dataclass(frozen=True, kw_only=True)
class KwOnlySkip:
    skipped: Skip[int] = 1
    a: U8_B


class NamedTupleSkip(t.NamedTuple):
    a: U8_B
    cache: Skip[int] = 9
    b: U8_B = 0


@pytest.mark.parametrize(
    "value, data",
    (
        (InitFalse(1, b=2), b"\x01\x02"),
        (KwOnlySkip(a=3), b"\x03"),
        (NamedTupleSkip(1, 9, 2), b"\x01\x02"),
    ),
)
def test_skip_in_other_kinds_of_classes(rt, value, data):
    assert rt(value) == data


def test_skip_in_a_namedtuple_takes_the_default(compile):
    codec = get_codec(NamedTupleSkip, compile=compile)
    assert codec.decode(b"\x05\x06") == NamedTupleSkip(5, 9, 6)


def test_skip_keeps_other_annotations_out_of_the_way(rt):
    @dataclasses.dataclass
    class Cls:
        a: t.Annotated[U8_B, Range(0, 9)]
        skipped: t.Annotated[int, Range(5, 6), Skip.__metadata__[0]] = 100

    assert rt(Cls(1)) == b"\x01"


@dataclasses.dataclass
class NoDefault:
    a: Skip[int]
    b: U8_B


class NamedTupleNoDefault(t.NamedTuple):
    a: Skip[int]
    b: U8_B


@dataclasses.dataclass
class OptionalSkip:
    a: Skip[int] | None = None


@pytest.mark.parametrize("cls", (NoDefault, NamedTupleNoDefault))
def test_skip_needs_a_default(cls):
    with pytest.raises(BytesOperationError, match="default"):
        get_codec(cls)


@pytest.mark.parametrize("hint", (Skip[int], list[Skip[int]], OptionalSkip))
def test_skip_is_only_for_class_fields(hint):
    with pytest.raises(BytesOperationError, match="Skip"):
        get_codec(hint)


# - - - - - an explicit codec wins - - - - - #


def test_explicit_codec_is_used_for_collections_and_classes(compile):
    codec_a = StructCodec(">H")
    assert get_codec(t.Annotated[list[U8_B], codec_a]) == codec_a
    assert get_codec(t.Annotated[Plain, codec_a]) == codec_a
    assert get_codec(t.Annotated[str, codec_a]) == codec_a


def test_the_last_explicit_codec_wins():
    hint = t.Annotated[U8_B, StructCodec(">H")]
    assert get_codec(hint) == StructCodec(">H")


# - - - - - hints that can't be built - - - - - #


@pytest.mark.parametrize("hint", (t.Any, t.Callable[[int], int], object))
def test_unresolvable_hints_are_errors(hint):
    with pytest.raises(BytesOperationError):
        get_codec(hint)


def test_module_level_functions_wrap_the_build_errors():
    with pytest.raises(BytesOperationError):
        encode(1, cls=t.Any)
    with pytest.raises(BytesOperationError):
        decode(b"", cls=t.Any)


def test_annotations_of_other_libraries_are_ignored():
    hint = t.Annotated[U8_B, "doc", {"other": 1}, t.Annotated[t.Any, "x"]]
    assert get_codec(hint) == StructCodec(">B")


def test_classvars_are_not_fields(rt):
    @dataclasses.dataclass
    class Cls:
        a: U8_B
        VERSION: t.ClassVar[int] = 1

    assert rt(Cls(5)) == b"\x05"
