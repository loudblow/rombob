import enum
import typing as t

T = t.TypeVar("T")
B = t.TypeVar("B")
EnumT = t.TypeVar("EnumT", bound=enum.Enum)
Buffer = t.Union[bytes, bytearray, memoryview]  # noqa: UP007
ParserContext = dict[t.TypeVar, t.Any]
Args = t.Iterable[t.Any]


class ByteOrder(str, enum.Enum):
    LITTLE = "little"
    BIG = "big"


LE = ByteOrder.LITTLE
BE = ByteOrder.BIG
