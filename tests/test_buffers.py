import dataclasses
import typing as t

import pytest
from models import Foo

import rombob as rb
from rombob import (
    U8_B,
    U16_B,
    BytesOperationError,
    Len,
    Reader,
    UVInt,
    Writer,
    decode,
    encode,
    get_codec,
)

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
