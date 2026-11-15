import dataclasses
import enum
import functools
import linecache
import operator
import re
import struct as s
import types
import typing as t

from .metadata import (
    CONSTRAINTS,
    NAMED,
    SKIP,
    Ge,
    Gt,
    Le,
    Len,
    Lt,
    Named,
    Predicate,
    Prefix,
    Range,
    Skip,
    When,
)

__all__ = [
    "Named",
    "Skip",
    "Len",
    "Prefix",
    "Gt",
    "Ge",
    "Lt",
    "Le",
    "Range",
    "Predicate",
    "When",
    "RefLenCodec",
    "BytesOperationError",
    "Reader",
    "Writer",
    "ByteOrder",
    "LE",
    "BE",
    "Codec",
    "StructCodec",
    "IntCodec",
    "VarIntCodec",
    "StringCodec",
    "BytesCodec",
    "CollectionCodec",
    "RawCodec",
    "OptionalCodec",
    "ValidatorCodec",
    "EnumCodec",
    "Factory",
    "LiteralCodec",
    "NamedCodec",
    "ClassCodec",
    "StructSegment",
    "DynamicSegment",
    "OptionalSegment",
    "I8_L",
    "I8_B",
    "U8_L",
    "U8_B",
    "I16_L",
    "I16_B",
    "U16_L",
    "U16_B",
    "I24_L",
    "I24_B",
    "U24_L",
    "U24_B",
    "I32_L",
    "I32_B",
    "U32_L",
    "U32_B",
    "I48_L",
    "I48_B",
    "U48_L",
    "U48_B",
    "I64_L",
    "I64_B",
    "U64_L",
    "U64_B",
    "F16_L",
    "F16_B",
    "F32_L",
    "F32_B",
    "F64_L",
    "F64_B",
    "IVInt",
    "UVInt",
    "Raw",
    "ParserContext",
    "Args",
    "get_codec",
    "encode",
    "decode",
]


T = t.TypeVar("T")
B = t.TypeVar("B")
EnumT = t.TypeVar("EnumT", bound=enum.Enum)
Buffer = t.Union[bytes, bytearray, memoryview]  # noqa: UP007


class BytesOperationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Reader / Writer
# ---------------------------------------------------------------------------


class Reader:
    """
    Cursor over an input buffer.

    The reader never slices-and-reassigns the buffer: the position is the
    `offset` only. All values handed out by codecs are copies.
    """

    __slots__ = ("view", "offset", "data")

    def __init__(
        self,
        data: Buffer,
        offset: int = 0,
        shared: dict[str, t.Any] | None = None,
    ) -> None:
        view = memoryview(data)
        if view.format != "B" or view.ndim != 1:
            view = view.cast("B")
        self.view = view
        self.offset = offset
        self.data: dict[str, t.Any] = {} if shared is None else shared

    def __repr__(self) -> str:
        return f"Reader(offset={self.offset}, size={len(self.view)})"

    @property
    def remaining(self) -> int:
        return len(self.view) - self.offset

    def take(self, n: int) -> memoryview:
        "Return a view of the next n bytes and advance"
        start = self.offset
        end = start + n
        if n < 0 or end > len(self.view):
            raise BytesOperationError(
                f"Not enough data: need {n} bytes at offset {start}, "
                f"only {len(self.view) - start} left"
            )
        self.offset = end
        return self.view[start:end]

    def peek(self, n: int, skip: int = 0) -> memoryview:
        "Return a view of n bytes starting `skip` bytes ahead, don't advance"
        start = self.offset + skip
        end = start + n
        if n < 0 or skip < 0 or end > len(self.view):
            raise BytesOperationError(
                f"Not enough data: need {n} bytes at offset {start}, "
                f"only {max(len(self.view) - start, 0)} left"
            )
        return self.view[start:end]

    def rest(self) -> bytes:
        "Copy of everything left; advances to the end"
        rv = bytes(self.view[self.offset :])
        self.offset = len(self.view)
        return rv

    def unpack(self, st: s.Struct) -> tuple:
        rv = st.unpack_from(self.view, self.offset)
        self.offset += st.size
        return rv

    def to_writer(self) -> "Writer":
        return Writer(shared=self.data)

    def release(self) -> None:
        try:
            self.view.release()
        except BufferError:
            pass


class Writer:
    "Append-only output buffer. `buffer` is always a bytearray."

    __slots__ = ("buffer", "data")

    def __init__(
        self,
        buffer: bytearray | None = None,
        shared: dict[str, t.Any] | None = None,
    ) -> None:
        self.buffer = bytearray() if buffer is None else buffer
        self.data: dict[str, t.Any] = {} if shared is None else shared

    def __repr__(self) -> str:
        return f"Writer(length={len(self.buffer)})"

    def write(self, b: Buffer) -> None:
        self.buffer += b

    def pack(self, st: s.Struct, *values: t.Any) -> None:
        self.buffer += st.pack(*values)

    def getvalue(self) -> bytes:
        return bytes(self.buffer)

    def to_reader(self) -> Reader:
        "Reader over a snapshot of the buffer, sharing `data`"
        return Reader(bytes(self.buffer), shared=self.data)


class ByteOrder(str, enum.Enum):
    LITTLE = "little"
    BIG = "big"


LE = ByteOrder.LITTLE
BE = ByteOrder.BIG


class Codec(t.Generic[T]):
    """
    Base class of all codecs. Subclasses implement `write`/`read`, which are
    used internally (and recursively) and never wrap errors. `encode`,
    `encode_to`, `decode` and `decode_from` are the entry points: they are
    where errors are wrapped into `BytesOperationError`.

    Codecs must be stateless: all per-call state lives in Reader/Writer,
    so one codec can be shared by any number of calls.
    """

    __slots__ = ()

    def write(self, value: T, w: Writer) -> None:
        raise NotImplementedError

    def read(self, r: Reader) -> T:
        raise NotImplementedError

    def encode(self, value: T, *, trace_errors: bool = False) -> bytes:
        """
        Encode the value into new bytes.

        :param trace_errors: on failure, run the value once more through
            a slower, non-compiled path to name the failing field in the
            error, e.g. `Msg.header.items[3]`. Costs nothing unless it fails.
        """
        w = Writer()
        try:
            self.write(value, w)
        except Exception as exc:
            raise BytesOperationError(
                _encode_message(
                    self, value, len(w.buffer), None, exc, trace_errors
                )
            ) from exc
        return bytes(w.buffer)

    def encode_to(
        self, value: T, w: Writer, *, trace_errors: bool = False
    ) -> None:
        """
        Append the encoded value to `w`. On failure `w` is left intact.
        See `encode` for `trace_errors`.
        """
        start = len(w.buffer)
        shared = dict(w.data) if trace_errors else None
        try:
            self.write(value, w)
        except Exception as exc:
            del w.buffer[start:]
            raise BytesOperationError(
                _encode_message(
                    self, value, len(w.buffer), shared, exc, trace_errors
                )
            ) from exc

    def decode(self, data: Buffer, *, trace_errors: bool = False) -> T:
        """
        Decode a value from the start of `data`.
        See `encode` for `trace_errors`.
        """
        r = Reader(data)
        try:
            return self.read(r)
        except Exception as exc:
            raise BytesOperationError(
                _decode_message(self, r, 0, None, exc, trace_errors)
            ) from exc
        finally:
            r.release()

    def decode_from(self, r: Reader, *, trace_errors: bool = False) -> T:
        """
        Decode a value at the reader's offset and advance it.
        See `encode` for `trace_errors`.
        """
        start = r.offset
        shared = dict(r.data) if trace_errors else None
        try:
            return self.read(r)
        except Exception as exc:
            raise BytesOperationError(
                _decode_message(self, r, start, shared, exc, trace_errors)
            ) from exc


@functools.cache
def _struct(fmt: str) -> s.Struct:
    return s.Struct(fmt)


_COMPILE = True  # see get_codec(compile=...)


# ---------------------------------------------------------------------------
# Primitive codecs
# ---------------------------------------------------------------------------


class StructCodec(s.Struct, Codec[T]):
    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        return type(other) is type(self) and other.format == self.format

    def __hash__(self) -> int:
        return hash((StructCodec, self.format))

    def __repr__(self) -> str:
        return f"StructCodec(format={self.format!r})"

    def write(self, value: T, w: Writer) -> None:
        w.buffer += self.pack(value)

    def read(self, r: Reader) -> T:
        rv = self.unpack_from(r.view, r.offset)[0]
        r.offset += self.size
        return rv


@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class IntCodec(Codec[int]):
    length: int
    byteorder: ByteOrder
    signed: bool

    def write(self, value: int, w: Writer) -> None:
        w.buffer += value.to_bytes(
            self.length, self.byteorder, signed=self.signed
        )

    def read(self, r: Reader) -> int:
        return int.from_bytes(
            r.take(self.length), self.byteorder, signed=self.signed
        )


@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class VarIntCodec(Codec[int]):
    signed: bool

    def write(self, value: int, w: Writer) -> None:
        if self.signed:
            value = ~(value << 1) if value < 0 else (value << 1)
        elif value < 0:
            raise BytesOperationError(
                f"value={value} should be greater than or equal 0"
            )
        buf = w.buffer
        if value < 0x80:
            buf.append(value)
            return
        while True:
            d = value & 0x7F
            value >>= 7
            if value:
                buf.append(d | 0x80)
            else:
                buf.append(d)
                break

    def read(self, r: Reader) -> int:
        view = r.view
        size = len(view)
        i = r.offset
        value = 0
        shift = 0
        while True:
            if i >= size:
                raise BytesOperationError(
                    f"Truncated varint at offset {r.offset}"
                )
            d = view[i]
            i += 1
            value |= (d & 0x7F) << shift
            if d < 0x80:
                break
            shift += 7
        r.offset = i
        if self.signed:
            return ~(value >> 1) if value & 1 else (value >> 1)
        return value


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class StringCodec(Codec[str]):
    len_codec: Codec = StructCodec(">H")
    length: int | None = None

    def write(self, value: str, w: Writer) -> None:
        data = value.encode("utf-8")
        length = len(data)
        if self.length is None:
            self.len_codec.write(length, w)
        elif self.length != length:
            raise BytesOperationError(
                f"Wrong value length: got {length}, expected {self.length}"
            )
        w.buffer += data

    def read(self, r: Reader) -> str:
        length = (
            self.length if self.length is not None else self.len_codec.read(r)
        )
        return str(r.take(length), "utf-8")


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class BytesCodec(Codec[bytes]):
    len_codec: Codec = StructCodec(">H")
    length: int | None = None

    def write(self, value: bytes, w: Writer) -> None:
        length = len(value)
        if self.length is None:
            self.len_codec.write(length, w)
        elif self.length != length:
            raise BytesOperationError(
                f"Wrong value length: got {length}, expected {self.length}"
            )
        w.buffer += value

    def read(self, r: Reader) -> bytes:
        length = (
            self.length if self.length is not None else self.len_codec.read(r)
        )
        return bytes(r.take(length))


def _wrap_collection(cls: t.Any, values: t.Iterable) -> t.Any:
    if cls is list:
        return list(values)
    if cls is tuple:
        return tuple(values)
    if cls is set:
        return set(values)
    if cls is frozenset:
        return frozenset(values)
    return cls(values)


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class CollectionCodec(Codec[T]):
    cls: t.Any
    item_codec: Codec
    len_codec: Codec = StructCodec(">H")
    length: int | None = None
    # (struct prefix, item char) when items are plain struct values
    _fast: tuple[str, str] | None = dataclasses.field(
        init=False, repr=False, compare=False, default=None
    )
    _fixed: s.Struct | None = dataclasses.field(
        init=False, repr=False, compare=False, default=None
    )

    def __post_init__(self) -> None:
        leaf = _leaf_item(self.item_codec)
        if leaf is None:
            return
        prefix = leaf[0] or ">"
        object.__setattr__(self, "_fast", (prefix, leaf[1]))
        if self.length is not None:
            object.__setattr__(
                self, "_fixed", _struct(f"{prefix}{self.length}{leaf[1]}")
            )

    def write(self, value: T, w: Writer) -> None:
        length = len(value)
        if self.length is None:
            self.len_codec.write(length, w)
        elif self.length != length:
            raise BytesOperationError(
                f"Wrong collection size, got {length}, expected {self.length}"
            )

        fast = self._fast
        if fast is None:
            write = self.item_codec.write
            for item in value:
                write(item, w)
        elif fast[1] == "B":
            w.buffer += bytes(value)
        else:
            st = self._fixed or _struct(f"{fast[0]}{length}{fast[1]}")
            w.buffer += st.pack(*value)

    def read(self, r: Reader) -> T:
        length = (
            self.length if self.length is not None else self.len_codec.read(r)
        )
        fast = self._fast
        if fast is not None:
            if fast[1] == "B":
                values = r.take(length)
            else:
                values = r.unpack(
                    self._fixed or _struct(f"{fast[0]}{length}{fast[1]}")
                )
            return _wrap_collection(self.cls, values)

        read = self.item_codec.read
        cls = self.cls
        # handle the builtin types first for speed; subclasses handled below
        if cls is list:
            return [read(r) for _ in range(length)]
        elif cls is tuple:
            return tuple([read(r) for _ in range(length)])
        elif cls is set:
            return {read(r) for _ in range(length)}
        elif cls is frozenset:
            return frozenset({read(r) for _ in range(length)})
        else:
            return cls(read(r) for _ in range(length))


@dataclasses.dataclass(slots=True, frozen=True)
class RawCodec(Codec[bytes]):
    def write(self, value: bytes, w: Writer) -> None:
        w.buffer += value

    def read(self, r: Reader) -> bytes:
        return r.rest()


def _tuple_size_error(got: int, expected: int) -> BytesOperationError:
    return BytesOperationError(
        f"Wrong tuple size, got {got}, expected {expected}"
    )


def _optional_missing(name: str = "") -> BytesOperationError:
    return BytesOperationError(
        f"{name or 'The value'} is None but its When condition holds"
    )


def _optional_extra(name: str = "") -> BytesOperationError:
    return BytesOperationError(
        f"{name or 'The value'} is set but its When condition doesn't hold"
    )


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class OptionalCodec(Codec[T]):
    """
    Without a predicate: read if there is data left, write if not None.
    With a predicate (see `When`): the field is present exactly when the
    predicate, called with the Reader/Writer, is true. Writing a value that
    disagrees with it is an error.
    """

    codec: Codec[T]
    predicate: t.Callable[[Reader | Writer], bool] | None = None

    def read(self, r: Reader) -> T | None:
        if self.predicate:
            return self.codec.read(r) if self.predicate(r) else None
        else:
            return self.codec.read(r) if r.offset < len(r.view) else None

    def write(self, value: T | None, w: Writer) -> None:
        if self.predicate:
            if self.predicate(w):
                if value is None:
                    raise _optional_missing()
                self.codec.write(value, w)
            elif value is not None:
                raise _optional_extra()
        elif value is not None:
            self.codec.write(value, w)


@dataclasses.dataclass(slots=True, frozen=True)
class _RefTruthy:
    "`When(ref=...)`: the named field is truthy"

    ref: str

    def __call__(self, ctx: Reader | Writer) -> bool:
        try:
            return bool(ctx.data[self.ref])
        except KeyError:
            raise BytesOperationError(
                f"When(ref={self.ref!r}): no earlier field is "
                f"annotated with Named under that name"
            ) from None


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class RefLenCodec(Codec[int]):
    """
    A length that isn't stored but known from the context: an earlier
    `Named` field, or `ref(ctx)`. It's the `len_codec` of the string, bytes
    and collection codecs for `Len(ref=...)`. Reading returns the length,
    writing checks the actual length against it and writes nothing.
    """

    ref: str | t.Callable[[t.Any], int]

    def _get(self, ctx: Reader | Writer) -> int:
        if isinstance(self.ref, str):
            try:
                n = ctx.data[self.ref]
            except KeyError:
                raise BytesOperationError(
                    f"Len(ref={self.ref!r}): no earlier field is "
                    f"annotated with Named under that name"
                ) from None
        else:
            n = self.ref(ctx)
        if not isinstance(n, int) or n < 0:
            raise BytesOperationError(
                f"Len(ref={self.ref!r}) is not a valid length: {n!r}"
            )
        return n

    def read(self, r: Reader) -> int:
        return self._get(r)

    def write(self, value: int, w: Writer) -> None:
        expected = self._get(w)
        if value != expected:
            raise BytesOperationError(
                f"Wrong value length: got {value}, "
                f"Len(ref={self.ref!r}) says {expected}"
            )


@dataclasses.dataclass(slots=True, frozen=True)
class _Check:
    "All the constraints of a field, as a read/write validator"

    constraints: tuple

    def __call__(self, value: t.Any) -> t.Any:
        for c in self.constraints:
            if not c.ok(value):
                raise BytesOperationError(f"{value!r} violates {c}")
        return value


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class ValidatorCodec(Codec[T]):
    codec: Codec
    read_validator: t.Callable[[t.Any], T] | None = None
    write_validator: t.Callable[[T], t.Any] | None = None

    def read(self, r: Reader) -> T:
        value = self.codec.read(r)
        if self.read_validator is not None:
            return self.read_validator(value)
        return value

    def write(self, value: T, w: Writer) -> None:
        if self.write_validator is not None:
            value = self.write_validator(value)
        self.codec.write(value, w)


class _EnumMap(dict):
    "dict that raises BytesOperationError on a missing key"

    __slots__ = ("name",)

    def __init__(self, name: str, items: t.Iterable) -> None:
        super().__init__(items)
        self.name = name

    def __missing__(self, key: t.Any) -> t.Any:
        raise BytesOperationError(f"{key!r} is not a valid {self.name}")


def _enum_maps(cls: type[enum.Enum]) -> tuple[_EnumMap, _EnumMap] | None:
    members = list(cls.__members__.values())
    try:
        return (
            _EnumMap(cls.__name__, ((m.value, m) for m in members)),
            _EnumMap(cls.__name__, ((m, m.value) for m in members)),
        )
    except TypeError:  # unhashable values
        return None


@dataclasses.dataclass(slots=True, frozen=True)
class EnumCodec(Codec[EnumT]):
    codec: Codec
    cls: t.Any
    _maps: tuple[_EnumMap, _EnumMap] | None = dataclasses.field(
        init=False, repr=False, compare=False, default=None
    )

    def __post_init__(self) -> None:
        # Flags have composite values that aren't members: use the slow path
        if not issubclass(self.cls, enum.Flag):
            object.__setattr__(self, "_maps", _enum_maps(self.cls))

    def read(self, r: Reader) -> EnumT:
        value = self.codec.read(r)
        if self._maps is None:
            return self.cls(value)
        return self._maps[0][value]

    def write(self, value: EnumT, w: Writer) -> None:
        if self._maps is None:
            return self.codec.write(value.value, w)
        return self.codec.write(self._maps[1][value], w)


def _literal_error(literals: t.Iterable, value: t.Any) -> BytesOperationError:
    return BytesOperationError(
        f"typing.Literal{list(literals)} doesn't contain {value!r}"
    )


def _literal_prefail(
    literals: t.Iterable, view: memoryview, start: int, size: int
) -> BytesOperationError:
    raw = bytes(view[start : start + size]).hex()
    return BytesOperationError(
        f"typing.Literal{list(literals)} doesn't contain bytes 0x{raw}"
    )


@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class LiteralCodec(Codec[T]):
    codec: Codec
    literals: t.Iterable[T]

    def __post_init__(self) -> None:
        object.__setattr__(self, "literals", frozenset(self.literals))

    def read(self, r: Reader) -> T:
        value = self.codec.read(r)
        if value in self.literals:
            return value
        raise _literal_error(self.literals, value)

    def write(self, value: T, w: Writer) -> None:
        if value not in self.literals:
            raise _literal_error(self.literals, value)
        return self.codec.write(value, w)


@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class NamedCodec(Codec[T]):
    codec: Codec[T]
    key: str

    def read(self, r: Reader) -> T:
        value = self.codec.read(r)
        r.data[self.key] = value
        return value

    def write(self, value: T | None, w: Writer) -> None:
        self.codec.write(value, w)
        w.data[self.key] = value


# ---------------------------------------------------------------------------
# Compiler: fixed-size specs
#
# A "spec" describes a value that has a fixed binary size and can be mapped to
# one or more `struct` slots. Consecutive specs with a compatible byte order
# are merged into one struct segment; the generated code reads/writes the
# whole segment with a single struct call.
# ---------------------------------------------------------------------------


class _Env:
    "Names that the generated code takes as default arguments"

    def __init__(self) -> None:
        self.ns: dict[str, t.Any] = {}
        self._n = 0

    def tmp(self, prefix: str = "t") -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def bind(self, prefix: str, obj: t.Any) -> str:
        name = "_" + self.tmp(prefix)
        self.ns[name] = obj
        return name

    @property
    def defaults(self) -> str:
        return "".join(f", {n}={n}" for n in self.ns)


class _Slots:
    "Hands out struct slot references of one unpacked segment tuple"

    __slots__ = ("var", "idx")

    def __init__(self, var: str, idx: int = 0) -> None:
        self.var = var
        self.idx = idx

    def one(self) -> str:
        rv = f"{self.var}[{self.idx}]"
        self.idx += 1
        return rv

    def many(self, n: int) -> str:
        rv = f"{self.var}[{self.idx}:{self.idx + n}]"
        self.idx += n
        return rv


class _Spec:
    order: str | None  # struct byte order char, None = order-neutral
    body: str  # struct format without the byte order char
    nslots: int
    size: int

    def read(self, sl: _Slots, env: _Env, out: list[str]) -> str:
        raise NotImplementedError

    def write(self, x: str, env: _Env, out: list[str]) -> list[str]:
        raise NotImplementedError

    def prechecks(self, base: int) -> list[tuple[int, int, frozenset, t.Any]]:
        return []

    def packed(self, value: t.Any) -> bytes:
        raise NotImplementedError


_STRUCT_BODY = re.compile(r"(\d*)([bBhHiIlLqQefd?cs])")
_NEUTRAL_CHARS = frozenset("bB?cs")
_INT_CHARS = frozenset("bBhHiIlLqQ")


def _parse_struct_format(fmt: str) -> tuple[str | None, str] | None:
    "Returns (order, body) or None if the format can't be compiled"
    if fmt and fmt[0] in "<>=!@":
        prefix, body = fmt[0], fmt[1:]
    else:
        prefix, body = "@", fmt
    m = _STRUCT_BODY.fullmatch(body)
    if m is None:
        return None
    count, char = m.groups()
    if char != "s" and count not in ("", "1"):
        return None
    if char in _NEUTRAL_CHARS:
        return None, body
    if prefix == "@":  # native size/alignment: not compilable
        return None
    return ("<" if prefix == "<" else "=" if prefix == "=" else ">"), body


class _StructSpec(_Spec):
    def __init__(self, codec: StructCodec, order: str | None, body: str):
        self.codec = codec
        self.order = order
        self.body = body
        self.nslots = 1
        self.size = codec.size
        self.is_int = body[-1] in _INT_CHARS

    def read(self, sl: _Slots, env: _Env, out: list[str]) -> str:
        return sl.one()

    def write(self, x: str, env: _Env, out: list[str]) -> list[str]:
        return [x]

    def packed(self, value: t.Any) -> bytes:
        if not self.is_int:
            raise NotImplementedError
        return self.codec.pack(value)


_INT_CHAR = {1: "B", 2: "H", 4: "I", 8: "Q"}


class _IntSpec(_Spec):
    def __init__(self, codec: IntCodec) -> None:
        self.codec = codec
        big = codec.byteorder == BE
        length = codec.length
        signed = codec.signed
        self.size = length
        self.order = None if length == 1 else (">" if big else "<")
        self.shift = 0
        if length in _INT_CHAR:
            ch = _INT_CHAR[length]
            self.body = ch.lower() if signed else ch
            self.nslots = 1
        else:
            # split into a high part (carries the sign) and a low part
            if length == 3:
                hi, lo, self.shift = "B", "H", 16
            else:
                hi, lo, self.shift = "H", "I", 32
            hi = hi.lower() if signed else hi
            self.body = hi + lo if big else lo + hi
            self.nslots = 2
            self.big = big
            self.mask = (1 << self.shift) - 1

    def read(self, sl: _Slots, env: _Env, out: list[str]) -> str:
        if self.nslots == 1:
            return sl.one()
        a, b = sl.one(), sl.one()
        hi, lo = (a, b) if self.big else (b, a)
        return f"(({hi} << {self.shift}) | {lo})"

    def write(self, x: str, env: _Env, out: list[str]) -> list[str]:
        if self.nslots == 1:
            return [x]
        hi, lo = f"{x} >> {self.shift}", f"{x} & {hex(self.mask)}"
        return [hi, lo] if self.big else [lo, hi]

    def packed(self, value: t.Any) -> bytes:
        c = self.codec
        return value.to_bytes(c.length, c.byteorder, signed=c.signed)


class _StrSpec(_Spec):
    order = None
    nslots = 1

    def __init__(self, length: int) -> None:
        self.length = length
        self.size = length
        self.body = f"{length}s"

    def read(self, sl: _Slots, env: _Env, out: list[str]) -> str:
        return f"{sl.one()}.decode()"

    def write(self, x: str, env: _Env, out: list[str]) -> list[str]:
        tmp = env.tmp("e")
        err = env.bind("Err", BytesOperationError)
        out.append(f"{tmp} = {x}.encode()")
        out.append(
            f"if len({tmp}) != {self.length}: raise {err}"
            f'(f"Wrong value length: got {{len({tmp})}}, '
            f'expected {self.length}")'
        )
        return [tmp]


class _BytesSpec(_Spec):
    order = None
    nslots = 1

    def __init__(self, length: int) -> None:
        self.length = length
        self.size = length
        self.body = f"{length}s"

    def read(self, sl: _Slots, env: _Env, out: list[str]) -> str:
        return sl.one()

    def write(self, x: str, env: _Env, out: list[str]) -> list[str]:
        err = env.bind("Err", BytesOperationError)
        out.append(
            f"if len({x}) != {self.length}: raise {err}"
            f'(f"Wrong value length: got {{len({x})}}, '
            f'expected {self.length}")'
        )
        return [x]


def _leaf_item(codec: Codec) -> tuple[str | None, str] | None:
    "(order, char) for codecs that are a single plain struct value"
    spec = _to_spec(codec)
    if (
        isinstance(spec, (_StructSpec, _IntSpec))
        and spec.nslots == 1
        and len(spec.body) == 1
        and spec.body not in "s"
    ):
        return spec.order, spec.body
    return None


class _ArraySpec(_Spec):
    def __init__(self, cls: t.Any, length: int, order: str | None, ch: str):
        self.cls = cls
        self.length = length
        self.order = order
        self.body = f"{length}{ch}"
        self.nslots = length
        self.size = s.calcsize(f">{self.body}")

    def read(self, sl: _Slots, env: _Env, out: list[str]) -> str:
        m = sl.many(self.length)
        cls = self.cls
        if cls is tuple:
            return m
        if cls in (list, set, frozenset):
            return f"{cls.__name__}({m})"
        return f"{env.bind('cls', cls)}({m})"

    def write(self, x: str, env: _Env, out: list[str]) -> list[str]:
        err = env.bind("Err", BytesOperationError)
        out.append(
            f"if len({x}) != {self.length}: raise {err}"
            f'(f"Wrong collection size, got {{len({x})}}, '
            f'expected {self.length}")'
        )
        return [f"*{x}"]


class _LiteralSpec(_Spec):
    def __init__(self, inner: _Spec, literals: frozenset) -> None:
        self.inner = inner
        self.literals = literals
        self.order = inner.order
        self.body = inner.body
        self.nslots = inner.nslots
        self.size = inner.size
        try:
            self.raw: frozenset | None = frozenset(
                inner.packed(v) for v in literals
            )
        except Exception:
            self.raw = None

    def prechecks(self, base: int) -> list[tuple[int, int, frozenset, t.Any]]:
        if self.raw is None:
            return []
        return [(base, self.size, self.raw, self.literals)]

    def read(self, sl: _Slots, env: _Env, out: list[str]) -> str:
        expr = self.inner.read(sl, env, out)
        if self.raw is not None:  # already checked on the raw bytes
            return expr
        tmp = env.tmp("l")
        lits = env.bind("L", self.literals)
        err = env.bind("LE", _literal_error)
        out.append(f"{tmp} = {expr}")
        out.append(f"if {tmp} not in {lits}: raise {err}({lits}, {tmp})")
        return tmp

    def write(self, x: str, env: _Env, out: list[str]) -> list[str]:
        lits = env.bind("L", self.literals)
        err = env.bind("LE", _literal_error)
        out.append(f"if {x} not in {lits}: raise {err}({lits}, {x})")
        return self.inner.write(x, env, out)


class _EnumSpec(_Spec):
    def __init__(self, inner: _Spec, cls: t.Any, maps: tuple) -> None:
        self.inner = inner
        self.cls = cls
        self.maps = maps
        self.order = inner.order
        self.body = inner.body
        self.nslots = inner.nslots
        self.size = inner.size

    def read(self, sl: _Slots, env: _Env, out: list[str]) -> str:
        mapping = env.bind("E", self.maps[0])
        return f"{mapping}[{self.inner.read(sl, env, out)}]"

    def write(self, x: str, env: _Env, out: list[str]) -> list[str]:
        mapping = env.bind("EV", self.maps[1])
        tmp = env.tmp("v")
        out.append(f"{tmp} = {mapping}[{x}]")
        return self.inner.write(tmp, env, out)


class _ValidatorSpec(_Spec):
    def __init__(self, inner: _Spec, codec: ValidatorCodec) -> None:
        self.inner = inner
        self.codec = codec
        self.order = inner.order
        self.body = inner.body
        self.nslots = inner.nslots
        self.size = inner.size

    def read(self, sl: _Slots, env: _Env, out: list[str]) -> str:
        expr = self.inner.read(sl, env, out)
        if self.codec.read_validator is None:
            return expr
        return f"{env.bind('rv', self.codec.read_validator)}({expr})"

    def write(self, x: str, env: _Env, out: list[str]) -> list[str]:
        if self.codec.write_validator is not None:
            tmp = env.tmp("w")
            out.append(
                f"{tmp} = {env.bind('wv', self.codec.write_validator)}({x})"
            )
            x = tmp
        return self.inner.write(x, env, out)


class _GroupSpec(_Spec):
    "A nested class whose fields are all fixed: flattened into the parent"

    def __init__(
        self,
        info: "_CtorInfo",
        names: tuple[str, ...],
        children: list[_Spec],
        order: str | None,
    ) -> None:
        self.info = info
        self.names = names
        self.children = children
        self.order = order
        self.body = "".join(c.body for c in children)
        self.nslots = sum(c.nslots for c in children)
        self.size = sum(c.size for c in children)

    def prechecks(self, base: int) -> list[tuple[int, int, frozenset, t.Any]]:
        rv = []
        for child in self.children:
            rv += child.prechecks(base)
            base += child.size
        return rv

    def read(self, sl: _Slots, env: _Env, out: list[str]) -> str:
        exprs = [c.read(sl, env, out) for c in self.children]
        return self.info.expr(self.names, exprs, env)

    def write(self, x: str, env: _Env, out: list[str]) -> list[str]:
        if self.info.kind == "anon":
            err = env.bind("Err", _tuple_size_error)
            n = len(self.names)
            out.append(f"if len({x}) != {n}: raise {err}(len({x}), {n})")
        getter = env.bind("get", self.info.getter(self.names))
        tmps = [env.tmp("g") for _ in self.names]
        target = ", ".join(tmps)
        if len(tmps) == 1:
            out.append(f"{target}, = ({getter}({x}),)")
        else:
            out.append(f"{target} = {getter}({x})")
        args: list[str] = []
        for child, tmp in zip(self.children, tmps, strict=True):
            args += child.write(tmp, env, out)
        return args


def _to_spec(codec: t.Any) -> _Spec | None:
    "Map a codec to a fixed-size spec, or None if it can't be compiled"
    typ = type(codec)
    if typ is StructCodec:
        parsed = _parse_struct_format(codec.format)
        if parsed is None:
            return None
        return _StructSpec(codec, *parsed)
    if typ is IntCodec:
        if codec.length in (1, 2, 3, 4, 6, 8):
            return _IntSpec(codec)
        return None
    if typ is StringCodec:
        return None if codec.length is None else _StrSpec(codec.length)
    if typ is BytesCodec:
        return None if codec.length is None else _BytesSpec(codec.length)
    if typ is CollectionCodec:
        if not codec.length:
            return None
        leaf = _leaf_item(codec.item_codec)
        if leaf is None:
            return None
        return _ArraySpec(codec.cls, codec.length, *leaf)
    if typ is LiteralCodec:
        inner = _to_spec(codec.codec)
        if inner is None or inner.nslots != 1:
            return None
        return _LiteralSpec(inner, codec.literals)
    if typ is EnumCodec:
        inner = _to_spec(codec.codec)
        if inner is None or inner.nslots != 1 or codec._maps is None:
            return None
        return _EnumSpec(inner, codec.cls, codec._maps)
    if typ is ValidatorCodec:
        inner = _to_spec(codec.codec)
        return None if inner is None else _ValidatorSpec(inner, codec)
    if typ is ClassCodec:
        return codec._as_group()
    return None


# ---------------------------------------------------------------------------
# Compiler: segments and code generation
# ---------------------------------------------------------------------------


class _CtorInfo:
    "How to construct an instance of a class from positional field values"

    def __init__(self, hint: t.Any, names: tuple[str, ...]) -> None:
        self.cls = t.get_origin(hint) or hint
        self.names = names
        cls = self.cls
        self.kind = "kw"
        if cls is tuple:  # an anonymous tuple[X, Y]: fields are the items
            self.kind = "anon"
        elif (
            isinstance(cls, type)
            and issubclass(cls, tuple)
            and hasattr(cls, "_fields")
        ):
            if cls.__bases__ == (tuple,) and tuple(cls._fields) == names:
                self.kind = "tuple"
            elif tuple(cls._fields) == names:
                self.kind = "pos"
        elif dataclasses.is_dataclass(cls):
            fields = dataclasses.fields(cls)
            if all(f.init and not f.kw_only for f in fields) and names == tuple(
                f.name for f in fields
            ):
                self.kind = "pos"

    def getter(self, names: t.Sequence[str]) -> t.Callable[[t.Any], t.Any]:
        "Returns the field values of an instance (one value if one field)"
        if self.kind == "anon":
            return operator.itemgetter(*range(len(names)))
        return operator.attrgetter(*names)

    def make(self, values: t.Sequence[t.Any]) -> t.Any:
        if self.kind == "anon":
            return tuple(values)
        if self.kind == "pos":
            return self.cls(*values)
        if self.kind == "tuple":
            return tuple.__new__(self.cls, values)
        return self.cls(**dict(zip(self.names, values, strict=True)))

    def expr(self, names: t.Sequence[str], exprs: list[str], env: _Env) -> str:
        if self.kind == "anon":
            return f"({''.join(e + ', ' for e in exprs)})"
        cls = env.bind("cls", self.cls)
        if self.kind == "pos":
            return f"{cls}({', '.join(exprs)})"
        if self.kind == "tuple":
            new = env.bind("new", tuple.__new__)
            return f"{new}({cls}, ({''.join(e + ', ' for e in exprs)}))"
        args = ", ".join(f"{n}={e}" for n, e in zip(names, exprs, strict=True))
        return f"{cls}({args})"


class _Entry:
    "One class field as seen by the compiler"

    __slots__ = ("name", "codec", "spec", "kind", "key", "var")

    def __init__(self, idx: int, name: str, codec: Codec) -> None:
        self.name = name
        self.var = f"f{idx}"
        self.key: str | None = None
        while type(codec) is NamedCodec:
            self.key = codec.key
            codec = codec.codec
        self.codec = codec
        self.spec: _Spec | None = None
        if type(codec) is OptionalCodec and (spec := _to_spec(codec.codec)):
            self.kind = "opt"
            self.spec = spec
        elif spec := _to_spec(codec):
            self.kind = "fixed"
            self.spec = spec
        else:
            self.kind = "dyn"


def _fmt(order: str | None, body: str) -> str:
    return (order or ">") + body


class StructSegment:
    "Consecutive fixed-size fields packed with a single struct"

    __slots__ = ("order", "body", "size", "entries")

    def __init__(self) -> None:
        self.order: str | None = None
        self.body = ""
        self.size = 0
        self.entries: list[_Entry] = []

    @property
    def format(self) -> str:
        return _fmt(self.order, self.body)

    def accepts(self, spec: _Spec) -> bool:
        return (
            spec.order is None or self.order is None or spec.order == self.order
        )

    def add(self, entry: _Entry) -> None:
        spec = entry.spec
        assert spec is not None
        self.order = self.order or spec.order
        self.body += spec.body
        self.size += spec.size
        self.entries.append(entry)

    def __repr__(self) -> str:
        return f"StructSegment(format={self.format!r})"


class DynamicSegment:
    "A field that can't be compiled: handled by calling its codec"

    __slots__ = ("entry",)

    def __init__(self, entry: _Entry) -> None:
        self.entry = entry

    @property
    def codec(self) -> Codec:
        return self.entry.codec

    def __repr__(self) -> str:
        return f"DynamicSegment(codec={type(self.entry.codec).__name__})"


class OptionalSegment:
    "An optional fixed-size field: presence is decided at runtime"

    __slots__ = ("entry",)

    def __init__(self, entry: _Entry) -> None:
        self.entry = entry

    @property
    def format(self) -> str:
        spec = self.entry.spec
        assert spec is not None
        return _fmt(spec.order, spec.body)

    def __repr__(self) -> str:
        return f"OptionalSegment(format={self.format!r})"


Segment = t.Union[StructSegment, DynamicSegment, OptionalSegment]  # noqa: UP007


def _build_segments(entries: t.Iterable[_Entry]) -> list[Segment]:
    segments: list[Segment] = []
    current: StructSegment | None = None
    for entry in entries:
        if entry.kind == "fixed":
            assert entry.spec is not None
            if current is None or not current.accepts(entry.spec):
                current = StructSegment()
                segments.append(current)
            current.add(entry)
            continue
        current = None
        if entry.kind == "opt":
            segments.append(OptionalSegment(entry))
        else:
            segments.append(DynamicSegment(entry))
    return segments


def _indent(lines: list[str], n: int = 1) -> list[str]:
    return ["    " * n + line for line in lines]


def _emit_prechecks(
    lines: list[str], env: _Env, entries: t.Iterable[_Entry]
) -> None:
    "Check literals on the raw bytes before unpacking anything"
    base = 0
    for entry in entries:
        spec = entry.spec
        assert spec is not None
        for k, size, raw, literals in spec.prechecks(base):
            raws = env.bind("P", raw)
            lits = env.bind("L", literals)
            fail = env.bind("PF", _literal_prefail)
            if size == 1:
                cond = f"view[off + {k}] not in {raws}"
                raws_set = frozenset(b[0] for b in raw)
                env.ns[raws] = raws_set
            else:
                cond = f"bytes(view[off + {k}:off + {k + size}]) not in {raws}"
            lines.append(
                f"if {cond}: raise {fail}({lits}, view, off + {k}, {size})"
            )
        base += spec.size


def _gen_read(
    info: _CtorInfo, entries: list[_Entry], segments: list[Segment], env: _Env
) -> str:
    lines = ["    view = r.view", "    off = r.offset"]

    def set_named(entry: _Entry) -> list[str]:
        return [f"r.data[{entry.key!r}] = {entry.var}"] if entry.key else []

    for seg in segments:
        if isinstance(seg, StructSegment):
            _emit_prechecks(lines_ := [], env, seg.entries)
            lines += _indent(lines_)
            unpack = env.bind("u", _struct(seg.format).unpack_from)
            var = env.tmp("s")
            lines.append(f"    {var} = {unpack}(view, off)")
            lines.append(f"    off += {seg.size}")
            sl = _Slots(var)
            for entry in seg.entries:
                out: list[str] = []
                assert entry.spec is not None
                expr = entry.spec.read(sl, env, out)
                lines += _indent(out)
                lines.append(f"    {entry.var} = {expr}")
                lines += _indent(set_named(entry))
        elif isinstance(seg, OptionalSegment):
            entry = seg.entry
            spec = entry.spec
            assert spec is not None
            codec = entry.codec
            assert isinstance(codec, OptionalCodec)
            body: list[str] = []
            if codec.predicate is not None:
                pred = env.bind("pred", codec.predicate)
                lines.append("    r.offset = off")
                cond = f"{pred}(r)"
            else:
                cond = "off < len(view)"
            _emit_prechecks(body, env, [entry])
            unpack = env.bind("u", _struct(seg.format).unpack_from)
            var = env.tmp("s")
            body.append(f"{var} = {unpack}(view, off)")
            body.append(f"off += {spec.size}")
            out = []
            expr = spec.read(_Slots(var), env, out)
            body += out
            body.append(f"{entry.var} = {expr}")
            lines.append(f"    if {cond}:")
            lines += _indent(body, 2)
            lines.append("    else:")
            lines.append(f"        {entry.var} = None")
            lines += _indent(set_named(entry))
        else:
            entry = seg.entry
            read = env.bind("c", entry.codec.read)
            lines.append("    r.offset = off")
            lines.append(f"    {entry.var} = {read}(r)")
            lines.append("    off = r.offset")
            lines += _indent(set_named(entry))

    lines.append("    r.offset = off")
    result = info.expr(info.names, [e.var for e in entries], env)
    lines.append(f"    return {result}")
    return f"def read(r{env.defaults}):\n" + "\n".join(lines) + "\n"


def _gen_write(
    info: _CtorInfo, entries: list[_Entry], segments: list[Segment], env: _Env
) -> str:
    lines: list[str] = []
    if info.kind == "anon":
        err = env.bind("Err", _tuple_size_error)
        n = len(info.names)
        lines.append(f"    if len(value) != {n}: raise {err}(len(value), {n})")
    if entries:
        names = info.names
        getter = env.bind("get", info.getter(names))
        targets = ", ".join(e.var for e in entries)
        lines.append(f"    {targets} = {getter}(value)")
    lines.append("    buf = w.buffer")

    def set_named(entry: _Entry) -> list[str]:
        return [f"w.data[{entry.key!r}] = {entry.var}"] if entry.key else []

    for seg in segments:
        if isinstance(seg, StructSegment):
            args: list[str] = []
            for entry in seg.entries:
                out: list[str] = []
                assert entry.spec is not None
                args += entry.spec.write(entry.var, env, out)
                lines += _indent(out)
            pack = env.bind("p", _struct(seg.format).pack)
            lines.append(f"    buf += {pack}({', '.join(args)})")
            for entry in seg.entries:
                lines += _indent(set_named(entry))
        elif isinstance(seg, OptionalSegment):
            entry = seg.entry
            spec = entry.spec
            assert spec is not None
            codec = entry.codec
            assert isinstance(codec, OptionalCodec)
            out = []
            args = spec.write(entry.var, env, out)
            pack = env.bind("p", _struct(seg.format).pack)
            body = out + [f"buf += {pack}({', '.join(args)})"]
            if codec.predicate is not None:
                pred = env.bind("pred", codec.predicate)
                missing = env.bind("miss", _optional_missing)
                extra = env.bind("extra", _optional_extra)
                lines.append(f"    if {pred}(w):")
                lines.append(
                    f"        if {entry.var} is None: "
                    f"raise {missing}({entry.name!r})"
                )
                lines += _indent(body, 2)
                lines.append(f"    elif {entry.var} is not None:")
                lines.append(f"        raise {extra}({entry.name!r})")
            else:
                lines.append(f"    if {entry.var} is not None:")
                lines += _indent(body, 2)
            lines += _indent(set_named(entry))
        else:
            entry = seg.entry
            write = env.bind("c", entry.codec.write)
            lines.append(f"    {write}({entry.var}, w)")
            lines += _indent(set_named(entry))

    return f"def write(value, w{env.defaults}):\n" + "\n".join(lines) + "\n"


_SOURCE_COUNTER = 0


def _exec_source(source: str, name: str, ns: dict[str, t.Any]) -> t.Callable:
    global _SOURCE_COUNTER
    _SOURCE_COUNTER += 1
    filename = f"<rombob:{name}:{_SOURCE_COUNTER}>"
    linecache.cache[filename] = (
        len(source),
        None,
        source.splitlines(keepends=True),
        filename,
    )
    exec(compile(source, filename, "exec"), ns)  # noqa: S102
    return ns[source.split("(", 1)[0].removeprefix("def ")]


def _display_name(hint: t.Any) -> str:
    return getattr(t.get_origin(hint) or hint, "__name__", repr(hint))


def _compile_class(
    hint: t.Any,
    info: _CtorInfo,
    entries: list[_Entry],
    segments: list[Segment],
) -> tuple[t.Callable, t.Callable, str]:
    name = _display_name(hint)
    env = _Env()
    read_src = _gen_read(info, entries, segments, env)
    read = _exec_source(read_src, f"{name}.read", env.ns)
    env = _Env()
    write_src = _gen_write(info, entries, segments, env)
    write = _exec_source(write_src, f"{name}.write", env.ns)
    return read, write, read_src + "\n" + write_src


def _plain_funcs(
    info: _CtorInfo, fields: tuple[tuple[str, Codec], ...]
) -> tuple[t.Callable, t.Callable]:
    "Non-compiled read/write: just loop over the field codecs"
    reads = tuple(c.read for _, c in fields)
    writes = tuple(c.write for _, c in fields)
    make = info.make
    names = tuple(n for n, _ in fields)
    getter = info.getter(names) if names else None
    single = len(names) == 1

    def read(r: Reader) -> t.Any:
        return make([f(r) for f in reads])

    anon = info.kind == "anon"

    def write(value: t.Any, w: Writer) -> None:
        if getter is None:
            return
        if anon and len(value) != len(names):
            raise _tuple_size_error(len(value), len(names))
        values = (getter(value),) if single else getter(value)
        for f, v in zip(writes, values, strict=True):
            f(v, w)

    return read, write


@dataclasses.dataclass(slots=True, frozen=True, kw_only=True, repr=False)
class ClassCodec(Codec[T]):
    cls: t.Any
    fields: t.Iterable[tuple[str, Codec]] = ()
    compiled: bool = True
    info: _CtorInfo = dataclasses.field(init=False, compare=False)
    entries: tuple[_Entry, ...] = dataclasses.field(init=False, compare=False)
    segments: tuple[Segment, ...] = dataclasses.field(init=False, compare=False)
    source: str | None = dataclasses.field(
        init=False, compare=False, default=None
    )
    read: t.Callable[[Reader], T] = dataclasses.field(init=False, compare=False)
    write: t.Callable[[T, Writer], None] = dataclasses.field(
        init=False, compare=False
    )

    def __post_init__(self) -> None:
        fields = tuple((n, c) for n, c in self.fields)
        set_ = functools.partial(object.__setattr__, self)
        set_("fields", fields)
        info = _CtorInfo(self.cls, tuple(n for n, _ in fields))
        entries = [_Entry(i, n, c) for i, (n, c) in enumerate(fields)]
        segments = _build_segments(entries)
        set_("info", info)
        set_("entries", tuple(entries))
        set_("segments", tuple(segments))
        if self.compiled:
            read, write, source = _compile_class(
                self.cls, info, entries, segments
            )
            set_("source", source)
        else:
            read, write = _plain_funcs(info, fields)
        set_("read", read)
        set_("write", write)

    def __repr__(self) -> str:
        name = _display_name(self.cls)
        if self.compiled:
            return f"ClassCodec(cls={name}, segments={list(self.segments)!r})"
        names = [n for n, _ in self.fields]
        return f"ClassCodec(cls={name}, fields={names!r})"

    def field_offset(self, name: str) -> int | None:
        "Static byte offset of the field, None if it isn't static"
        offset = 0
        for entry in self.entries:
            if entry.name == name:
                return offset if entry.kind == "fixed" else None
            if entry.kind != "fixed":
                return None
            assert entry.spec is not None
            offset += entry.spec.size
        return None

    def _as_group(self) -> _GroupSpec | None:
        if not self.compiled or not self.entries:
            return None
        children: list[_Spec] = []
        order: str | None = None
        for entry in self.entries:
            if entry.kind != "fixed" or entry.key is not None:
                return None
            assert entry.spec is not None
            spec = entry.spec
            if spec.order is not None:
                if order is not None and spec.order != order:
                    return None
                order = spec.order
            children.append(spec)
        return _GroupSpec(
            self.info, tuple(n for n, _ in self.fields), children, order
        )


# ---------------------------------------------------------------------------
# Public type aliases
# ---------------------------------------------------------------------------

I8_L = t.Annotated[int, StructCodec("<b")]
I8_B = t.Annotated[int, StructCodec(">b")]
U8_L = t.Annotated[int, StructCodec("<B")]
U8_B = t.Annotated[int, StructCodec(">B")]
I16_L = t.Annotated[int, StructCodec("<h")]
I16_B = t.Annotated[int, StructCodec(">h")]
U16_L = t.Annotated[int, StructCodec("<H")]
U16_B = t.Annotated[int, StructCodec(">H")]
I24_L = t.Annotated[int, IntCodec(length=3, byteorder=LE, signed=True)]
I24_B = t.Annotated[int, IntCodec(length=3, byteorder=BE, signed=True)]
U24_L = t.Annotated[int, IntCodec(length=3, byteorder=LE, signed=False)]
U24_B = t.Annotated[int, IntCodec(length=3, byteorder=BE, signed=False)]
I32_L = t.Annotated[int, StructCodec("<i")]
I32_B = t.Annotated[int, StructCodec(">i")]
U32_L = t.Annotated[int, StructCodec("<I")]
U32_B = t.Annotated[int, StructCodec(">I")]
I48_L = t.Annotated[int, IntCodec(length=6, byteorder=LE, signed=True)]
I48_B = t.Annotated[int, IntCodec(length=6, byteorder=BE, signed=True)]
U48_L = t.Annotated[int, IntCodec(length=6, byteorder=LE, signed=False)]
U48_B = t.Annotated[int, IntCodec(length=6, byteorder=BE, signed=False)]
I64_L = t.Annotated[int, StructCodec("<q")]
I64_B = t.Annotated[int, StructCodec(">q")]
U64_L = t.Annotated[int, StructCodec("<Q")]
U64_B = t.Annotated[int, StructCodec(">Q")]
F16_L = t.Annotated[float, StructCodec("<e")]
F16_B = t.Annotated[float, StructCodec(">e")]
F32_L = t.Annotated[float, StructCodec("<f")]
F32_B = t.Annotated[float, StructCodec(">f")]
F64_L = t.Annotated[float, StructCodec("<d")]
F64_B = t.Annotated[float, StructCodec(">d")]
IVInt = t.Annotated[int, VarIntCodec(signed=True)]
UVInt = t.Annotated[int, VarIntCodec(signed=False)]
Raw = t.Annotated[bytes, RawCodec()]


_FALLBACKS: dict[type, Codec] = {
    bool: StructCodec("?"),
    str: StringCodec(len_codec=StructCodec(">H")),
    bytes: BytesCodec(len_codec=StructCodec(">H")),
    int: StructCodec(">q"),
    float: StructCodec(">d"),
}


ParserContext = dict[t.TypeVar, t.Any]
Args = t.Iterable[t.Any]

_CODECS: dict[t.Any, Codec] = {}
_PLAIN_CODECS: dict[t.Any, Codec] = {}


def get_codec(hint: type[T], *, compile: bool = True) -> Codec[T]:
    """
    Build (and memoize per hint) the codec for a type hint.

    :param compile: set to False to get the plain, non-compiled codecs
        (field by field). Mostly useful for tests and debugging.
    """
    cache = _CODECS if compile else _PLAIN_CODECS
    try:
        return cache[hint]
    except KeyError:
        pass
    except TypeError:  # unhashable hint, e.g. Annotated[..., {"a": 1}]
        return _build_codec(hint, compile)
    codec = cache[hint] = _build_codec(hint, compile)
    return codec


def _build_codec(hint: t.Any, compile: bool) -> Codec:
    global _COMPILE
    previous, _COMPILE = _COMPILE, compile
    try:
        return _get_codec_inner(hint, context={})
    finally:
        _COMPILE = previous


def _resolve_base_codec(hint: t.Any) -> Codec:
    if hint in _FALLBACKS:
        return _FALLBACKS[hint]
    if isinstance(hint, type) and issubclass(hint, enum.Enum):
        for base in hint.__mro__:
            if base in _FALLBACKS:
                return _FALLBACKS[base]
    # Literal primitives
    if type(hint) in _FALLBACKS:
        return _FALLBACKS[type(hint)]
    raise BytesOperationError(f"No fallback codec for {hint}")


# ---------------------------------------------------------------------------
# Metadata of a hint
#
# `Annotated[...]` layers are peeled off first and their metadata is merged
# into one `_Meta`; only then is the base type dispatched. That keeps the
# annotations independent of the shape of the type (`X | None`, aliases of
# `Annotated`, type variables).
# ---------------------------------------------------------------------------


@dataclasses.dataclass(slots=True)
class _Meta:
    codec: Codec | None = None
    length: Len | None = None
    prefix: Prefix | None = None
    checks: list = dataclasses.field(default_factory=list)
    when: When | None = None
    named: bool = False
    skip: bool = False

    def copy(self) -> "_Meta":
        return dataclasses.replace(self, checks=list(self.checks))

    def for_inner(self) -> "_Meta":
        "What an `X | None` hands down to X: all but the optional's own"
        rv = self.copy()
        rv.when = None
        rv.named = False
        return rv


def _set_once(meta: _Meta, attr: str, value: t.Any) -> None:
    if getattr(meta, attr) is not None:
        raise BytesOperationError(
            f"{type(value).__name__} is given more than once"
        )
    setattr(meta, attr, value)


def _collect(items: t.Iterable[t.Any], meta: _Meta, context: dict) -> None:
    for item in items:
        if isinstance(item, Codec):
            meta.codec = item  # the last one wins, so aliases can be refined
        elif isinstance(item, Len):
            _set_once(meta, "length", item)
        elif isinstance(item, Prefix):
            _set_once(meta, "prefix", item)
        elif isinstance(item, CONSTRAINTS):
            meta.checks.append(item)
        elif isinstance(item, When):
            _set_once(meta, "when", item)
        elif item is NAMED:
            meta.named = True
        elif item is SKIP:
            meta.skip = True
        elif t.get_origin(item) is t.Annotated:
            # an alias such as U16_L used as the metadata
            try:
                meta.codec = _get_codec_inner(item, context)
            except BytesOperationError:
                pass
        # anything else belongs to someone else, ignore it


def _is_skipped(hint: t.Any) -> bool:
    return t.get_origin(hint) is t.Annotated and SKIP in t.get_args(hint)[1:]


def _len_kwargs(meta: _Meta, context: dict) -> dict[str, t.Any]:
    "Constructor arguments of the str/bytes/collection codecs"
    if meta.length is not None and meta.prefix is not None:
        raise BytesOperationError("Len and Prefix can't be used together")
    if meta.length is not None:
        if meta.length.n is not None:
            return {"length": meta.length.n}
        return {"len_codec": RefLenCodec(ref=meta.length.ref)}
    if meta.prefix is not None:
        codec = meta.prefix.codec
        if not isinstance(codec, Codec):
            codec = _get_codec_inner(codec, context)
        return {"len_codec": codec}
    return {}


def _reject_len(meta: _Meta, hint: t.Any) -> None:
    if meta.length is not None or meta.prefix is not None:
        raise BytesOperationError(f"Len and Prefix don't apply to {hint}")


def _resolve_literal(args: Args, context: ParserContext, meta: _Meta) -> Codec:
    args = tuple(args)
    if meta.codec is not None:
        _reject_len(meta, "a Literal with an explicit codec")
        return LiteralCodec(codec=meta.codec, literals=args)
    kind = type(args[0])
    if kind not in (str, bytes):
        _reject_len(meta, f"Literal of {kind.__name__}")
        return LiteralCodec(
            codec=_get_codec_inner(kind, context), literals=args
        )
    # str/bytes literals know their size, no need to spell it out
    cls = StringCodec if kind is str else BytesCodec
    kwargs = _len_kwargs(meta, context)
    sizes = {
        len(a.encode("utf-8") if kind is str else a)
        for a in args
        if isinstance(a, kind)
    }
    if not kwargs:
        if len(sizes) == 1:
            kwargs = {"length": next(iter(sizes))}
    elif kwargs.get("length") is not None and sizes != {kwargs["length"]}:
        raise BytesOperationError(
            f"Len({kwargs['length']}) doesn't match the Literal {list(args)}"
        )
    return LiteralCodec(codec=cls(**kwargs), literals=args)


def _resolve_enum(actual_hint: t.Any, meta: _Meta) -> EnumCodec:
    _reject_len(meta, actual_hint)
    codec = meta.codec or _resolve_base_codec(actual_hint)
    return EnumCodec(codec=codec, cls=actual_hint)


def _class_codec(
    hint: t.Any,
    actual_hint: t.Any,
    args: Args,
    context: ParserContext,
    get_fields: t.Callable[[ParserContext], dict[str, t.Any]],
) -> ClassCodec:
    cacheable = not context and not args
    cache = _CODECS if _COMPILE else _PLAIN_CODECS
    if cacheable and hint in cache:
        return cache[hint]  # type: ignore[return-value]
    new_context = dict(context)
    if hasattr(actual_hint, "__parameters__") and args:
        new_context.update(zip(actual_hint.__parameters__, args, strict=False))
    fields = {}
    for name, f_hint in get_fields(new_context).items():
        if _is_skipped(f_hint):
            _check_has_default(actual_hint, name)
            continue
        fields[name] = _get_codec_inner(f_hint, new_context, field_name=name)
    codec = ClassCodec(
        cls=hint, fields=tuple(fields.items()), compiled=_COMPILE
    )
    if cacheable:
        cache[hint] = codec
    return codec


def _check_has_default(cls: t.Any, name: str) -> None:
    "A skipped field is never read, so the class must be able to do without"
    if dataclasses.is_dataclass(cls):
        f = dataclasses.fields(cls)
        f = next((x for x in f if x.name == name), None)
        ok = f is not None and (
            not f.init
            or f.default is not dataclasses.MISSING
            or f.default_factory is not dataclasses.MISSING
        )
    else:
        ok = name in getattr(cls, "_field_defaults", {})
    if not ok:
        raise BytesOperationError(
            f"{cls.__name__}.{name} is Skip but has no default value"
        )


def _resolve_class(
    hint: t.Any, actual_hint: t.Any, args: Args, context: ParserContext
) -> ClassCodec:
    return _class_codec(
        hint,
        actual_hint,
        args,
        context,
        lambda _: dict(t.get_type_hints(actual_hint, include_extras=True)),
    )


def _resolve_dataclass(
    hint: t.Any, actual_hint: t.Any, args: Args, context: ParserContext
) -> ClassCodec:
    return _class_codec(
        hint,
        actual_hint,
        args,
        context,
        lambda _: _dataclass_hints(actual_hint),
    )


def _dataclass_hints(cls: t.Any) -> dict[str, t.Any]:
    """
    Field hints of a dataclass with forward references resolved
    (`from __future__ import annotations`, string annotations).
    """
    fields = dataclasses.fields(cls)
    try:
        hints = t.get_type_hints(cls, include_extras=True)
    except NameError as e:
        # e.g. a class defined inside a function referencing a local name
        if any(isinstance(f.type, str) for f in fields):
            raise BytesOperationError(
                f"Cannot resolve forward references of {cls}: {e}"
            ) from e
        return {f.name: f.type for f in fields}
    return {f.name: hints.get(f.name, f.type) for f in fields}


def _resolve_collection(
    hint: t.Any,
    actual_hint: t.Any,
    args: Args,
    context: ParserContext,
    meta: _Meta,
) -> Codec:
    args = tuple(args)
    if actual_hint is tuple and args and Ellipsis not in args:
        # tuple[int, str]: a fixed record of different types
        _reject_len(meta, hint)
        fields = tuple(
            (f"_{i}", _get_codec_inner(a, context)) for i, a in enumerate(args)
        )
        return ClassCodec(cls=hint, fields=fields, compiled=_COMPILE)
    if Ellipsis in args and not (len(args) == 2 and args[1] is Ellipsis):
        raise BytesOperationError(f"Unsupported tuple {hint}")
    if not args:
        raise BytesOperationError(f"The item type of {hint} is not given")
    item_codec = _get_codec_inner(args[0], context)
    return CollectionCodec(
        cls=actual_hint, item_codec=item_codec, **_len_kwargs(meta, context)
    )


def _resolve_optional(
    args: Args, context: ParserContext, meta: _Meta, field_name: str | None
) -> Codec:
    other_args = [a for a in args if a is not type(None)]
    other = (
        other_args[0] if len(other_args) == 1 else t.Union[tuple(other_args)]  # noqa: UP007
    )
    inner = _get_codec_inner(other, context, meta=meta.for_inner())
    predicate: t.Callable | None = None
    if meta.when is not None:
        predicate = meta.when.predicate or _RefTruthy(meta.when.ref)
    codec = OptionalCodec(codec=inner, predicate=predicate)
    # the constraints went down to the inner type: `None` is never checked
    return _finish(codec, _Meta(named=meta.named), field_name)


def _finish(codec: Codec, meta: _Meta, field_name: str | None) -> Codec:
    if meta.checks:
        check = _Check(tuple(meta.checks))
        codec = ValidatorCodec(
            codec=codec, read_validator=check, write_validator=check
        )
    if meta.named and field_name is not None:
        codec = NamedCodec(codec=codec, key=field_name)
    return codec


def _get_codec_inner(
    hint: t.Any,
    context: dict[t.TypeVar, t.Any],
    field_name: str | None = None,
    meta: _Meta | None = None,
) -> Codec:
    meta = _Meta() if meta is None else meta.copy()
    while True:
        if isinstance(hint, t.TypeVar):
            hint = context.get(hint, hint)
        if t.get_origin(hint) is not t.Annotated:
            break
        args = t.get_args(hint)
        _collect(args[1:], meta, context)
        hint = args[0]

    if isinstance(hint, (str, t.ForwardRef)):
        # Class fields are resolved via get_type_hints before reaching here,
        # so this is a bare string hint with no namespace to resolve it in.
        raise BytesOperationError(f"Unresolved forward reference {hint!r}")
    if meta.skip:
        raise BytesOperationError("Skip is only allowed on class fields")

    origin = t.get_origin(hint)
    args = t.get_args(hint)
    actual_hint = origin if origin is not None else hint
    if actual_hint is t.Union or actual_hint is getattr(
        types, "UnionType", object
    ):
        if type(None) not in args:
            raise BytesOperationError(f"Unsupported union {hint}")
        return _resolve_optional(args, context, meta, field_name)
    if meta.when is not None:
        raise BytesOperationError(f"When needs an optional type, got {hint}")

    if actual_hint is t.Literal:
        codec = _resolve_literal(args, context, meta)
    elif isinstance(actual_hint, type) and issubclass(actual_hint, enum.Enum):
        codec = _resolve_enum(actual_hint, meta)
    elif meta.codec is not None:
        _reject_len(meta, f"{hint} with an explicit codec")
        codec = meta.codec
    elif not isinstance(actual_hint, type):
        raise BytesOperationError(f"No fallback codec for {hint}")
    elif issubclass(actual_hint, tuple) and hasattr(actual_hint, "_fields"):
        _reject_len(meta, hint)
        codec = _resolve_class(hint, actual_hint, args, context)
    elif dataclasses.is_dataclass(actual_hint):
        _reject_len(meta, hint)
        codec = _resolve_dataclass(hint, actual_hint, args, context)
    elif issubclass(actual_hint, (list, set, frozenset, tuple)):
        codec = _resolve_collection(hint, actual_hint, args, context, meta)
    elif actual_hint is str:
        codec = StringCodec(**_len_kwargs(meta, context))
    elif actual_hint is bytes:
        codec = BytesCodec(**_len_kwargs(meta, context))
    else:
        _reject_len(meta, hint)
        codec = _resolve_base_codec(actual_hint)

    return _finish(codec, meta, field_name)


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


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


@dataclasses.dataclass(slots=True)
class Factory:
    primary_field: str
    id_map: dict[int, type] = dataclasses.field(default_factory=dict)
    codecs: dict[int, t.Callable] = dataclasses.field(default_factory=dict)
    # packed literal bytes -> codec; the primary field of every registered
    # class sits at the same static offset and has the same size
    _dispatch: dict[bytes, Codec] = dataclasses.field(
        default_factory=dict, repr=False
    )
    _offset: int | None = dataclasses.field(default=None, repr=False)
    _size: int | None = dataclasses.field(default=None, repr=False)

    def register(self, cls: type[T]) -> type[T]:
        codec = get_codec(cls)
        if not isinstance(codec, ClassCodec):
            raise BytesOperationError(f"{cls} must be a class")

        entries = {e.name: e for e in codec.entries}
        entry = entries.get(self.primary_field)
        if entry is None:
            raise BytesOperationError(
                f"{cls} have no codec for field {self.primary_field}"
            )

        primary_codec = entry.codec
        if not isinstance(primary_codec, LiteralCodec):
            raise BytesOperationError(
                f"{cls}.{self.primary_field} (cls={type(primary_codec)}) "
                f"should be typing.Literal"
            )

        offset = codec.field_offset(self.primary_field)
        inner = _to_spec(primary_codec.codec)
        if offset is None or inner is None:
            raise BytesOperationError(
                f"{cls}.{self.primary_field} should be a fixed-size integer "
                f"at a static offset"
            )
        try:
            packed = {v: inner.packed(v) for v in primary_codec.literals}
        except Exception as exc:
            raise BytesOperationError(
                f"{cls}.{self.primary_field} should be a fixed-size integer "
                f"literal"
            ) from exc
        if self._size is not None and (self._offset, self._size) != (
            offset,
            inner.size,
        ):
            raise BytesOperationError(
                f"{cls}.{self.primary_field} has offset={offset}, "
                f"size={inner.size}; registered classes use "
                f"offset={self._offset}, size={self._size}"
            )
        self._offset, self._size = offset, inner.size

        for id, raw in packed.items():
            self.id_map[id] = cls
            self.codecs[id] = codec
            self._dispatch[raw] = codec
        return cls

    def register_subclasses(
        self, cls: type[T], *, include_base: bool = False
    ) -> type[T]:
        """
        Register subclasses of the `cls`. Note that it's not a recursive
        method, only direct subclasses will be registered.

        :param cls: the base class
        :param include_base: True if you also need to register the base class
        :return: the base class
        """
        if include_base:
            self.register(cls)
        for subclass in cls.__subclasses__():
            self.register(subclass)
        return cls

    def encode(self, value: t.Any) -> bytes | None:
        """Encode the value, `None` if its primary id is not registered."""
        codec = self.codecs.get(getattr(value, self.primary_field))
        if codec is None:
            return None
        w = Writer()
        try:
            codec.write(value, w)
        except Exception as exc:
            raise BytesOperationError(
                f"Encoding failed at length {len(w.buffer)}: {exc}"
            ) from exc
        return bytes(w.buffer)

    def encode_to(self, value: t.Any, w: Writer) -> bool:
        """
        Append the encoded value to `w`. Returns False (and writes nothing)
        if its primary id is not registered. On failure `w` is left intact.
        """
        codec = self.codecs.get(getattr(value, self.primary_field))
        if codec is None:
            return False
        start = len(w.buffer)
        try:
            codec.write(value, w)
        except Exception as exc:
            del w.buffer[start:]
            raise BytesOperationError(
                f"Encoding failed at length {len(w.buffer)}: {exc}"
            ) from exc
        return True

    def decode(self, data: Buffer) -> t.Any | None:
        """Decode the value in `data`, `None` if its id is not registered."""
        r = Reader(data)
        try:
            if self._size is None:
                return None
            codec = self._dispatch.get(bytes(r.peek(self._size, self._offset)))
            if codec is None:
                return None
            return codec.read(r)
        except Exception as exc:
            raise BytesOperationError(
                f"Decoding failed at offset {r.offset}: {exc}"
            ) from exc
        finally:
            r.release()

    def decode_from(self, r: Reader) -> t.Any | None:
        """
        Decode the value at the reader's offset and advance it. Returns
        None (offset untouched) if its id is not registered.
        """
        try:
            if self._size is None:
                return None
            codec = self._dispatch.get(bytes(r.peek(self._size, self._offset)))
            if codec is None:
                return None
            return codec.read(r)
        except Exception as exc:
            raise BytesOperationError(
                f"Decoding failed at offset {r.offset}: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Module-level API: simple, not the fastest path (see Codec / Factory)
# ---------------------------------------------------------------------------


def encode(
    value: T,
    codec: Codec[T] | None = None,
    cls: type[T] | None = None,
    writer: Writer | None = None,
    *,
    trace_errors: bool = False,
) -> bytes:
    """
    Encode the value. Returns the whole content of the writer's buffer
    (just the encoded value unless a `writer` with data is given).
    On failure nothing is left in the user-supplied writer.
    `trace_errors`: see `Codec.encode`.
    """
    if codec is None:
        try:
            codec = get_codec(cls or type(value))
        except Exception as exc:
            raise BytesOperationError(f"Encoding failed: {exc}") from exc
    if writer is None:
        return codec.encode(value, trace_errors=trace_errors)
    codec.encode_to(value, writer, trace_errors=trace_errors)
    return bytes(writer.buffer)


def decode(
    data: Buffer,
    codec: Codec[T] | None = None,
    cls: type[T] | None = None,
    reader: Reader | None = None,
    *,
    trace_errors: bool = False,
) -> T:
    """
    Decode a value from `data`, or from the `reader` if it is provided
    (the reader's offset is advanced). `trace_errors`: see `Codec.encode`.
    """
    if not (codec or cls):
        raise ValueError(
            "Both codec and cls is None. "
            "At least one of them should be provided!"
        )
    if codec is None:
        try:
            codec = get_codec(cls)
        except Exception as exc:
            raise BytesOperationError(f"Decoding failed: {exc}") from exc
    if reader is None:
        return codec.decode(data, trace_errors=trace_errors)
    return codec.decode_from(reader, trace_errors=trace_errors)
