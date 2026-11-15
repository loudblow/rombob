"""
Annotations for `typing.Annotated` hints: lengths, constraints, conditions.

This module has no dependencies: it only describes *what* the user asked for.
Turning the annotations into codecs happens in `rombob.__init__`.
"""

import dataclasses
import typing as t

__all__ = [
    "Len",
    "Prefix",
    "Gt",
    "Ge",
    "Lt",
    "Le",
    "Range",
    "Predicate",
    "When",
    "Named",
    "Skip",
]

T = t.TypeVar("T")


class _Marker:
    "A flag annotation (compared by identity)"

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<{self.name}>"


NAMED = _Marker("Named")
SKIP = _Marker("Skip")

# The value is remembered (under the field name) in `Reader.data` /
# `Writer.data` so that `Len(ref=...)` and `When` can refer to it
Named = t.Annotated[T, NAMED]

# The field is neither read nor written, the class default is used instead
Skip = t.Annotated[T, SKIP]


@dataclasses.dataclass(frozen=True, slots=True)
class Len:
    """
    The exact length of a `str`/`bytes`/collection, or a `Literal` of
    `str`/`bytes`. The length of a `str` is the length of its UTF-8 encoding,
    the length of a collection is its number of items.

    * `Len(3)` - exactly 3, nothing is stored in the data
    * `Len(ref="count")` - taken from the earlier field annotated with
      `Named`. When writing, the value must have exactly that length.
    * `Len(ref=lambda ctx: ctx.data["size"] - 4)` - computed from the
      `Reader`/`Writer`

    Without `Len` the length is stored in front of the data (see `Prefix`).
    """

    n: int | None = None
    ref: str | t.Callable[[t.Any], int] | None = None

    def __post_init__(self) -> None:
        if (self.n is None) == (self.ref is None):
            raise ValueError("Len needs exactly one of: n, ref")
        if self.n is not None and (
            not isinstance(self.n, int)
            or isinstance(self.n, bool)
            or self.n < 0
        ):
            raise ValueError(f"Len(n) needs a non-negative int, got {self.n!r}")


@dataclasses.dataclass(frozen=True, slots=True)
class Prefix:
    """
    How the length of a `str`/`bytes`/collection is stored in front of it.
    Takes a codec or a hint that resolves to one, e.g. `Prefix(U8_B)`.
    The default is an unsigned 16-bit big-endian integer.
    """

    codec: t.Any


class _Constraint:
    "A check of the value, applied when reading and when writing"

    __slots__ = ()

    def ok(self, value: t.Any) -> bool:
        raise NotImplementedError


@dataclasses.dataclass(frozen=True, slots=True)
class Gt(_Constraint):
    value: t.Any

    def ok(self, value: t.Any) -> bool:
        return value > self.value


@dataclasses.dataclass(frozen=True, slots=True)
class Ge(_Constraint):
    value: t.Any

    def ok(self, value: t.Any) -> bool:
        return value >= self.value


@dataclasses.dataclass(frozen=True, slots=True)
class Lt(_Constraint):
    value: t.Any

    def ok(self, value: t.Any) -> bool:
        return value < self.value


@dataclasses.dataclass(frozen=True, slots=True)
class Le(_Constraint):
    value: t.Any

    def ok(self, value: t.Any) -> bool:
        return value <= self.value


@dataclasses.dataclass(frozen=True, slots=True)
class Range(_Constraint):
    "`lo <= value <= hi`, both ends included"

    lo: t.Any
    hi: t.Any

    def ok(self, value: t.Any) -> bool:
        return self.lo <= value <= self.hi


@dataclasses.dataclass(frozen=True, slots=True)
class Predicate(_Constraint):
    "`func(value)` must be true"

    func: t.Callable[[t.Any], bool]

    def ok(self, value: t.Any) -> bool:
        return bool(self.func(value))


@dataclasses.dataclass(frozen=True, slots=True)
class When:
    """
    Marks an optional field (`X | None`) as present only under a condition.

    * `When(lambda ctx: "token" in ctx.data)` - `ctx` is the `Reader` or the
      `Writer`; `ctx.data` holds the fields annotated with `Named`
    * `When(ref="has_token")` - the earlier `Named` field is truthy

    Writing fails if the value disagrees with the condition: a value is given
    but the condition is false, or the value is `None` but it's true.
    """

    predicate: t.Callable[[t.Any], bool] | None = None
    ref: str | None = None

    def __post_init__(self) -> None:
        if (self.predicate is None) == (self.ref is None):
            raise ValueError("When needs exactly one of: predicate, ref")


CONSTRAINTS = (Gt, Ge, Lt, Le, Range, Predicate)
