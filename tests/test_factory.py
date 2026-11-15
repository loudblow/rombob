import dataclasses
import typing as t

import pytest

from rombob import (
    U8_B,
    BytesOperationError,
    Factory,
    Reader,
    StructCodec,
    UVInt,
    Writer,
)


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

        w = Writer(bytearray(b"prefix"))
        assert factory.encode_to(Packet(id=1), w) is True
        assert bytes(w.buffer) == b"prefix\x01"
        assert factory.encode_to(WrongPacket(id=4), w) is False
        assert bytes(w.buffer) == b"prefix\x01"

        r = Reader(b"\x01\x04")
        assert factory.decode_from(r) == Packet(id=1)
        assert r.offset == 1
        assert factory.decode_from(r) is None
        assert r.offset == 1
        with pytest.raises(BytesOperationError):
            factory.decode_from(Reader(b""))


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
