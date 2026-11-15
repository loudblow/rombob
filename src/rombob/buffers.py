import struct as s
import typing as t

from .errors import BytesOperationError
from .typing import Buffer


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
