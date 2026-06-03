# NCS Production Insights

Fast, trustworthy view of Norwegian Continental Shelf (NCS) field production with
**credible, backtested decline forecasts** — built entirely from SODIR open data, spec-first.

**Specs are the single source of truth; code is generated from them.** The binding project
constitution lives in [`specs/constitution/`](specs/constitution/); the git/GitHub workflow is in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Layout
- `specs/` — phases (`00N-<name>/`) running the loop spec -> plan -> tasks -> implement -> validate.
- `src/ncs/` — the importable Python package (src-layout).
- `tests/acceptance/` — black-box tests from EARS (test-author); `tests/unit/` — white-box tests (developer).

## Develop
Python 3.12+, managed with [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync                 # resolve + install (writes uv.lock)
uv run pytest           # run the suite with the coverage gate
```
