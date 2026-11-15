from __future__ import annotations

import dataclasses
import typing as t

import pytest

import rombob


@dataclasses.dataclass
class Inner:
    a: rombob.U8_L


@dataclasses.dataclass
class Outer:
    inner: Inner
    items: list[Inner]
    opt: t.Optional[Inner]  # noqa: UP045
    lit: t.Literal[1]


class Named(t.NamedTuple):
    inner: Inner


class NamedQuoted(t.NamedTuple):
    inner: "Inner"  # noqa: UP037


@dataclasses.dataclass
class Quoted:
    inner: "Inner"  # noqa: UP037


def test_future_annotations_roundtrip():
    value = Outer(Inner(1), [Inner(2), Inner(3)], Inner(4), 1)
    assert rombob.decode(rombob.encode(value), cls=Outer) == value


def test_string_hint_and_namedtuple():
    quoted = Quoted(Inner(5))
    assert rombob.decode(rombob.encode(quoted), cls=Quoted) == quoted
    named = Named(Inner(6))
    assert rombob.decode(rombob.encode(named), cls=Named) == named
    named_q = NamedQuoted(Inner(7))
    assert rombob.decode(rombob.encode(named_q), cls=NamedQuoted) == named_q


def test_unresolvable_local_reference():
    @dataclasses.dataclass
    class Local:
        x: Missing  # noqa: F821

    with pytest.raises(rombob.BytesOperationError):
        rombob.get_codec(Local)


def test_bare_string_hint():
    with pytest.raises(rombob.BytesOperationError):
        rombob.get_codec("Inner")  # type: ignore[arg-type]
