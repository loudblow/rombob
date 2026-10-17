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
- **Tests**: `tests/test_basic.py`
- **API**: `rombob.encode(value)` / `rombob.decode(data, cls)`

## Codec Caching
All `Codec` classes are cached via `@cache` (from `functools.lru_cache`). This means codec instances are memoized - the same codec is returned for identical type hints. Tests involving codec state should account for this.

## Language Policy
- Reply to the user in the language the user is communicating in.
- Write all files and code comments in English only.
