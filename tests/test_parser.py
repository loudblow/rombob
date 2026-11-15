import dataclasses
import enum
import typing as t

import pytest
from models import Address, EnumIntegers, EnumStrings, Foo

import rombob
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
    BytesOperationError,
    ClassCodec,
    Codec,
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


# - - - - - custom codecs registry - - - - - #


class SystemAddress:
    def __init__(self, host: str, port: int) -> None:
        self.host, self.port = host, port

    def __eq__(self, other):
        return (self.host, self.port) == (other.host, other.port)


class SystemAddressCodec(Codec[SystemAddress]):
    def read(self, r):
        raw = bytes(r.take(6))
        return SystemAddress(
            ".".join(str(b) for b in raw[:4]), int.from_bytes(raw[4:], "big")
        )

    def write(self, value, w):
        w.write(
            bytes(int(p) for p in value.host.split("."))
            + value.port.to_bytes(2, "big")
        )


@pytest.fixture
def address_codec():
    codec = rombob.register_codec(SystemAddress, SystemAddressCodec())
    yield codec
    rombob.unregister_codec(SystemAddress)


class TestRegisterCodec:
    def test_unknown_type_without_codec(self):
        with pytest.raises(BytesOperationError):
            get_codec(SystemAddress)

    def test_get_codec(self, address_codec):
        assert get_codec(SystemAddress) is address_codec

    def test_class_fields(self, address_codec):
        @dataclasses.dataclass
        class Packet:
            id: U8_B
            addr: SystemAddress
            others: t.Annotated[list[SystemAddress], Len(2)]

        a, b = SystemAddress("1.2.3.4", 80), SystemAddress("5.6.7.8", 443)
        value = Packet(id=1, addr=a, others=[a, b])
        for compile in (True, False):
            codec = get_codec(Packet, compile=compile)
            data = codec.encode(value)
            assert data == b"\x01" + bytes([1, 2, 3, 4, 0, 80]) + bytes(
                [1, 2, 3, 4, 0, 80, 5, 6, 7, 8, 1, 187]
            )
            assert codec.decode(data) == value

    def test_registered_before_cached_class_codec(self):
        @dataclasses.dataclass
        class Holder:
            addr: SystemAddress

        with pytest.raises(BytesOperationError):
            get_codec(Holder)
        rombob.register_codec(SystemAddress, SystemAddressCodec())
        try:
            decoded = get_codec(Holder).decode(b"\x01\x02\x03\x04\x00P")
            assert decoded.addr == SystemAddress("1.2.3.4", 80)
        finally:
            rombob.unregister_codec(SystemAddress)
        with pytest.raises(BytesOperationError):
            get_codec(Holder)

    def test_explicit_annotation_wins(self, address_codec):
        other = SystemAddressCodec()
        hint = t.Annotated[SystemAddress, other]
        assert get_codec(hint) is other

    def test_priority_over_dataclass_and_enum(self):
        @dataclasses.dataclass
        class Point:
            x: U8_B

        codec = RawCodec()
        rombob.register_codec(Point, codec)
        rombob.register_codec(EnumIntegers, codec)
        try:
            assert get_codec(Point) is codec
            assert get_codec(EnumIntegers) is codec
        finally:
            rombob.unregister_codec(Point)
            rombob.unregister_codec(EnumIntegers)
        assert isinstance(get_codec(Point), rombob.ClassCodec)

    def test_generic_falls_back_to_origin(self):
        T = t.TypeVar("T")

        class Box(t.Generic[T]):
            pass

        codec = RawCodec()
        rombob.register_codec(Box, codec)
        try:
            assert get_codec(Box[int]) is codec
        finally:
            rombob.unregister_codec(Box)

    def test_duplicates_and_override(self, address_codec):
        with pytest.raises(BytesOperationError, match=r"already has"):
            rombob.register_codec(SystemAddress, SystemAddressCodec())
        with pytest.raises(BytesOperationError, match=r"already has"):
            rombob.register_codec(int, StructCodec(">i"))

        new = SystemAddressCodec()
        rombob.register_codec(SystemAddress, new, override=True)
        assert get_codec(SystemAddress) is new

    def test_override_builtin_and_restore(self):
        codec = StructCodec(">i")
        rombob.register_codec(int, codec, override=True)
        try:
            assert get_codec(int) is codec
        finally:
            rombob.unregister_codec(int)
        assert get_codec(int) == StructCodec(">q")

    def test_unregister_unknown_is_noop(self):
        rombob.unregister_codec(SystemAddress)

    def test_len_is_rejected(self, address_codec):
        with pytest.raises(BytesOperationError, match=r"Len and Prefix"):
            get_codec(t.Annotated[SystemAddress, Len(2)])

    def test_validation(self):
        codec = RawCodec()
        with pytest.raises(BytesOperationError, match=r"expects a Codec"):
            rombob.register_codec(SystemAddress, SystemAddress)  # type: ignore
        for bad in (
            t.Annotated[int, codec],
            t.Literal[1],
            t.Literal,
            None,
            "SystemAddress",
            t.TypeVar("X"),
            t.Annotated[int, {"a": 1}],
        ):
            with pytest.raises(BytesOperationError):
                rombob.register_codec(bad, codec)


class TestRegisterCodecConsistency:
    def test_override_of_a_primitive_reaches_every_path(self):
        class Wide(enum.IntEnum):
            A = 1

        codec = StructCodec(">i")
        rombob.register_codec(int, codec, override=True)
        try:
            assert get_codec(int) is codec
            assert get_codec(t.Literal[1]).codec is codec
            # the value type of an IntEnum is looked up the same way
            assert get_codec(Wide).codec is codec
            assert get_codec(Wide, compile=False).codec is codec
        finally:
            rombob.unregister_codec(int)
        assert get_codec(Wide).codec == StructCodec(">q")

    def test_falsy_codec_is_still_used(self):
        class Box:
            pass

        class FalsyCodec(Codec):
            def __len__(self):
                return 0

            def read(self, r):
                return Box()

            def write(self, value, w):
                pass

        codec = FalsyCodec()
        rombob.register_codec(Box, codec)
        try:
            assert get_codec(Box) is codec
            assert get_codec(t.Annotated[Box, rombob.Named]) is codec
        finally:
            rombob.unregister_codec(Box)
