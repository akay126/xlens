# Contributing

## Setup

```
git clone https://github.com/akay126/xlens
cd xlens
uv sync --extra dev
uv run playwright install chromium   # for the browser tests
```

Python 3.10 or later. Lint with `uv run ruff check .`.

## Tests

```
uv run pytest                            # unit tests
uv run pytest e2e/ --browser chromium    # browser tests
```

- Tests use workbooks generated in code by `tests/fixtures/build_models.py` with invented names. Never add a real client or employer model, or data taken from one, to tests, fixtures, examples or docs.
- `examples/sample_model.xlsx` is produced by `build_sample`, then opened and recalculated once in Excel or LibreOffice so it carries cached values. Its metadata (author, company, paths) must be scrubbed. Tests check this. If you regenerate it, repeat both steps.
- Analysis modules must never print to stdout. Stdout carries the MCP protocol, and only `cli.py` prints.

## Skill and plugins

`skills/xlens/SKILL.md` is the single source for the skill. After editing it, run:

```
python scripts/sync_plugins.py
```

This copies it into both plugins. `tests/test_plugins.py` fails when the copies are stale.

## Commits and pull requests

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `style`, `perf`, with an optional scope, for example `fix(trace): ...`. Write the subject in the imperative, 72 characters or fewer. Keep each commit to one logical change, and explain why in the body when it is not obvious. Run both test suites before opening a pull request.
