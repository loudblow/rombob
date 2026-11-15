import dataclasses
import typing as t

from .buffers import Reader, Writer
from .codecs import (
    Codec,
    CollectionCodec,
    EnumCodec,
    LiteralCodec,
    NamedCodec,
    OptionalCodec,
    ValidatorCodec,
)
from .compiler import ClassCodec, _display_name

# ---------------------------------------------------------------------------
# Error tracing (`trace_errors=True`)
#
# To say *where* an operation failed, it is run once more on a copy of the
# codec tree whose children are wrapped in proxies. The copy is never
# compiled, and every proxy records the path (`.field`, `[index]`) it is
# working on; when something raises, the path of the failure is left behind.
# The normal path pays nothing for this.
# ---------------------------------------------------------------------------


class _TraceProxy(Codec):
    __slots__ = ("codec", "path", "label", "items", "index")

    def __init__(
        self, codec: Codec, path: list[str], label: str, items: bool = False
    ) -> None:
        self.codec = codec
        self.path = path
        self.label = label
        self.items = items
        self.index = 0

    def _push(self) -> bool:
        if self.items:
            self.path.append(f"[{self.index}]")
            self.index += 1
        elif self.label:
            self.path.append(self.label)
        else:
            return False
        return True

    def read(self, r: Reader) -> t.Any:
        pushed = self._push()
        value = _traced(self.codec, self.path).read(r)
        if pushed:
            self.path.pop()
        return value

    def write(self, value: t.Any, w: Writer) -> None:
        pushed = self._push()
        _traced(self.codec, self.path).write(value, w)
        if pushed:
            self.path.pop()


_WRAPPERS = (OptionalCodec, ValidatorCodec, LiteralCodec, EnumCodec, NamedCodec)


def _traced(codec: Codec, path: list[str]) -> Codec:
    "A copy of the codec whose children record their path"
    typ = type(codec)
    if typ is ClassCodec:
        fields = tuple(
            (n, _TraceProxy(c, path, f".{n}")) for n, c in codec.fields
        )
        return ClassCodec(cls=codec.cls, fields=fields, compiled=False)
    if typ is CollectionCodec:
        item = _TraceProxy(codec.item_codec, path, "", items=True)
        return dataclasses.replace(codec, item_codec=item)
    if typ in _WRAPPERS:
        return dataclasses.replace(
            codec, codec=_TraceProxy(codec.codec, path, "")
        )
    return codec


def _format_path(codec: Codec, path: list[str]) -> str:
    root = _display_name(codec.cls) if type(codec) is ClassCodec else ""
    rv = root + "".join(path)
    return rv[1:] if rv.startswith(".") else rv


def _decode_message(
    codec: Codec,
    r: Reader,
    start: int,
    shared: dict[str, t.Any] | None,
    exc: Exception,
    trace: bool,
) -> str:
    if trace:
        path: list[str] = []
        r2 = Reader(r.view, start, shared)
        try:
            _traced(codec, path).read(r2)
        except Exception:
            where = _format_path(codec, path)
            at = f" ({where})" if where else ""
            return f"Decoding failed at offset {r2.offset}{at}: {exc}"
    return f"Decoding failed at offset {r.offset}: {exc}"


def _encode_message(
    codec: Codec,
    value: t.Any,
    length: int,
    shared: dict[str, t.Any] | None,
    exc: Exception,
    trace: bool,
) -> str:
    if trace:
        path: list[str] = []
        w2 = Writer(shared=shared)
        try:
            _traced(codec, path).write(value, w2)
        except Exception:
            where = _format_path(codec, path)
            at = f" ({where})" if where else ""
            return f"Encoding failed at length {len(w2.buffer)}{at}: {exc}"
    return f"Encoding failed at length {length}: {exc}"
