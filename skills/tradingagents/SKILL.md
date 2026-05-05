---
name: tradingagents
description: Run the TradingAgents multi-agent trading workflow with a coding agent as the model runtime, using JSON config instead of the interactive CLI.
---

# TradingAgents Skill

Use this skill when a user wants Claude Code, Codex, Copilot, or another coding agent to run the TradingAgents process without the interactive CLI or in-app LLM provider calls.

## Non-Negotiable Source of Truth

The existing prompts and LangGraph workflow are the soul of this project. Do not modify, summarize away, reorder, or replace them when using this skill.

- Prompt source of truth: `tradingagents/agents/analysts/market_analyst.py`, `tradingagents/agents/analysts/social_media_analyst.py`, `tradingagents/agents/analysts/news_analyst.py`, `tradingagents/agents/analysts/fundamentals_analyst.py`, `tradingagents/agents/researchers/bull_researcher.py`, `tradingagents/agents/researchers/bear_researcher.py`, `tradingagents/agents/managers/research_manager.py`, `tradingagents/agents/trader/trader.py`, `tradingagents/agents/risk_mgmt/aggressive_debator.py`, `tradingagents/agents/risk_mgmt/conservative_debator.py`, `tradingagents/agents/risk_mgmt/neutral_debator.py`, and `tradingagents/agents/managers/portfolio_manager.py`.
- Workflow source of truth: `tradingagents/graph/setup.py` and `tradingagents/graph/conditional_logic.py`.
- Structured output source of truth: `tradingagents/agents/schemas.py` and `tradingagents/agents/utils/rating.py`.

`prompt_manifest.json` and `workflow.json` are maps for coding agents. If they disagree with the files above, the existing code wins.

## Inputs

Start from a JSON config that matches `config.schema.json`. A minimal example is in `config.example.json`.

Run helper scripts from the repository root with the package importable, for example after `pip install -e .`.

Required fields:

- `ticker`: exact instrument symbol to analyze.
- `trade_date`: analysis date in `YYYY-MM-DD` format.
- `selected_analysts`: ordered subset of `market`, `social`, `news`, and `fundamentals`.
- `max_debate_rounds`: number of bull/bear debate rounds.
- `max_risk_discuss_rounds`: number of aggressive/conservative/neutral risk cycles.
- `results_dir`: safe relative directory where role reports and `complete_report.md` are written.

Validate before running:

```bash
python skills/tradingagents/scripts/validate_config.py skills/tradingagents/config.example.json
```

## Runtime Model Policy

Do not instantiate provider clients from `tradingagents/llm_clients/` for a skill run. The host coding agent is the model runtime. Use its own reasoning/subagent/tool capabilities to execute each role in the same order as the original workflow.

Market, news, and fundamentals data still need a source. Prefer user-provided files when available. If live data is required, use existing deterministic dataflow utilities or approved MCP/tools, then include the raw data references in the generated report.

## Deterministic Runtime Workflow

Use the deterministic runner scripts for skill runs. They preserve the original workflow order, state transitions, role counters, report paths, tool allowlists, final report assembly, and rating extraction while keeping the host coding agent as the model runtime.

Start a run:

```bash
python skills/tradingagents/scripts/skill_runner.py init-run path/to/config.json
```

The command prints the path to `state.json` under `results_dir/<TICKER>_<TRADE_DATE>/`.

For each role:

```bash
python skills/tradingagents/scripts/skill_runner.py next-step path/to/results/TICKER_YYYY-MM-DD
```

Read the generated `next_step.json`. It contains the role id, source prompt path, allowed tools, input state, required markers, `tool_request.json` path, and output path.

If an analyst needs live data, write `tool_request.json` using the role id, approved tool name, and JSON arguments, then run:

```bash
python skills/tradingagents/scripts/skill_runner.py run-tool-request path/to/results/TICKER_YYYY-MM-DD
```

Use the generated tool transcript as context for the same role. Do not call tools outside the runner.

After writing the role report to the packet's `output_path`, apply it:

```bash
python skills/tradingagents/scripts/skill_runner.py apply-step path/to/results/TICKER_YYYY-MM-DD --role-id ROLE_ID
```

Repeat `next-step` and `apply-step` until `next_step.json` reports completion. Then finalize:

```bash
python skills/tradingagents/scripts/skill_runner.py finalize-run path/to/results/TICKER_YYYY-MM-DD
```

Finalization writes `complete_report.md`, `TradingAgentsStrategy_logs/full_states_log_<TRADE_DATE>.json`, updates `state.json`, and returns the parsed final rating.

## Role Execution Rules

For each generated `next_step.json` packet:

1. Read the role entry from the packet.
2. Read the role's `source_path` file from the repository root.
3. Preserve the current prompt wording and role intent from that source file.
4. Use only the packet's `input_state`, approved tool transcripts, and allowed tools.
5. Write the role output exactly to the packet's `output_path`.
6. Run `apply-step` before moving to the next role.

Only the runner may advance `state.json`. Do not let a later role rewrite earlier reports. Later roles may quote or critique earlier outputs, matching the original multi-agent handoff.

## Output Contract

Write reports under `results_dir/<TICKER>_<TRADE_DATE>/`, where `TRADE_DATE` keeps its `YYYY-MM-DD` format. Selected analysts write only their selected analyst report files; the debate, trader, risk, and portfolio files are required for a complete run.

Potential report paths:

- `1_analysts/market.md`
- `1_analysts/sentiment.md`
- `1_analysts/news.md`
- `1_analysts/fundamentals.md`
- `2_research/bull.md`
- `2_research/bear.md`
- `2_research/manager.md`
- `3_trading/trader.md`
- `4_risk/aggressive.md`
- `4_risk/conservative.md`
- `4_risk/neutral.md`
- `5_portfolio/decision.md`
- `complete_report.md`

Preserve load-bearing output markers:

- Research Manager: `**Recommendation**:`
- Trader: `**Action**:` and trailing `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`
- Portfolio Manager: `**Rating**:`, `**Executive Summary**:`, and `**Investment Thesis**:`

Assemble the final report after all role files exist:

```bash
python skills/tradingagents/scripts/assemble_report.py path/to/results/TICKER_YYYY-MM-DD
```

When a config is available, pass it so the assembler can enforce the selected analyst subset and ensure the report directory stays under `results_dir`:

```bash
python skills/tradingagents/scripts/assemble_report.py path/to/results/TICKER_YYYY-MM-DD --config path/to/config.json
```

## Safety

Use safe ticker path components only. Keep `results_dir` as a safe relative path. Do not write reports outside the configured results directory. Do not commit API keys, `.env`, generated caches, or live credentials.
