"""
F16 / F32 / F64: values, boundaries, out-of-range values.

A float32 can't hold 0.1, so comparing what was read with what was written
using `==` is only right for values that happen to be exactly representable.
Everything here is compared against `pytest.approx` with the precision of the
format, and the bytes against `struct`, which doesn't depend on rombob.
"""

import dataclasses
import math
import struct
import sys
import typing as t

import pytest

from rombob import (
    F16_B,
    F16_L,
    F32_B,
    F32_L,
    F64_B,
    F64_L,
    U8_B,
    BytesOperationError,
    Len,
    Writer,
    get_codec,
)


@dataclasses.dataclass(frozen=True)
class Format:
    name: str
    code: str  # struct format character
    hints: dict  # byte order char -> rombob hint
    rel: float  # relative precision (half an ulp, with some room)
    min_subnormal: float
    min_normal: float
    max: float
    below_max: float  # the next smaller value
    rounds_down: float  # above max, but rounds to max, no overflow
    overflow: tuple  # can't be stored, whatever the sign
    underflow: tuple  # too small, becomes zero (keeping the sign)
    normal: tuple

    @property
    def abs_tol(self) -> float:
        # a value between two subnormals is off by up to half a step
        return self.min_subnormal / 2


F16 = Format(
    name="F16",
    code="e",
    hints={"<": F16_L, ">": F16_B},
    rel=1e-3,
    min_subnormal=2**-24,
    min_normal=2**-14,
    max=65504.0,
    below_max=65472.0,
    rounds_down=65519.0,
    overflow=(65520.0, 7e4, 1e10, 1e308),
    underflow=(2**-25, 1e-10, 1e-300),
    normal=(0.1, 1.5, 3.14159, 123.456, 1000.5, 6.1e-5, 12345.0),
)
F32 = Format(
    name="F32",
    code="f",
    hints={"<": F32_L, ">": F32_B},
    rel=1e-6,
    min_subnormal=2**-149,
    min_normal=2**-126,
    max=3.4028234663852886e38,
    below_max=3.4028232635611926e38,
    rounds_down=3.4028235e38,
    overflow=(3.4028236e38, 3.5e38, 1e39, 1e300),
    underflow=(2**-150, 1e-50, 1e-300),
    normal=(0.1, 1.5, 3.14159265, 123456.789, 1e-30, 1.23e30, 16777216.0),
)
F64 = Format(
    name="F64",
    code="d",
    hints={"<": F64_L, ">": F64_B},
    rel=1e-15,
    min_subnormal=5e-324,
    min_normal=sys.float_info.min,
    max=sys.float_info.max,
    below_max=math.nextafter(sys.float_info.max, 0.0),
    rounds_down=sys.float_info.max,
    overflow=(2 * 10**308, 10**400),
    underflow=(),
    normal=(0.1, 1.5, 3.141592653589793, 1e-300, 1.7e308, 2.0**53 + 2),
)

FORMATS = (F16, F32, F64)
ORDERS = ("<", ">")


def cases(keep=lambda fmt: True):
    for fmt in FORMATS:
        if keep(fmt):
            for order in ORDERS:
                yield pytest.param(fmt, order, id=f"{fmt.name}{order}")


def oracle(fmt: Format, order: str, value: float) -> bytes:
    return struct.pack(f"{order}{fmt.code}", value)


def oracle_read(fmt: Format, order: str, data: bytes) -> float:
    return struct.unpack(f"{order}{fmt.code}", data)[0]


def finite_values(fmt: Format):
    "Representable values, both signs"
    base = [
        0.0,
        fmt.min_subnormal,
        fmt.min_subnormal * 3,
        fmt.min_normal,
        fmt.min_normal * 1.5,
        fmt.below_max,
        fmt.max,
        fmt.rounds_down,
        *fmt.normal,
    ]
    return base + [-v for v in base]


def assert_float(fmt: Format, got: float, expected: float) -> None:
    "`got` is what was read back for the written `expected`"
    assert isinstance(got, float)
    if math.isnan(expected):
        assert math.isnan(got)
    elif math.isinf(expected):
        assert got == expected  # approx is not needed (and not wanted)
    elif expected == 0:
        assert got == 0
        assert math.copysign(1, got) == math.copysign(1, expected)
    else:
        assert got == pytest.approx(expected, rel=fmt.rel, abs=fmt.abs_tol)


# - - - - - single values - - - - - #


@pytest.mark.parametrize("fmt, order", cases())
def test_values(subject, fmt, order):
    s = subject(fmt.hints[order])
    for value in finite_values(fmt):
        w = Writer()
        s.encode_to((value,), w)
        assert bytes(w.buffer) == oracle(fmt, order, value)
        (read,) = s.decode(bytes(w.buffer))
        assert_float(fmt, read, value)
        # whatever the precision, it's exactly what struct reads
        assert read == oracle_read(fmt, order, bytes(w.buffer))


@pytest.mark.parametrize("fmt, order", cases())
def test_special_values(subject, fmt, order):
    s = subject(fmt.hints[order])
    for value in (math.inf, -math.inf, math.nan, -math.nan, 0.0, -0.0):
        w = Writer()
        s.encode_to((value,), w)
        assert bytes(w.buffer) == oracle(fmt, order, value)
        (read,) = s.decode(bytes(w.buffer))
        assert_float(fmt, read, value)


@pytest.mark.parametrize("fmt, order", cases())
def test_signed_zero_is_kept(subject, fmt, order):
    s = subject(fmt.hints[order], 2)
    w = Writer()
    s.encode_to((0.0, -0.0), w)
    positive, negative = s.decode(bytes(w.buffer))
    assert math.copysign(1, positive) == 1
    assert math.copysign(1, negative) == -1


@pytest.mark.parametrize("fmt, order", cases())
def test_boundaries_are_exact(subject, fmt, order):
    "The edges of the format are representable: they come back unchanged"
    s = subject(fmt.hints[order])
    for value in (fmt.max, -fmt.max, fmt.min_normal, fmt.min_subnormal):
        w = Writer()
        s.encode_to((value,), w)
        (read,) = s.decode(bytes(w.buffer))
        assert read == value


@pytest.mark.parametrize("fmt, order", cases())
def test_precision_is_lost_as_expected(subject, fmt, order):
    "Why `==` is not the right comparison: 0.1 doesn't survive F16 and F32"
    s = subject(fmt.hints[order])
    w = Writer()
    s.encode_to((0.1,), w)
    (read,) = s.decode(bytes(w.buffer))
    assert read == pytest.approx(0.1, rel=fmt.rel)
    if fmt is F64:
        assert read == 0.1
    else:
        assert read != 0.1


@pytest.mark.parametrize("fmt, order", cases())
def test_ints_are_accepted_and_come_back_as_floats(subject, fmt, order):
    s = subject(fmt.hints[order])
    w = Writer()
    s.encode_to((3,), w)
    assert bytes(w.buffer) == oracle(fmt, order, 3.0)
    (read,) = s.decode(bytes(w.buffer))
    assert isinstance(read, float)
    assert read == pytest.approx(3.0, rel=fmt.rel)


# - - - - - out of range - - - - - #


@pytest.mark.parametrize("fmt, order", cases())
def test_overflow_is_an_error(subject, fmt, order):
    s = subject(fmt.hints[order])
    for value in fmt.overflow:
        for signed in (value, -value):
            w = Writer(bytearray(b"keep"))
            with pytest.raises(BytesOperationError):
                s.encode_to((signed,), w)
            assert bytes(w.buffer) == b"keep"


@pytest.mark.parametrize("fmt, order", cases())
def test_just_beyond_max_rounds_to_max(subject, fmt, order):
    "Up to the half way to the next step it's rounded, not an error"
    s = subject(fmt.hints[order])
    for value in (fmt.rounds_down, -fmt.rounds_down):
        w = Writer()
        s.encode_to((value,), w)
        (read,) = s.decode(bytes(w.buffer))
        assert read == math.copysign(fmt.max, value)


@pytest.mark.parametrize("fmt, order", cases())
def test_the_first_overflowing_value_fails(subject, fmt, order):
    "The values on both sides of the threshold behave differently"
    s = subject(fmt.hints[order])
    ok, bad = fmt.rounds_down, fmt.overflow[0]
    assert ok < bad
    s.encode_to((ok,), Writer())
    with pytest.raises(BytesOperationError):
        s.encode_to((bad,), Writer())


@pytest.mark.parametrize("fmt, order", list(cases(lambda fmt: fmt.underflow)))
def test_underflow_becomes_a_signed_zero(subject, fmt, order):
    s = subject(fmt.hints[order])
    for value in fmt.underflow:
        for signed in (value, -value):
            w = Writer()
            s.encode_to((signed,), w)
            assert bytes(w.buffer) == oracle(fmt, order, signed)
            (read,) = s.decode(bytes(w.buffer))
            assert read == 0
            assert math.copysign(1, read) == math.copysign(1, signed)


@pytest.mark.parametrize("fmt, order", cases())
def test_wrong_types(subject, fmt, order):
    s = subject(fmt.hints[order])
    for value in ("1.5", None, b"\x00", [1.0], object()):
        w = Writer()
        with pytest.raises(BytesOperationError):
            s.encode_to((value,), w)
        assert len(w.buffer) == 0


@pytest.mark.parametrize("fmt, order", cases())
def test_truncated(fmt, order):
    codec = get_codec(fmt.hints[order])
    size = struct.calcsize(fmt.code)
    with pytest.raises(BytesOperationError):
        codec.decode(b"\x00" * (size - 1))
    assert codec.decode(b"\x00" * size) == 0.0


# - - - - - several values at once - - - - - #


def arrays_class(hint) -> type:
    return dataclasses.make_dataclass(
        "Arrays",
        [
            ("fixed", t.Annotated[tuple[hint, ...], Len(3)]),
            ("var", list[hint]),
            ("tail", U8_B),
            ("maybe", hint | None),  # last: it's read if there is data left
        ],
    )


@pytest.mark.parametrize("fmt, order", cases())
def test_arrays(compile, fmt, order):
    cls = arrays_class(fmt.hints[order])
    codec = get_codec(cls, compile=compile)
    fixed = (0.1, -fmt.max, fmt.min_subnormal)
    var = [1.5, -0.0, 123.456, fmt.min_normal]
    value = cls(fixed, var, 7, 0.1)

    data = codec.encode(value)
    prefix = struct.pack(">H", len(var))
    expected = (
        struct.pack(f"{order}3{fmt.code}", *fixed)
        + prefix
        + struct.pack(f"{order}{len(var)}{fmt.code}", *var)
        + b"\x07"
        + struct.pack(f"{order}{fmt.code}", 0.1)
    )
    assert data == expected

    back = codec.decode(data)
    assert list(back.fixed) == pytest.approx(
        [oracle_read(fmt, order, oracle(fmt, order, v)) for v in fixed],
        rel=fmt.rel,
        abs=fmt.abs_tol,
    )
    assert back.var == pytest.approx(var, rel=fmt.rel, abs=fmt.abs_tol)
    assert back.maybe == pytest.approx(0.1, rel=fmt.rel)
    assert back.tail == 7
    assert isinstance(back.fixed, tuple) and isinstance(back.var, list)


@pytest.mark.parametrize("fmt, order", cases())
def test_arrays_with_special_values(compile, fmt, order):
    cls = arrays_class(fmt.hints[order])
    codec = get_codec(cls, compile=compile)
    value = cls((math.inf, -math.inf, math.nan), [math.nan, math.inf], 0, None)
    back = codec.decode(codec.encode(value))
    assert back.fixed[:2] == (math.inf, -math.inf)
    assert math.isnan(back.fixed[2])
    assert math.isnan(back.var[0]) and back.var[1] == math.inf
    assert back.maybe is None


@pytest.mark.parametrize("fmt, order", list(cases(lambda fmt: fmt is not F64)))
def test_one_overflowing_item_fails_the_whole_array(compile, fmt, order):
    cls = arrays_class(fmt.hints[order])
    codec = get_codec(cls, compile=compile)
    over = fmt.overflow[0]
    for value in (
        cls((0.0, over, 0.0), [], 0, None),
        cls((0.0, 0.0, 0.0), [1.0, -over], 0, None),
        cls((0.0, 0.0, 0.0), [], 0, over),
    ):
        w = Writer(bytearray(b"keep"))
        with pytest.raises(BytesOperationError):
            codec.encode_to(value, w)
        assert bytes(w.buffer) == b"keep"


@pytest.mark.parametrize("fmt, order", cases())
def test_bytes_do_not_depend_on_compilation(fmt, order):
    cls = arrays_class(fmt.hints[order])
    value = cls((1.5, 0.1, -3.0), [0.25, 0.1], 1, 0.1)
    assert get_codec(cls, compile=True).encode(value) == get_codec(
        cls, compile=False
    ).encode(value)
