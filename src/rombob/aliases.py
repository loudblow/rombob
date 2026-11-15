"""
Public `Annotated` aliases for the common binary types.
"""

import typing as t

from .codecs import IntCodec, RawCodec, StructCodec, VarIntCodec
from .typing import BE, LE

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
