import dataclasses
import typing as t

import pytest

from rombob import Reader, Writer, get_codec


@pytest.fixture(params=[True, False], ids=["compiled", "plain"])
def compile(request):
    "Whether classes are built with the compiler (see `get_codec(compile=)`)"
    return request.param


class Subject:
    """
    Runs one hint through a codec in one of three modes:

    * `direct`: the bare codec, values are written/read one after another;
    * `compiled` / `plain`: the values are fields of a dataclass whose codec
      is built with / without the compiler.

    The binary form is the same in all modes, so tables of
    (hint, values, bytes) can be checked against each of them.
    """

    def __init__(self, hint: t.Any, n: int, mode: str) -> None:
        self.n = n
        self.mode = mode
        if mode == "direct":
            self.codec = get_codec(hint)
        else:
            self.names = [f"f{i}" for i in range(n)]
            self.cls = dataclasses.make_dataclass(
                "Box", [(name, hint) for name in self.names]
            )
            self.codec = get_codec(self.cls, compile=mode == "compiled")

    def encode_to(self, values: tuple, w: Writer) -> None:
        "Append the values; on failure `w` is left intact"
        if self.mode == "direct":
            start = len(w.buffer)
            try:
                for value in values:
                    self.codec.encode_to(value, w)
            except Exception:
                del w.buffer[start:]
                raise
        else:
            self.codec.encode_to(self.cls(*values), w)

    def decode(self, data: bytes) -> tuple:
        "All the values, the data must be consumed completely"
        r = Reader(data)
        if self.mode == "direct":
            values = tuple(self.codec.read(r) for _ in range(self.n))
        else:
            box = self.codec.decode_from(r)
            values = tuple(getattr(box, name) for name in self.names)
        assert r.remaining == 0
        return values


@pytest.fixture(params=["direct", "compiled", "plain"])
def subject(request):
    "Factory `subject(hint, n=1)`, see `Subject`"

    def make(hint: t.Any, n: int = 1) -> Subject:
        return Subject(hint, n, request.param)

    return make


@pytest.fixture
def rt():
    """
    `rt(value, hint=None)`: encode/decode through the compiled and the plain
    codec, check both give the same bytes and the same value, return the bytes
    """

    def run(value: t.Any, hint: t.Any = None) -> bytes:
        hint = hint or type(value)
        datas = []
        for compile_ in (True, False):
            codec = get_codec(hint, compile=compile_)
            data = codec.encode(value)
            assert codec.decode(data) == value
            datas.append(data)
        assert datas[0] == datas[1]
        return datas[0]

    return run
