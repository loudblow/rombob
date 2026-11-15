# AGENTS.md

## Overview
rombob is a library for binary serialization/deserialization of structures using type hints and annotations.

## Quick Start
```bash
make install    # poetry install + pre-commit hooks
make test       # pytest + coverage
make lint       # pre-commit run
```

## Single Test
```bash
poetry run pytest tests/test_basic.py -v -k test_name
```

## Key Commands
- `make format` - run ruff-format only
- `make clean` - clean caches and temp files

## Architecture
- **Package**: `src/rombob/` (single package, entry via `__init__.py`)
- **Tests**: `tests/test_basic.py`, `tests/test_compiler.py`
- **API**: `rombob.encode(value)` / `rombob.decode(data, cls)`

## Codec Caching
Codec classes are plain classes with value-based `__eq__`/`__hash__` (frozen dataclasses, `StructCodec` compares by format). Constructors do not intern instances. Memoization lives in `get_codec(hint)`, which caches per hint (unhashable hints are built without caching). Codecs must be stateless: all per-call state lives in `Reader`/`Writer`, so one codec can be shared freely. `get_codec(hint, compile=False)` returns the plain, non-compiled codecs (used by tests to compare against the compiled path).

## Compiler
`ClassCodec` for dataclasses/NamedTuples groups consecutive fixed-size fields (struct types, 24/48-bit ints, fixed `str`/`bytes`/collections, literals, enums, validators, nested all-fixed classes) into struct segments and generates `read`/`write` source (`codec.source`). See `repr(get_codec(cls))` for the segment layout.

## Benchmarks
`benchmarks/bench.py` (end-to-end encode/decode) and `benchmarks/bench_int24.py`.

## Language Policy
- Reply to the user in the language the user is communicating in.
- Write all files and code comments in English only.
