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

## Workflow

Follow the current workflow exactly:

1. Analyst team runs in `selected_analysts` order. Each analyst may fetch its allowed data, then writes its report.
2. Bull researcher and bear researcher debate for `max_debate_rounds` cycles.
3. Research Manager evaluates the debate and writes the investment plan.
4. Trader converts the investment plan into a transaction proposal.
5. Aggressive, Conservative, and Neutral risk analysts debate for `max_risk_discuss_rounds` cycles.
6. Portfolio Manager writes the final decision.

Use `workflow.json` for machine-readable stage metadata, but treat `tradingagents/graph/setup.py` and `tradingagents/graph/conditional_logic.py` as authoritative.

## Role Execution Rules

For each role:

1. Read the role entry from `prompt_manifest.json`.
2. Read the role's `source_path` file.
3. Preserve the current prompt wording and role intent from that source file.
4. Provide only the role's allowed context and prior reports.
5. Write the role output to the configured report path.

Do not let a later role rewrite earlier reports. Later roles may quote or critique earlier outputs, matching the original multi-agent handoff.

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
