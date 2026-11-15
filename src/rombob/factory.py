import dataclasses
import typing as t

from .buffers import Reader, Writer
from .codecs import Codec, LiteralCodec
from .compiler import ClassCodec, _to_spec
from .errors import BytesOperationError
from .parser import get_codec
from .typing import Buffer, T


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
                f"{cls}.{self.primary_field} should be a fixed-size literal "
                f"at a static offset"
            )
        try:
            packed = {v: inner.packed(v) for v in primary_codec.literals}
        except Exception as exc:
            raise BytesOperationError(
                f"{cls}.{self.primary_field} should be a literal of integers, "
                f"strings or bytes of a fixed size"
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
    if codec is None and cls is None:
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
