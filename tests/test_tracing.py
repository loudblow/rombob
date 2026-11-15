"""`trace_errors=True`: the failing field is named in the error."""

import dataclasses
import re
import typing as t

import pytest

from rombob import (
    U8_B,
    BytesOperationError,
    Len,
    Named,
    Range,
    Reader,
    When,
    Writer,
    decode,
    encode,
    get_codec,
)


@dataclasses.dataclass
class Item:
    x: U8_B
    name: t.Annotated[str, Len(2)]


@dataclasses.dataclass
class Header:
    items: list[Item]


@dataclasses.dataclass
class Msg:
    header: Header
    tail: tuple[U8_B, t.Annotated[str, Len(2)]]


def good() -> Msg:
    return Msg(Header([Item(1, "ab"), Item(2, "cd")]), (3, "ef"))


def bad_item() -> Msg:
    return Msg(
        Header([Item(1, "ab"), Item(2, "cd"), Item(3, "xyz")]), (3, "ef")
    )


def offset_of(message: str) -> int:
    return int(re.search(r"offset (\d+)", message).group(1))


def test_encode_names_the_failing_field(compile):
    codec = get_codec(Msg, compile=compile)
    with pytest.raises(BytesOperationError) as plain:
        codec.encode(bad_item())
    with pytest.raises(BytesOperationError) as traced:
        codec.encode(bad_item(), trace_errors=True)
    assert "Msg.header.items[2].name" in str(traced.value)
    assert "Msg.header" not in str(plain.value)
    # the cause is still there
    assert "Wrong value length" in str(plain.value)
    assert "Wrong value length" in str(traced.value)


def test_encode_names_a_tuple_item(compile):
    codec = get_codec(Msg, compile=compile)
    value = Msg(Header([]), (3, "efg"))
    with pytest.raises(BytesOperationError, match=r"Msg\.tail\._1"):
        codec.encode(value, trace_errors=True)


def test_decode_names_the_failing_field(compile):
    codec = get_codec(Msg, compile=compile)
    data = codec.encode(good())
    with pytest.raises(BytesOperationError) as plain:
        codec.decode(data[:-1])
    with pytest.raises(BytesOperationError) as traced:
        codec.decode(data[:-1], trace_errors=True)
    assert "Msg.tail._1" in str(traced.value)
    assert "Msg.tail" not in str(plain.value)
    assert offset_of(str(traced.value)) == len(data) - 2
    # cut in the middle of the list
    with pytest.raises(
        BytesOperationError, match=r"Msg\.header\.items\[1\]\.x"
    ):
        codec.decode(data[:5], trace_errors=True)


def test_traced_offset_is_where_the_failure_happened(compile):
    codec = get_codec(Msg, compile=compile)
    data = codec.encode(good())
    with pytest.raises(BytesOperationError) as exc:
        codec.decode(data[:5], trace_errors=True)
    # list size (2) + x (1) + name (2) were read, the next x is missing
    assert offset_of(str(exc.value)) == 5


def test_a_list_at_the_root_has_no_class_name(compile):
    codec = get_codec(list[Item], compile=compile)
    with pytest.raises(BytesOperationError, match=r"\(\[0\]\.x\)"):
        codec.decode(b"\x00\x01", trace_errors=True)
    with pytest.raises(BytesOperationError, match=r"\(\[1\]\.name\)"):
        codec.encode([Item(1, "ab"), Item(2, "c")], trace_errors=True)


def test_a_leaf_has_no_path(compile):
    codec = get_codec(U8_B, compile=compile)
    with pytest.raises(BytesOperationError) as plain:
        codec.decode(b"")
    with pytest.raises(BytesOperationError) as traced:
        codec.decode(b"", trace_errors=True)
    assert str(plain.value) == str(traced.value)


@dataclasses.dataclass
class Boxed:
    a: t.Annotated[U8_B, Range(1, 3)]
    b: t.Annotated[U8_B | None, Range(1, 3)] = None


def test_constraints_are_traced(compile):
    codec = get_codec(Boxed, compile=compile)
    with pytest.raises(BytesOperationError, match=r"\(Boxed\.a\)"):
        codec.encode(Boxed(9), trace_errors=True)
    with pytest.raises(BytesOperationError, match=r"\(Boxed\.b\)"):
        codec.encode(Boxed(1, 9), trace_errors=True)
    with pytest.raises(BytesOperationError, match=r"\(Boxed\.b\)"):
        codec.decode(b"\x01\x09", trace_errors=True)


@dataclasses.dataclass
class Conditional:
    flag: Named[U8_B]
    token: t.Annotated[U8_B | None, When(ref="flag")] = None
    data: t.Annotated[bytes, Len(ref="flag")] = b""


def test_named_fields_work_in_the_traced_run(compile):
    codec = get_codec(Conditional, compile=compile)
    with pytest.raises(BytesOperationError, match=r"\(Conditional\.token\)"):
        codec.encode(Conditional(0, 5), trace_errors=True)
    with pytest.raises(BytesOperationError, match=r"\(Conditional\.data\)"):
        codec.encode(Conditional(2, 5, b"x"), trace_errors=True)
    with pytest.raises(BytesOperationError, match=r"\(Conditional\.data\)"):
        codec.decode(b"\x03\x01ab", trace_errors=True)


def test_success_is_not_traced(compile):
    codec = get_codec(Msg, compile=compile)
    data = codec.encode(good(), trace_errors=True)
    assert data == codec.encode(good())
    assert codec.decode(data, trace_errors=True) == good()


def test_decode_from_leaves_the_reader_as_without_tracing(compile):
    codec = get_codec(Conditional, compile=compile)
    data = b"\x03\x01ab"
    readers = []
    for trace in (False, True):
        r = Reader(data)
        with pytest.raises(BytesOperationError):
            codec.decode_from(r, trace_errors=trace)
        readers.append(r)
    assert readers[0].offset == readers[1].offset
    assert readers[0].data == readers[1].data


def test_decode_from_traces_from_where_it_started(compile):
    codec = get_codec(Item, compile=compile)
    r = Reader(b"\xaa\xbb" + b"\x01a", 2)
    with pytest.raises(BytesOperationError) as exc:
        codec.decode_from(r, trace_errors=True)
    assert "Item.name" in str(exc.value)
    assert offset_of(str(exc.value)) == 3


def test_decode_from_traces_with_the_data_of_the_reader(compile):
    @dataclasses.dataclass
    class Tail:
        data: t.Annotated[bytes, Len(ref="n")]
        more: U8_B

    codec = get_codec(Tail, compile=compile)
    r = Reader(b"abc", shared={"n": 3})
    with pytest.raises(BytesOperationError, match=r"\(Tail\.more\)"):
        codec.decode_from(r, trace_errors=True)


def test_encode_to_leaves_the_writer_as_without_tracing(compile):
    codec = get_codec(Conditional, compile=compile)
    writers = []
    for trace in (False, True):
        w = Writer(bytearray(b"keep"), shared={"x": 1})
        with pytest.raises(BytesOperationError):
            codec.encode_to(Conditional(0, 5), w, trace_errors=trace)
        writers.append(w)
    assert bytes(writers[0].buffer) == bytes(writers[1].buffer) == b"keep"
    assert writers[0].data == writers[1].data


def test_module_level_functions_pass_it_on():
    with pytest.raises(BytesOperationError, match=r"Msg\.header\.items\[2\]"):
        encode(bad_item(), trace_errors=True)
    data = encode(good())
    with pytest.raises(BytesOperationError, match=r"Msg\.tail\._1"):
        decode(data[:-1], cls=Msg, trace_errors=True)
    with pytest.raises(BytesOperationError, match=r"Msg\.tail\._1"):
        decode(data[:-1], cls=Msg, reader=Reader(data[:-1]), trace_errors=True)
    with pytest.raises(BytesOperationError, match=r"Msg\.header\.items\[2\]"):
        encode(bad_item(), cls=Msg, writer=Writer(), trace_errors=True)


def test_the_run_is_repeated_only_when_asked_and_only_on_failure(compile):
    calls = []

    def present(ctx):
        calls.append(1)
        return True

    @dataclasses.dataclass
    class Cls:
        a: t.Annotated[U8_B | None, When(present)]
        b: U8_B

    codec = get_codec(Cls, compile=compile)
    codec.decode(b"\x01\x02", trace_errors=True)  # fine: one run
    assert len(calls) == 1
    calls.clear()
    with pytest.raises(BytesOperationError):
        codec.decode(b"\x01")
    assert len(calls) == 1
    calls.clear()
    with pytest.raises(BytesOperationError):
        codec.decode(b"\x01", trace_errors=True)
    assert len(calls) == 2


def test_a_failure_that_does_not_repeat_keeps_the_plain_message(compile):
    calls = []

    def flaky(ctx):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("boom")
        return True

    @dataclasses.dataclass
    class Cls:
        a: t.Annotated[U8_B | None, When(flaky)]

    codec = get_codec(Cls, compile=compile)
    with pytest.raises(BytesOperationError) as exc:
        codec.decode(b"\x01", trace_errors=True)
    assert "boom" in str(exc.value)
    assert "Cls.a" not in str(exc.value)
