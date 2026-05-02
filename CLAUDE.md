# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common commands

```bash
pip install .                                   # install package + CLI (Python ≥3.10)
tradingagents                                   # interactive CLI (entry: cli.main:app)
tradingagents analyze --checkpoint              # opt-in resume after a crash
tradingagents analyze --clear-checkpoints       # wipe per-ticker checkpoint DBs first
python -m cli.main                              # same CLI without installing the script
python main.py                                  # programmatic example (edits config, runs NVDA)

pytest                                          # full suite (markers: unit, integration, smoke)
pytest -m unit                                  # unit tests only
pytest tests/test_signal_processing.py::TestSignalProcessor::test_returns_rating_from_pm_markdown
                                                # run one test
python scripts/smoke_structured_output.py openai
                                                # live structured-output check against a real provider
docker compose run --rm tradingagents           # containerised CLI
docker compose --profile ollama run --rm tradingagents-ollama
                                                # CLI + local Ollama sidecar
```

`tests/conftest.py` autouses placeholder API keys and lazy-imports LLM SDKs, so the suite runs without credentials. There is no linter/formatter wired in.

## Architecture

The pipeline is a single LangGraph `StateGraph` over a typed `AgentState` (`tradingagents/agents/utils/agent_states.py`). Roles, in order: **Analyst Team** (market → social → news → fundamentals, each with its own ToolNode and msg-clear node) → **Researchers** (Bull ↔ Bear debate, configurable rounds) → **Research Manager** → **Trader** → **Risk Debate** (Aggressive → Conservative → Neutral, round-robin) → **Portfolio Manager** → END. Edges and round counts are wired in `tradingagents/graph/setup.py` and `conditional_logic.py`; round caps come from `max_debate_rounds` / `max_risk_discuss_rounds` in config.

`TradingAgentsGraph` (`tradingagents/graph/trading_graph.py`) is the public entry point. `__init__` builds the LLM clients via the factory, instantiates ToolNodes (one per analyst, with the abstract tools re-exported from `agent_utils`), and compiles the graph. `propagate(ticker, date)` does three things in order: (1) resolves any same-ticker pending memory-log entries by fetching realized/alpha returns and writing reflections in one batch; (2) recompiles with a `SqliteSaver` checkpointer if `checkpoint_enabled`; (3) streams the graph, persists the final state to disk and to the memory log. The `process_signal()` step that returns the 5-tier rating is **not** an extra LLM call — `signal_processing.SignalProcessor` is a thin adapter over `agents/utils/rating.parse_rating`, which extracts the rating from the Portfolio Manager's rendered markdown.

### Three structured-output agents

Research Manager, Trader, and Portfolio Manager are the only agents that produce structured output. They share the pattern in `agents/utils/structured.py`:

1. `bind_structured(llm, Schema)` returns `llm.with_structured_output(Schema)` or logs a warning and returns `None` (older Ollama models, `deepseek-reasoner`).
2. `invoke_structured_or_freetext()` calls the structured LLM, renders the typed Pydantic instance back to markdown via the matching `render_*` helper in `agents/schemas.py`, and falls back to plain `llm.invoke` if the structured call throws.

The rendered markdown shape is **load-bearing**: the memory log, CLI display, saved reports, and `parse_rating` all rely on the exact `**Rating**:` / `**Action**:` / `**Recommendation**:` headers and the trailing `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**` line in the trader output. Don't change those without updating every reader.

Rating scales: 5-tier (`Buy / Overweight / Hold / Underweight / Sell`) for Research Manager and Portfolio Manager — defined once in `agents/utils/rating.py` and reused by signal processor + memory log. 3-tier (`Buy / Hold / Sell`) for the Trader.

### LLM client factory

`tradingagents/llm_clients/factory.py:create_llm_client(provider, model, …)` is the single seam for picking a provider. Lazy imports keep test collection cheap.

- The OpenAI-compatible cluster (`openai, xai, deepseek, qwen, glm, ollama, openrouter`) shares `OpenAIClient` and uses `_PROVIDER_CONFIG` for default base URL + API key env var. Native OpenAI sets `use_responses_api=True`. Structured output forces `method="function_calling"` to suppress noisy `PydanticSerializationUnexpectedValue` warnings from langchain-openai's parse path.
- `DeepSeekChatOpenAI` overrides `_get_request_payload` / `_create_chat_result` to round-trip `reasoning_content` (DeepSeek 400s without it on the next turn) and refuses `with_structured_output` for `deepseek-reasoner`.
- `Anthropic`, `Google`, `Azure` each get their own client. All wrap their LangChain class in `Normalized*` to flatten typed-block content arrays (Responses API / Gemini 3 / Claude extended-thinking) into plain strings.
- `default_config.DEFAULT_CONFIG["backend_url"]` is `None` so a non-OpenAI provider doesn't inherit `api.openai.com` and produce malformed URLs.
- `model_catalog.MODEL_OPTIONS` is the single source of truth for CLI model picker and provider validation.

### Data flow / vendor routing

Tools live in `tradingagents/agents/utils/{core_stock,technical_indicators,fundamental_data,news_data}_tools.py` as thin LangChain `@tool` wrappers that delegate to `dataflows/interface.route_to_vendor(method, *args)`. Routing reads `data_vendors` (category-level) and `tool_vendors` (tool-level override) from config and dispatches to either yfinance or alpha_vantage. **Only `AlphaVantageRateLimitError` triggers fallback** — other exceptions propagate so legitimate failures aren't masked. To add a new vendor, register it in `VENDOR_LIST` + `VENDOR_METHODS` and any caller can pick it via config.

`dataflows/config.py` is a module-level singleton — `TradingAgentsGraph.__init__` calls `set_config()` so tools see the same options the graph was built with. Don't bypass it.

### Persistence

Everything user-state lives under `~/.tradingagents/` (overridable per-path via `TRADINGAGENTS_CACHE_DIR`, `TRADINGAGENTS_RESULTS_DIR`, `TRADINGAGENTS_MEMORY_LOG_PATH`):

- `memory/trading_memory.md` — append-only markdown decision log. Each entry has a `[date | ticker | rating | pending|raw|alpha|holding]` tag, a `DECISION:` block, and (after resolution) a `REFLECTION:` block, separated by `<!-- ENTRY_END -->`. `agents/utils/memory.py:TradingMemoryLog` writes pending entries on every run, resolves them on the *next* same-ticker run by fetching SPY-relative returns, and injects the most recent same-ticker decisions plus cross-ticker lessons into the Portfolio Manager prompt via `state["past_context"]`. Updates use temp-file + `os.replace()` so a crash mid-write never corrupts the log. Entries for *other* tickers stay pending until that ticker runs again.
- `cache/checkpoints/<TICKER>.db` — per-ticker SQLite for LangGraph's `SqliteSaver`. Thread ID is `sha256(TICKER:DATE)[:16]` so same-ticker-same-date resumes and any other date starts fresh. Successful runs clear their own checkpoint; `--clear-checkpoints` wipes everything.
- `logs/<TICKER>/TradingAgentsStrategy_logs/full_states_log_<DATE>.json` — full final state per run.
- CLI saves human-readable markdown reports to `./reports/<TICKER>_<TIMESTAMP>/` (the `reports/` directory is a git submodule pointing to `TradingAgentsReports.git`).

### Security gotcha — ticker as a path component

`dataflows/utils.py:safe_ticker_component()` validates any string that will be joined into a filesystem path (cache dirs, checkpoint DBs, results dirs). Tickers come from CLI prompts and from LLM tool calls — both reachable from prompt-injected content — so rejecting `..` / non-alphanumeric tickers here is the only thing keeping malicious values from escaping `~/.tradingagents/`. Always route ticker → path interpolation through this function (or pre-validated `safe_ticker_component(...).upper()`).

### CLI display

`cli/main.py` uses Rich `Live` with a layout-driven update loop. `MessageBuffer` tracks per-agent statuses derived from streamed graph chunks (analyst statuses come from `update_analyst_statuses`, which reads the *accumulated* report sections, not just the current chunk — first analyst without a report is `in_progress`, the rest stay `pending`). When wiring new state into the display, follow the same pattern: drive status off the agent's *output*, not off message ordering.

### What's not used

`FinancialSituationMemory` (the per-agent BM25 memory) and `reflect_and_remember()` are gone — superseded by the persistent decision log. The `LLM_PROVIDER` env var in `docker-compose.yml` for the ollama profile is a hint for users; configuration is still passed through `DEFAULT_CONFIG` / CLI prompts, not env vars (apart from API keys and the three `TRADINGAGENTS_*` overrides).
