# Repository Guidelines

## Project Structure & Module Organization

Core package code lives in `tradingagents/`. The LangGraph pipeline is under `tradingagents/graph/`, roles under `tradingagents/agents/`, market data adapters under `tradingagents/dataflows/`, and provider wrappers under `tradingagents/llm_clients/`. The interactive CLI is in `cli/`, with packaged static text in `cli/static/`. Tests live in `tests/`; ad hoc smoke checks live in `scripts/`. `assets/` contains README and CLI images. `reports/` is generated output and a submodule, so update it only when artifacts are intentional.

## Build, Test, and Development Commands

```bash
pip install .                         # install package and tradingagents CLI
python -m cli.main                    # run CLI directly from source
tradingagents                         # run installed interactive CLI
python main.py                        # run the programmatic NVDA example
pytest                                # run the full test suite
pytest -m unit                        # run fast unit tests only
python scripts/smoke_structured_output.py openai  # live provider smoke check
docker compose run --rm tradingagents # run the CLI in Docker
```

Copy `.env.example` to `.env` for local credentials. Use `.env.enterprise.example` for enterprise provider settings.

## Coding Style & Naming Conventions

Use Python 3.10+ and PEP 8-style formatting: four-space indentation, snake_case functions and modules, PascalCase classes, and UPPER_SNAKE_CASE constants. Keep provider selection centralized in `tradingagents/llm_clients/model_catalog.py` and `factory.py`. Preserve structured-output markdown headers such as `**Rating**:` and trader final proposal lines because parsers depend on them. There is no configured formatter or linter; match surrounding code.

## Testing Guidelines

Pytest is configured in `pyproject.toml` with markers `unit`, `integration`, and `smoke`. Name tests `test_*.py` and place shared fixtures in `tests/conftest.py`. Placeholder API keys and lazy SDK imports let normal tests run without real credentials. Mark network or live-provider checks as `integration` or keep them in `scripts/`.

## Commit & Pull Request Guidelines

Recent commits use short imperative subjects, often Conventional Commit prefixes such as `feat:` and `chore:`. Prefer messages like `feat: add azure model validation` or `chore: update reports submodule`. Pull requests should describe behavior changes, list tests run, note API key or config changes, and include screenshots only for CLI or documentation image updates. Link related issues when available.

## Security & Configuration Tips

Never commit `.env` or real API keys. Any ticker used in filesystem paths must pass through `safe_ticker_component()` to prevent path traversal. Generated caches and decision logs belong under `~/.tradingagents/` unless explicitly overridden by `TRADINGAGENTS_CACHE_DIR`, `TRADINGAGENTS_RESULTS_DIR`, or `TRADINGAGENTS_MEMORY_LOG_PATH`.
