# Contributing

Thanks for your interest in improving `langchain-mongodb-agent-log`.

## Development setup

This project uses [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/mongodb-partners/langchain-mongodb-agent-log
cd langchain-mongodb-agent-log
uv sync --group dev
```

## Quality gates

Every change must keep all three gates green:

```bash
uv run ruff check src tests      # lint + import order
uv run mypy --strict src         # static types
uv run pytest -q                 # unit tier (hermetic — mongomock, no Atlas)
```

CI runs the same gates on Python 3.11, 3.12, and 3.13.

The integration suite under `tests/integration/` is gated on a live Atlas
connection and skips automatically when `ATLAS_URI` is unset:

```bash
ATLAS_URI="mongodb+srv://..." uv run pytest -m integration
```

## Pull requests

- Keep changes focused, and accompany behavior changes with tests.
- Follow the surrounding code style; `ruff` enforces formatting and imports.
- Public API changes must update [`docs/reference/api.md`](docs/reference/api.md)
  and the public-API regression test.
- Add a `CHANGELOG.md` entry describing the change.

## Documentation

User-facing docs live under [`docs/`](docs/) and follow the
[Diátaxis](https://diataxis.fr) framework (tutorial / how-to / reference /
explanation). Keep examples runnable.

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
