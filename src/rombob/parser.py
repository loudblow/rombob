"""
Turns type hints (with annotations) into codecs: `get_codec`.
"""

import dataclasses
import enum
import types
import typing as t

from .codecs import (
    BytesCodec,
    Codec,
    CollectionCodec,
    EnumCodec,
    LiteralCodec,
    NamedCodec,
    OptionalCodec,
    RefLenCodec,
    StringCodec,
    StructCodec,
    ValidatorCodec,
    _Check,
    _RefTruthy,
)
from .compiler import ClassCodec
from .errors import BytesOperationError
from .metadata import CONSTRAINTS, NAMED, SKIP, Len, Prefix, When
from .typing import Args, ParserContext, T

_COMPILE = True  # see get_codec(compile=...)

_CODECS: dict[t.Any, Codec] = {}
_PLAIN_CODECS: dict[t.Any, Codec] = {}
# Two maps on purpose. `_FALLBACKS` are the defaults for plain leftovers and
# are consulted last: `str`/`bytes`/collections are built by their own
# branches first because they need `Len`/`Prefix`. `_REGISTERED` (see
# `register_codec`) are user overrides and win over every branch, so they
# can't live in `_FALLBACKS` without stopping `str`/`bytes` from honouring
# `Len`. Both are consulted where a base codec is looked up.
_REGISTERED: dict[t.Any, Codec] = {}
_FALLBACKS: dict[type, Codec] = {
    bool: StructCodec("?"),
    str: StringCodec(len_codec=StructCodec(">H")),
    bytes: BytesCodec(len_codec=StructCodec(">H")),
    int: StructCodec(">q"),
    float: StructCodec(">d"),
}


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


def register_codec(
    hint: t.Any, codec: Codec, *, override: bool = False
) -> Codec:
    """
    Register `codec` as the default codec of `hint` (usually a class).

    From now on every field and every `get_codec` call of that type uses it,
    unless the field carries an explicit codec in `Annotated`. Registered
    codecs take priority over the built-in handling of dataclasses, enums and
    primitives. Subscripted generics (`Foo[int]`) fall back to the codec of
    their origin (`Foo`) when they have no codec of their own.

    Classes and codecs built before the call are not affected (the memoized
    ones are dropped, but the objects you already hold stay as they are), so
    register before building codecs and registering classes in a `Factory`.

    :param override: allow replacing an already registered (or a built-in
        primitive) codec of the same hint
    :return: the codec, so it can be used inline
    """
    if not isinstance(codec, Codec):
        raise BytesOperationError(
            f"register_codec expects a Codec, got {codec!r}"
        )
    if t.get_origin(hint) is t.Annotated:
        raise BytesOperationError(
            f"Can't register a codec for {hint}: Annotated hints carry "
            f"their own codec, register the underlying type instead"
        )
    if hint is t.Literal or t.get_origin(hint) is t.Literal:
        raise BytesOperationError("Can't register a codec for a Literal")
    if hint is None or isinstance(hint, (str, t.ForwardRef, t.TypeVar)):
        raise BytesOperationError(f"Can't register a codec for {hint!r}")
    try:
        hash(hint)
    except TypeError:
        raise BytesOperationError(
            f"Can't register a codec for unhashable {hint!r}"
        ) from None
    if not override and (hint in _REGISTERED or hint in _FALLBACKS):
        raise BytesOperationError(
            f"{hint} already has a codec; pass override=True to replace it"
        )
    _REGISTERED[hint] = codec
    _clear_caches()
    return codec


def unregister_codec(hint: t.Any) -> None:
    "Remove a codec added by `register_codec`; no-op if there is none"
    if _REGISTERED.pop(hint, None) is not None:
        _clear_caches()


def _clear_caches() -> None:
    _CODECS.clear()
    _PLAIN_CODECS.clear()


def _registered(hint: t.Any, actual_hint: t.Any) -> Codec | None:
    if not _REGISTERED:
        return None
    try:
        codec = _REGISTERED.get(hint)
        return codec if codec is not None else _REGISTERED.get(actual_hint)
    except TypeError:  # unhashable hint
        return None


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
        # the codec of the value type (`int` for an IntEnum), registered
        # overrides first
        for base in hint.__mro__:
            if base in _REGISTERED:
                return _REGISTERED[base]
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
    codec = (
        meta.codec
        if meta.codec is not None
        else _resolve_base_codec(actual_hint)
    )
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

    custom = _registered(hint, actual_hint) if meta.codec is None else None
    if actual_hint is t.Literal:
        codec = _resolve_literal(args, context, meta)
    elif custom is not None:
        _reject_len(meta, f"{hint} with a registered codec")
        codec = custom
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
