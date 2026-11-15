"""
The `Codec` base class and the primitive and composite codecs.
"""

import dataclasses
import enum
import functools
import struct as s
import typing as t

from .buffers import Reader, Writer
from .errors import BytesOperationError
from .typing import Buffer, ByteOrder, EnumT, T


def _encode_message(*args: t.Any) -> str:
    "Imported lazily: `tracing` depends on the codecs defined in this module"
    from .tracing import _encode_message as message

    return message(*args)


def _decode_message(*args: t.Any) -> str:
    "Imported lazily: `tracing` depends on the codecs defined in this module"
    from .tracing import _decode_message as message

    return message(*args)


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
        from .compiler import _leaf_item  # compiler imports this module

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
