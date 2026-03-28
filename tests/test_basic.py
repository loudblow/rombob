import binascii
import dataclasses
import decimal as d
import enum
import math
import typing as t

import pytest
from annotated_types import Len

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
    CollectionCodec,
    Context,
    EnumCodec,
    Factory,
    IntCodec,
    IVInt,
    LiteralCodec,
    Named,
    NamedCodec,
    OptionalCodec,
    Raw,
    RawCodec,
    StringCodec,
    StructCodec,
    UVInt,
    ValidatorCodec,
    VarIntCodec,
    decode,
    encode,
    get_codec,
)

T = t.TypeVar("T")


class BadBool:
    def __bool__(self):
        raise ValueError("I refuse to be a boolean!")


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
            tuple[tuple[U8_B]],
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
            t.Annotated[tuple[str], Len(1)],
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


# - - - - - NUMERIC DATA - - - - - #


@pytest.mark.parametrize(
    "hint, cls, min, max, expected, expected_len",
    (
        (bool, bool, False, True, b"0001", 2),
        (I8_B, int, -128, 127, b"807f", 2),
        (I8_L, int, -128, 127, b"807f", 2),
        (U8_B, int, 0, 254, b"00fe", 2),
        (U8_L, int, 0, 254, b"00fe", 2),
        (I16_B, int, -32768, 32766, b"80007ffe", 4),
        (I16_L, int, -32768, 32766, b"0080fe7f", 4),
        (U16_B, int, 0, 65534, b"0000fffe", 4),
        (U16_L, int, 0, 65534, b"0000feff", 4),
        (I24_B, int, -8388608, 8388607, b"8000007fffff", 6),
        (I24_L, int, -8388608, 8388607, b"000080ffff7f", 6),
        (U24_B, int, 0, 16777214, b"000000fffffe", 6),
        (U24_L, int, 0, 16777214, b"000000feffff", 6),
        (I32_B, int, -2147483648, 2147483647, b"800000007fffffff", 8),
        (I32_L, int, -2147483648, 2147483647, b"00000080ffffff7f", 8),
        (U32_B, int, 0, 4294967294, b"00000000fffffffe", 8),
        (U32_L, int, 0, 4294967294, b"00000000feffffff", 8),
        (
            I48_B,
            int,
            -140737488355328,
            140737488355327,
            b"8000000000007fffffffffff",
            12,
        ),
        (
            I48_L,
            int,
            -140737488355328,
            140737488355327,
            b"000000000080ffffffffff7f",
            12,
        ),
        (U48_B, int, 0, 281474976710654, b"000000000000fffffffffffe", 12),
        (U48_L, int, 0, 281474976710654, b"000000000000feffffffffff", 12),
        (
            I64_B,
            int,
            -9223372036854775808,
            9223372036854775807,
            b"80000000000000007fffffffffffffff",
            16,
        ),
        (
            I64_L,
            int,
            -9223372036854775808,
            9223372036854775807,
            b"0000000000000080ffffffffffffff7f",
            16,
        ),
        (
            U64_B,
            int,
            0,
            18446744073709551614,
            b"0000000000000000fffffffffffffffe",
            16,
        ),
        (
            U64_L,
            int,
            0,
            18446744073709551614,
            b"0000000000000000feffffffffffffff",
            16,
        ),
        (F16_B, float, -65504, 65504, b"fbff7bff", 4),
        (F16_B, float, float("-inf"), float("inf"), b"fc007c00", 4),
        (F16_B, float, float("-nan"), float("nan"), b"fe007e00", 4),
        (F16_L, float, -65504, 65504, b"fffbff7b", 4),
        (F16_L, float, float("-inf"), float("inf"), b"00fc007c", 4),
        (F16_L, float, float("-nan"), float("nan"), b"00fe007e", 4),
        (F32_B, float, -1.75, 1.75, b"bfe000003fe00000", 8),
        (F32_B, float, float("-inf"), float("inf"), b"ff8000007f800000", 8),
        (F32_B, float, float("-nan"), float("nan"), b"ffc000007fc00000", 8),
        (F32_L, float, -1.75, 1.75, b"0000e0bf0000e03f", 8),
        (F32_L, float, float("-inf"), float("inf"), b"000080ff0000807f", 8),
        (F32_L, float, float("-nan"), float("nan"), b"0000c0ff0000c07f", 8),
        (F64_B, float, -1.75, 1.75, b"bffc0000000000003ffc000000000000", 16),
        (
            F64_B,
            float,
            float("-inf"),
            float("inf"),
            b"fff00000000000007ff0000000000000",
            16,
        ),
        (
            F64_B,
            float,
            float("-nan"),
            float("nan"),
            b"fff80000000000007ff8000000000000",
            16,
        ),
        (F64_L, float, -1.75, 1.75, b"000000000000fcbf000000000000fc3f", 16),
        (
            F64_L,
            float,
            float("-inf"),
            float("inf"),
            b"000000000000f0ff000000000000f07f",
            16,
        ),
        (
            F64_L,
            float,
            float("-nan"),
            float("nan"),
            b"000000000000f8ff000000000000f87f",
            16,
        ),
        (IVInt, int, 0, 1, b"0002", 2),
        (IVInt, int, 0, -1, b"0001", 2),
        (IVInt, int, -32768, 32767, b"ffff03feff03", 6),
        (UVInt, int, 0, 127, b"007f", 2),
        (UVInt, int, 0, 128, b"008001", 3),
        (UVInt, int, 16383, 16384, b"ff7f808001", 5),
    ),
)
def test_numeric_write_read(hint, cls, min, max, expected, expected_len):
    codec = get_codec(hint)
    ctx = Context(buffer=bytearray())
    ctx.write(codec, min)
    ctx.write(codec, max)
    assert bytes(ctx.buffer) == binascii.unhexlify(expected)
    assert len(ctx.buffer) == expected_len

    for value in (min, max):
        read_value = ctx.read(codec)
        assert isinstance(read_value, cls)
        if math.isnan(read_value):
            assert math.isnan(read_value) == math.isnan(value)
        else:
            assert read_value == value

    assert len(ctx.buffer) == 0


@pytest.mark.parametrize(
    "hint, min, max",
    (
        (bool, BadBool(), BadBool()),
        (I8_B, -129, 128),
        (I8_L, -129, 128),
        (U8_B, -1, 256),
        (U8_L, -1, 256),
        (I16_B, -32769, 32768),
        (I16_L, -32769, 32768),
        (U16_B, -1, 65536),
        (U16_L, -1, 65536),
        (I24_B, -8388609, 8388608),
        (I24_L, -8388609, 8388608),
        (U24_B, -1, 16777216),
        (U24_L, -1, 16777216),
        (I32_B, -2147483649, 2147483648),
        (I32_L, -2147483649, 2147483648),
        (U32_B, -1, 4294967296),
        (U32_L, -1, 4294967296),
        (I48_B, -140737488355329, 140737488355328),
        (I48_L, -140737488355329, 140737488355328),
        (U48_B, -1, 281474976710656),
        (U48_L, -1, 281474976710656),
        (I64_B, -9223372036854775809, 9223372036854775808),
        (I64_L, -9223372036854775809, 9223372036854775808),
        (U64_B, -1, 18446744073709551616),
        (U64_L, -1, 18446744073709551616),
        (F16_B, -6.6e04, 6.6e04),
        (F16_L, -6.6e04, 6.6e04),
        (F32_B, -3.5e38, 3.5e38),
        (F32_L, -3.5e38, 3.5e38),
        (F64_B, -2 * 10**308, 2 * 10**308),
        (F64_L, -2 * 10**308, 2 * 10**308),
        (UVInt, -1, -1),
    ),
)
def test_numeric_wrong_data_size(hint, min, max):
    ctx = Context(bytearray())
    codec = get_codec(hint)
    with pytest.raises(BytesOperationError):
        ctx.write(codec, min)
    with pytest.raises(BytesOperationError):
        ctx.write(codec, max)
    assert len(ctx.buffer) == 0


@pytest.mark.parametrize(
    "hint, values",
    (
        (bool, [BadBool()]),
        (I8_B, [""]),
        (I8_L, [""]),
        (U8_B, [""]),
        (U8_L, [""]),
        (I16_B, [""]),
        (I16_L, [""]),
        (U16_B, [""]),
        (U16_L, [""]),
        (I24_B, [""]),
        (I24_L, [""]),
        (U24_B, [""]),
        (U24_L, [""]),
        (I32_B, [""]),
        (I32_L, [""]),
        (U32_B, [""]),
        (U32_L, [""]),
        (I48_B, [""]),
        (I48_L, [""]),
        (U48_B, [""]),
        (U48_L, [""]),
        (I64_B, [""]),
        (I64_L, [""]),
        (U64_B, [""]),
        (U64_L, [""]),
        (F16_B, [""]),
        (F16_L, [""]),
        (F32_B, [""]),
        (F32_L, [""]),
        (F64_B, [""]),
        (F64_L, [""]),
        (UVInt, [""]),
        (IVInt, [""]),
    ),
)
def test_numeric_wrong_data_type(hint, values):
    ctx = Context(bytearray())
    codec = get_codec(hint)
    for v in values:
        with pytest.raises(BytesOperationError):
            ctx.write(codec, v)
    assert len(ctx.buffer) == 0


# - - - - - SEQUENCED DATA - - - - - #


@pytest.mark.parametrize(
    "hint, cls, value, expected, expected_len",
    (
        (str, str, "Hello", b"000548656c6c6f", 7),
        (t.Annotated[str, Len(5)], str, "Hello", b"48656c6c6f", 5),
        (bytes, bytes, b"Hello", b"000548656c6c6f", 7),
        (t.Annotated[bytes, Len(5)], bytes, b"Hello", b"48656c6c6f", 5),
        (Raw, bytes, b"\x7f", b"7f", 1),
        (t.Annotated[bytes, Len(2)], bytes, b"\x7f\x7f", b"7f7f", 2),
        (list[str], list, ["Hello", "Hi"], b"0002000548656c6c6f00024869", 13),
        (tuple[IVInt], tuple, (0, 0, 1), b"0003000002", 5),
        (set[IVInt], set, {0}, b"000100", 3),
        # TODO
        # (
        #    collections.UserList[str],
        #    ['Hello', 'Hi'],
        #    b'0002000548656c6c6f00024869',
        #    13,
        # ),
        (
            t.Annotated[list[str], Len(2)],
            list,
            ["Hello", "Hi"],
            b"000548656c6c6f00024869",
            11,
        ),
        (t.Annotated[tuple[I8_B], Len(3)], tuple, (-128, 0, 127), b"80007f", 3),
        (
            t.Annotated[
                int,
                ValidatorCodec(
                    codec=StructCodec(">b"),
                    read_validator=lambda d: str(d),
                    write_validator=lambda d: int(d),
                ),
            ],
            str,
            "127",
            b"7f",
            1,
        ),
        (
            t.Annotated[t.Literal[127], I8_B],
            int,
            127,
            b"7f",
            1,
        ),
        (
            t.Annotated[EnumIntegers, U8_B],
            EnumIntegers,
            EnumIntegers.a,
            b"00",
            1,
        ),
        (
            t.Annotated[EnumIntegers, U8_B],
            EnumIntegers,
            EnumIntegers.b,
            b"01",
            1,
        ),
        (EnumStrings, EnumStrings, EnumStrings.a, b"000161", 3),
        (EnumStrings, EnumStrings, EnumStrings.b, b"00026262", 4),
        (I8_B | None, int, 127, b"7f", 1),
        (I8_B | None, type(None), None, b"", 0),
    ),
)
def test_sequence_write_read(hint, cls, value, expected, expected_len):
    codec = get_codec(hint)
    ctx = Context(buffer=bytearray())
    ctx.write(codec, value)
    assert bytes(ctx.buffer) == binascii.unhexlify(expected)
    assert len(ctx.buffer) == expected_len

    ctx.buffer = memoryview(ctx.buffer)
    read_value = ctx.read(codec)
    assert read_value == value
    assert isinstance(read_value, cls)
    assert len(ctx.buffer) == 0


@pytest.mark.parametrize(
    "hint, value",
    (
        (str, "0" * 65536),
        (t.Annotated[str, Len(5)], "0" * 6),
        (bytes, b"0" * 65536),
        (t.Annotated[bytes, Len(5)], b"0" * 6),
        (t.Annotated[bytes, Len(2)], b"\x7f"),
        (list[I8_B], [1] * 65536),
        (t.Annotated[list[str], Len(2)], ["Hello"]),
        (t.Annotated[tuple[I8_B], Len(3)], [-128, 0, 127, 0]),
        (I8_B | None, 128),
    ),
    ids=["a", "b", "c", "d", "e", "f", "g", "j", "k"],
)
def test_sequence_wrong_data_size(hint, value):
    codec = get_codec(hint)
    ctx = Context(bytearray())
    with pytest.raises(BytesOperationError):
        ctx.write(codec, value)
    assert len(ctx.buffer) == 0


@pytest.mark.parametrize(
    "hint, value",
    (
        (Raw, 1),
        (t.Annotated[bytes, Len(2)], "7f"),
        # TODO
        # (
        #    ValidatorCodec(
        #        codec=StructCodec('>b'),
        #        read_validator=lambda d: str(d),
        #        write_validator=lambda d: int(d),
        #    ),
        #    '129',
        # ),
        # TODO
        # (
        #    ValidatorCodec(
        #        codec=StructCodec('>b'),
        #        read_validator=lambda d: str(d),
        #        write_validator=lambda d: int(d),
        #    ),
        #    'He',
        # ),
        (t.Literal["127"], "126"),
        (t.Annotated[EnumIntegers, U16_B], 2),
        (t.Annotated[EnumIntegers, U16_B], EnumIntegers),
        (EnumStrings, "ccc"),
        (EnumStrings, EnumStrings),
    ),
)
def test_sequence_wrong_data_type(hint, value):
    codec = get_codec(hint)
    ctx = Context(bytearray())
    with pytest.raises(BytesOperationError):
        ctx.write(codec, value)
    assert len(ctx.buffer) == 0


@pytest.mark.parametrize(
    "codec, value",
    ((NamedCodec(codec=StringCodec(), key="first_name"), "Zaza"),),
)
def test_named(codec, value):
    ctx = Context()
    ctx.write(codec, value)
    assert codec.key in ctx.data
    assert ctx.data[codec.key] == value

    ctx = Context(bytearray(ctx.buffer))
    assert ctx.read(codec) == value
    assert codec.key in ctx.data
    assert ctx.data[codec.key] == value


@dataclasses.dataclass
class ManyTypesDC(t.Generic[T]):
    strenum: EnumStrings
    intenum: t.Annotated[EnumIntegers, U8_B]
    integer: U8_B
    string: str
    boolean: bool
    dynamic: list[str]
    fixed: t.Annotated[list[str], Len(3)]
    typevar: T
    literal_1: t.Annotated[t.Literal[3, 2, 1], U8_B]
    literal_2: t.Annotated[t.Literal["Privet"], StringCodec()]
    validated_decimal: t.Annotated[
        d.Decimal,
        ValidatorCodec(
            codec=StringCodec(),
            read_validator=lambda val: d.Decimal(val),
            write_validator=lambda val: str(val),
        ),
    ]
    named: Named[str]
    address: Address
    somebytes: bytes
    somemorebytes: t.Annotated[bytes, Len(2)]
    optional: Raw | None = None


def test_class_codec():
    data = ManyTypesDC[bool](
        strenum=EnumStrings.b,
        intenum=EnumIntegers.a,
        integer=255,
        string="string",
        boolean=True,
        dynamic=["1"],
        fixed=["1", "2", "3"],
        typevar=False,
        literal_1=3,
        literal_2="Privet",
        validated_decimal=d.Decimal("10"),
        named="hey",
        address=Address("0.0.0.0", 19132),
        somebytes=b"\x01\x02",
        somemorebytes=b"\x00\x00",
        optional=None,
    )
    codec = get_codec(ManyTypesDC[bool])
    ctx = Context()
    ctx.write(codec, data)
    ctx.buffer = memoryview(ctx.buffer)
    assert ctx.read(codec) == data

    dd = encode(data, codec=codec)
    assert decode(dd, codec=codec) == data

    with pytest.raises(BytesOperationError):
        data.integer = 256
        data.somemorebytes = b"\x00"
        Context().write(codec, data)


class TestFactory:
    def test_register(self):
        factory = Factory("id")

        with pytest.raises(
            BytesOperationError,
            match=r"must be a class",
        ):
            factory.register(str)

        with pytest.raises(
            BytesOperationError,
            match=r"have no codec for field",
        ):

            @factory.register
            @dataclasses.dataclass
            class Packet:
                id_: t.Literal[1, 2, 3]

        with pytest.raises(
            BytesOperationError,
            match=r"should be typing.Literal",
        ):

            @factory.register
            @dataclasses.dataclass
            class Packet:
                id: list[str]

        @factory.register
        @dataclasses.dataclass
        class Packet:
            id: t.Literal[1, 2, 3]

        assert factory.id_map[1] == Packet
        assert factory.id_map[2] == Packet
        assert factory.id_map[3] == Packet
        assert 1 in factory.codecs
        assert 2 in factory.codecs
        assert 3 in factory.codecs
        assert len(factory.id_map) == 3
        assert len(factory.codecs) == 3

    def test_register_subclasses(self):
        @dataclasses.dataclass
        class Packet:
            id: t.Literal[100]

        @dataclasses.dataclass
        class PacketA(Packet):
            id: t.Literal[1]

        @dataclasses.dataclass
        class PacketB(Packet):
            id: t.Literal[2]

        @dataclasses.dataclass
        class PacketAA(PacketA):
            id: t.Literal[3]

        factory = Factory("id")
        factory.register_subclasses(Packet)

        assert factory.id_map.get(100) is None
        assert factory.id_map[1] == PacketA
        assert factory.id_map[2] == PacketB
        assert factory.id_map.get(3) is None

        factory = Factory("id")
        factory.register_subclasses(Packet, include_base=True)

        assert factory.id_map.get(100) == Packet
        assert factory.id_map[1] == PacketA
        assert factory.id_map[2] == PacketB
        assert factory.id_map.get(3) is None

    def test_encode_decode(self):
        factory = Factory("id")

        @factory.register
        @dataclasses.dataclass
        class Packet:
            id: t.Annotated[t.Literal[1, 2, 3], StructCodec(">B")]

        @dataclasses.dataclass
        class SimilarPacket:
            id: t.Annotated[t.Literal[1, 2, 3], StructCodec(">B")]

        @dataclasses.dataclass
        class WrongPacket:
            id: t.Annotated[t.Literal[4, 5, 6], StructCodec(">B")]

        assert factory.encode(Packet(id=1)) == b"\x01"
        assert factory.encode(SimilarPacket(id=2)) == b"\x02"
        assert factory.encode(WrongPacket(id=4)) is None

        assert factory.decode(b"\x01") == Packet(id=1)
        assert factory.decode(b"\x02") == Packet(id=2)
        assert factory.decode(b"\x04") is None
        with pytest.raises(BytesOperationError):
            factory.decode(b"")
