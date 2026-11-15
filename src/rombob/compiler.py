"""
Generation of fast `read`/`write` functions for classes (`ClassCodec`).
"""

import dataclasses
import functools
import linecache
import operator
import re
import struct as s
import typing as t

from .buffers import Reader, Writer
from .codecs import (
    BytesCodec,
    Codec,
    CollectionCodec,
    EnumCodec,
    IntCodec,
    LiteralCodec,
    NamedCodec,
    OptionalCodec,
    StringCodec,
    StructCodec,
    ValidatorCodec,
    _literal_error,
    _literal_prefail,
    _optional_extra,
    _optional_missing,
    _struct,
    _tuple_size_error,
)
from .errors import BytesOperationError
from .typing import BE, T

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


def _sized(raw: bytes, length: int) -> bytes:
    "Raw bytes of a fixed-size value; a wrong size can't be matched on bytes"
    if len(raw) != length:
        raise BytesOperationError(f"Expected {length} bytes, got {len(raw)}")
    return raw


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

    def packed(self, value: t.Any) -> bytes:
        return _sized(value.encode(), self.length)


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

    def packed(self, value: t.Any) -> bytes:
        return _sized(bytes(value), self.length)


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

    def packed(self, value: t.Any) -> bytes:
        raw = value.value if self.maps is None else self.maps[1][value]
        return self.inner.packed(raw)


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
        if inner is None:
            return None
        return _LiteralSpec(inner, codec.literals)
    if typ is EnumCodec:
        inner = _to_spec(codec.codec)
        if inner is None or codec._maps is None:
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
