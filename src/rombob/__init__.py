import dataclasses
import enum
import functools
import struct as s
import sys
import types
import typing as t

if sys.version_info >= (3, 12):
    from collections.abc import Buffer
else:
    from collections.abc import ByteString as Buffer

from annotated_types import Len

__all__ = [
    "Named",
    "BytesOperationError",
    "Context",
    "ByteOrder",
    "LE",
    "BE",
    "cache",
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
    "LiteralCodec",
    "NamedCodec",
    "ClassCodec",
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

_NAMED_MARKER = "__rombob__NamedMarker__"
Named = t.Annotated[T, _NAMED_MARKER]


class BytesOperationError(Exception):
    pass


@dataclasses.dataclass(slots=True)
class Context:
    buffer: Buffer = dataclasses.field(default_factory=bytearray)
    data: dict[str, t.Any] = dataclasses.field(default_factory=dict)

    def __enter__(self) -> "Context":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        if exc_val is None:
            return True
        if isinstance(exc_val, Exception):
            if isinstance(self.buffer, memoryview):
                self.buffer.release()
            self.clear()
            raise BytesOperationError from exc_val

    def clear(self) -> None:
        self.__init__()

    def pop(self, n: int) -> Buffer:
        "Remove and return first n bytes from the buffer"
        rv = self.buffer[:n]
        self.buffer = self.buffer[n:]
        return rv

    def write(self, codec: "Codec[T]", value: T) -> None:
        with self as ctx:
            codec.write(value=value, ctx=ctx)

    def read(self, codec: "Codec[T]") -> T:
        with self as ctx:
            return codec.read(ctx=ctx)


class ByteOrder(str, enum.Enum):
    LITTLE = "little"
    BIG = "big"


LE = ByteOrder.LITTLE
BE = ByteOrder.BIG


def cache(user_function: T) -> T:
    return functools.lru_cache(maxsize=None, typed=True)(user_function)


@t.runtime_checkable
class Codec(t.Protocol[T]):
    def write(self, value: T, ctx: Context) -> None: ...
    def read(self, ctx: Context) -> T: ...


@cache
class StructCodec(s.Struct, Codec[T]):
    __slots__ = ()

    def write(self, value: T, ctx: Context) -> None:
        ctx.buffer += self.pack(value)

    def read(self, ctx: Context) -> T:
        return self.unpack(ctx.pop(self.size))[0]


@cache
@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class IntCodec(Codec[int]):
    length: int
    byteorder: ByteOrder
    signed: bool

    def write(self, value: int, ctx: Context) -> None:
        ctx.buffer += value.to_bytes(
            length=self.length,
            byteorder=self.byteorder,
            signed=self.signed,
        )

    def read(self, ctx: Context) -> int:
        return int.from_bytes(
            ctx.pop(self.length),
            byteorder=self.byteorder,
            signed=self.signed,
        )


@cache
@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class VarIntCodec(Codec[int]):
    signed: bool

    @classmethod
    def _sign_for_writing(cls, value: int) -> int:
        return ~(value << 1) if value < 0 else (value << 1)

    @classmethod
    def _sign_for_reading(cls, value: int) -> int:
        return ~(value >> 1) if value & 1 else (value >> 1)

    def write(self, value: int, ctx: Context) -> None:
        if self.signed:
            value = self._sign_for_writing(value)
        else:
            if value < 0:
                raise BytesOperationError(
                    f"value={value} should be greater than or equal 0"
                )
        while True:
            d = value & 0x7F
            value >>= 7
            if value != 0:
                ctx.buffer.append(d | 0x80)
            else:
                ctx.buffer.append(d)
                break

    def read(self, ctx: Context) -> int:
        if len(ctx.buffer) == 0:
            raise BytesOperationError(f"buffer is empty. Context={ctx}")
        value = 0
        shift = 0
        offset = 0
        for d in ctx.buffer:
            offset += 1
            value += (d & 0x7F) << shift
            if d & 0x80 == 0:
                break
            shift += 7
        ctx.buffer = ctx.buffer[offset:]
        if self.signed:
            return self._sign_for_reading(value)
        return value


@cache
@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class StringCodec(Codec[str]):
    len_codec: Codec = StructCodec(">H")
    length: int | None = None

    def write(self, value: str, ctx: Context) -> None:
        data = value.encode(encoding="utf-8")
        length = len(data)
        if self.length is None:
            self.len_codec.write(length, ctx)
        elif self.length != length:
            raise BytesOperationError(
                f"Wrong value length: got {length}, expected {self.length}"
            )
        ctx.buffer += data

    def read(self, ctx: Context) -> str:
        length = self.length or self.len_codec.read(ctx)
        return str(ctx.pop(length), encoding="utf-8")


@cache
@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class BytesCodec(Codec[bytes]):
    len_codec: Codec = StructCodec(">H")
    length: int | None = None

    def write(self, value: bytes, ctx: Context) -> None:
        length = len(value)
        if self.length is None:
            self.len_codec.write(length, ctx)
        elif self.length != length:
            raise BytesOperationError(
                f"Wrong value length: got {length}, expected {self.length}"
            )
        ctx.buffer += value

    def read(self, ctx: Context) -> bytes:
        length = self.length or self.len_codec.read(ctx)
        return ctx.pop(length).tobytes()


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class CollectionCodec(Codec[T]):
    cls: T
    item_codec: Codec
    len_codec: Codec = StructCodec(">H")
    length: int | None = None

    def write(self, value: T, ctx: Context) -> None:
        length = len(value)
        if self.length is None:
            self.len_codec.write(length, ctx)
        elif self.length != length:
            raise BytesOperationError(
                f"Wrong collection size, got {length}, expected {self.length}"
            )

        for item in value:
            self.item_codec.write(item, ctx)

    def read(self, ctx: Context) -> T:
        length = self.length or self.len_codec.read(ctx)

        cls = self.cls
        # handle the builtin types first for speed; subclasses handled below
        if cls is list:
            return [self.item_codec.read(ctx) for _ in range(length)]
        elif cls is tuple:
            return tuple([self.item_codec.read(ctx) for _ in range(length)])
        elif cls is set:
            return {self.item_codec.read(ctx) for _ in range(length)}
        elif cls is frozenset:
            return frozenset({self.item_codec.read(ctx) for _ in range(length)})
        else:
            return cls(self.item_codec.read(ctx) for _ in range(length))


@cache
@dataclasses.dataclass(slots=True, frozen=True)
class RawCodec(Codec[bytes]):
    def write(self, value: bytes, ctx: Context) -> None:
        ctx.buffer += value

    def read(self, ctx: Context) -> bytes:
        rv = ctx.buffer.tobytes()
        ctx.buffer = ctx.buffer[:0]
        return rv


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class OptionalCodec(Codec[T]):
    "Read/write if predicate is True"

    codec: Codec[T]
    predicate: t.Callable[[Context], bool] | None = None

    def read(self, ctx: Context) -> T | None:
        if self.predicate:
            return self.codec.read(ctx) if self.predicate(ctx) else None
        else:
            return self.codec.read(ctx) if len(ctx.buffer) else None

    def write(self, value: T | None, ctx: Context) -> None:
        if self.predicate:
            if self.predicate(ctx) and value is not None:
                self.codec.write(value, ctx)
        else:
            if value is not None:
                self.codec.write(value, ctx)


@dataclasses.dataclass(slots=True, kw_only=True)
class ValidatorCodec(Codec[T]):
    codec: Codec
    read_validator: dataclasses.InitVar[t.Callable[[B], T] | None] = None
    write_validator: dataclasses.InitVar[t.Callable[[T], B] | None] = None

    def __post_init__(
        self,
        read_validator: t.Callable[[B], T] | None,
        write_validator: t.Callable[[T], B] | None,
    ) -> None:
        self.read = (
            (lambda ctx: read_validator(self.codec.read(ctx)))
            if read_validator
            else self.codec.read
        )
        self.write = (
            (lambda value, ctx: self.codec.write(write_validator(value), ctx))
            if write_validator
            else self.codec.write
        )

    def read(self, ctx: Context) -> T:
        return self.codec.read(ctx)

    def write(self, value: T, ctx: Context) -> None:
        self.codec.write(value, ctx)


def EnumCodec(codec: Codec, cls: EnumT) -> Codec[EnumT]:
    return ValidatorCodec(
        codec=codec,
        read_validator=lambda d: cls(d),
        write_validator=lambda d: d.value,
    )


@dataclasses.dataclass(slots=True, kw_only=True)
class LiteralCodec(Codec[T]):
    codec: Codec
    literals: t.Iterable[T]

    def __post_init__(self) -> None:
        self.literals = frozenset(self.literals)

    def read(self, ctx: Context) -> T:
        value = self.codec.read(ctx)
        if value in self.literals:
            return value
        raise BytesOperationError(
            f"typing.Literal{list(self.literals)} doesn't contain {value}"
        )

    def write(self, value: T, ctx: Context) -> None:
        if value not in self.literals:
            raise BytesOperationError(
                f"typing.Literal{list(self.literals)} doesn't contain {value}"
            )
        return self.codec.write(value, ctx)


@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class NamedCodec(Codec[T]):
    codec: Codec[T]
    key: str

    def read(self, ctx: Context) -> T:
        value = self.codec.read(ctx)
        ctx.data[self.key] = value
        return value

    def write(self, value: T | None, ctx: Context) -> None:
        self.codec.write(value, ctx)
        ctx.data[self.key] = value


@dataclasses.dataclass(slots=True, kw_only=True, frozen=True)
class ClassCodec(Codec[T]):
    cls: T
    fields: t.Iterable[tuple[str, Codec]] = dataclasses.field(
        default_factory=list
    )

    def write(self, value: T, ctx: Context) -> None:
        for name, codec in self.fields:
            codec.write(getattr(value, name), ctx)

    def read(self, ctx: Context) -> T:
        kwargs = {name: codec.read(ctx) for name, codec in self.fields}
        return self.cls(**kwargs)


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


_FALLBACKS: dict[type, type] = {
    bool: StructCodec("?"),
    str: StringCodec(len_codec=StructCodec(">H")),
    bytes: BytesCodec(len_codec=StructCodec(">H")),
    int: StructCodec(">q"),
    float: StructCodec(">d"),
}


ParserContext = dict[t.TypeVar, t.Any]
Args = t.Iterable[t.Any]


def get_codec(hint: type[T]) -> Codec[T]:
    return _get_codec_inner(hint, context={})


def _resolve_base_codec(hint: t.Any, explicit_codec: Codec | None) -> Codec:
    if explicit_codec is not None:
        return explicit_codec
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


def _resolve_literal(
    args: Args, context: ParserContext, explicit_codec: Codec | None
) -> Codec:
    codec = (
        explicit_codec
        if explicit_codec
        else _get_codec_inner(type(args[0]), context)
    )
    return LiteralCodec(codec=codec, literals=args)


def _resolve_enum(actual_hint: t.Any, explicit_codec: Codec) -> EnumCodec:
    codec = (
        explicit_codec
        if explicit_codec
        else _resolve_base_codec(actual_hint, explicit_codec)
    )
    return EnumCodec(codec=codec, cls=actual_hint)


def _resolve_class(
    hint: t.Any, actual_hint: t.Any, args: Args, context: ParserContext
) -> ClassCodec:
    new_context = dict(context)
    if hasattr(actual_hint, "__parameters__") and args:
        new_context.update(zip(actual_hint.__parameters__, args, strict=False))
    hints = t.get_type_hints(actual_hint, include_extras=True)
    fields = {
        name: _get_codec_inner(f_hint, new_context, field_name=name)
        for name, f_hint in hints.items()
    }
    return ClassCodec(cls=hint, fields=fields.items())


def _resolve_dataclass(
    hint: t.Any, actual_hint: t.Any, args: Args, context: ParserContext
) -> ClassCodec:
    new_context = dict(context)
    if hasattr(actual_hint, "__parameters__") and args:
        new_context.update(zip(actual_hint.__parameters__, args, strict=False))
    fields = {
        f.name: _get_codec_inner(f.type, new_context, field_name=f.name)
        for f in dataclasses.fields(actual_hint)
    }
    return ClassCodec(cls=hint, fields=fields.items())


def _resolve_collection(
    actual_hint: t.Any, args: Args, context: ParserContext, length: int
) -> CollectionCodec:
    item_hint = args[0] if args else t.Any
    item_codec = _get_codec_inner(item_hint, context)
    return CollectionCodec(
        cls=actual_hint, item_codec=item_codec, length=length
    )


def _resolve_optional(
    args: Args, context: ParserContext, field_name: str
) -> OptionalCodec:
    other_args = [a for a in args if a is not type(None)]
    other = (
        other_args[0] if len(other_args) == 1 else t.Union[tuple(other_args)]  # noqa: UP007
    )
    inner_codec = _get_codec_inner(other, context, field_name)
    return OptionalCodec(codec=inner_codec)


def _get_codec_inner(
    hint: t.Any, context: dict[t.TypeVar, t.Any], field_name: str | None = None
) -> Codec:
    if isinstance(hint, t.TypeVar):
        hint = context.get(hint, hint)

    origin = t.get_origin(hint)
    args = t.get_args(hint)
    actual_hint = origin if origin is not None else hint
    if (
        actual_hint is t.Union
        or actual_hint is getattr(types, "UnionType", object)
    ) and type(None) in args:
        return _resolve_optional(
            args=args, context=context, field_name=field_name
        )

    explicit_codec = None
    length_override = None
    is_named = False
    if actual_hint is t.Annotated:
        base_type = args[0]
        metadata = args[1:]
        for meta in metadata:
            if isinstance(meta, Codec):
                explicit_codec = meta
            elif isinstance(meta, Len):
                length_override = meta.min_length
            elif meta == _NAMED_MARKER:
                is_named = True
            elif t.get_origin(meta) is t.Annotated:
                # If metadata is Annotated
                try:
                    explicit_codec = _get_codec_inner(meta, context)
                except BytesOperationError:
                    pass
        hint = base_type
        origin = t.get_origin(hint)
        args = t.get_args(hint)
        actual_hint = origin if origin is not None else hint

    if actual_hint is t.Literal:
        codec = _resolve_literal(
            args=args, context=context, explicit_codec=explicit_codec
        )
    elif isinstance(actual_hint, type) and issubclass(actual_hint, enum.Enum):
        codec = _resolve_enum(
            actual_hint=actual_hint, explicit_codec=explicit_codec
        )
    elif issubclass(actual_hint, tuple) and hasattr(actual_hint, "_fields"):
        codec = _resolve_class(
            hint=hint, actual_hint=actual_hint, args=args, context=context
        )
    elif dataclasses.is_dataclass(actual_hint):
        codec = _resolve_dataclass(
            hint=hint, actual_hint=actual_hint, args=args, context=context
        )
    elif issubclass(actual_hint, (list, set, frozenset, tuple)):
        codec = _resolve_collection(
            actual_hint=actual_hint,
            args=args,
            context=context,
            length=length_override,
        )
    elif issubclass(actual_hint, (str, bytes)) and length_override:
        if issubclass(actual_hint, str):
            codec = StringCodec(length=length_override)
        elif issubclass(actual_hint, bytes):
            codec = BytesCodec(length=length_override)
    elif explicit_codec is not None:
        codec = explicit_codec
    else:
        codec = _resolve_base_codec(actual_hint, explicit_codec)

    if is_named and field_name is not None:
        codec = NamedCodec(codec=codec, key=field_name)

    return codec


def encode(
    value: T,
    codec: Codec[T] | None = None,
    cls: type[T] | None = None,
) -> bytearray:
    if not codec:
        codec = get_codec(cls or type(value))
    with Context() as ctx:
        ctx.write(codec=codec, value=value)
    return ctx.buffer


def decode(
    data: Buffer,
    codec: Codec[T] | None = None,
    cls: type[T] | None = None,
) -> T:
    if not (codec or cls):
        raise ValueError(
            "Both codec and cls is None. "
            "At least one of them should be provided!"
        )
    codec = codec or get_codec(cls)
    with Context(memoryview(data)) as ctx:
        return ctx.read(codec)
