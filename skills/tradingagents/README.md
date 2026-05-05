# TradingAgents Skill

This directory contains a project-local skill that lets Claude Code, Codex, Copilot, or another coding agent run the TradingAgents workflow with the coding agent as the model runtime.

The existing prompts and workflow remain the source of truth. Do not modify, summarize away, reorder, or replace the prompts under `tradingagents/agents/` or the workflow under `tradingagents/graph/`.

## Files

| File | Purpose |
| --- | --- |
| `SKILL.md` | Agent-facing skill instructions. |
| `config.schema.json` | JSON config contract that replaces interactive CLI choices. |
| `config.example.json` | Minimal example config. |
| `prompt_manifest.json` | Role-to-source mapping. It points to existing prompt files instead of copying prompt text. |
| `workflow.json` | Machine-readable mirror of the current multi-agent workflow. |
| `scripts/validate_config.py` | Deterministic config validation helper. |
| `scripts/assemble_report.py` | Deterministic final report assembly helper. |

## Install for Claude Code

Expose this skill through Claude Code's project-local skills directory:

```bash
git switch skill-version
mkdir -p .claude/skills
ln -s ../../skills/tradingagents .claude/skills/tradingagents
```

Restart Claude Code or open a new Claude Code session from the repository root so it discovers `.claude/skills/tradingagents/SKILL.md`.

## Prerequisites

Run the helper scripts from the repository root with the package importable:

```bash
pip install -e .
```

## Prepare a run config

Copy the example and edit it for your target instrument:

```bash
cp skills/tradingagents/config.example.json my-trading-run.json
```

Required fields:

- `ticker`: exact ticker or index symbol, such as `NVDA`, `BRK.B`, or `^GSPC`.
- `trade_date`: `YYYY-MM-DD`.
- `selected_analysts`: ordered subset of `market`, `social`, `news`, and `fundamentals`.
- `max_debate_rounds`: bull/bear debate rounds.
- `max_risk_discuss_rounds`: aggressive/conservative/neutral risk cycles.
- `results_dir`: safe relative output directory.

Validate the config before asking an agent to run it:

```bash
python skills/tradingagents/scripts/validate_config.py my-trading-run.json
```

## Run with the deterministic skill runner

Initialize the run:

```bash
python skills/tradingagents/scripts/skill_runner.py init-run my-trading-run.json
```

The command prints:

```text
reports/skill_runs/NVDA_2026-05-04/state.json
```

Generate the next role packet:

```bash
python skills/tradingagents/scripts/skill_runner.py next-step reports/skill_runs/NVDA_2026-05-04
```

Read `next_step.json`, then use the host coding agent as the model runtime for that role. The agent should read the packet's `source_path`, use only the packet's `input_state`, write the role report to `output_path`, and preserve any required markers.

When an analyst needs live data, write `tool_request.json` in the run directory:

```json
{
  "role_id": "market_analyst",
  "tool": "get_stock_data",
  "arguments": {
    "symbol": "NVDA",
    "start_date": "2026-04-01",
    "end_date": "2026-05-04"
  }
}
```

Run the approved tool request through the deterministic gate:

```bash
python skills/tradingagents/scripts/skill_runner.py run-tool-request reports/skill_runs/NVDA_2026-05-04
```

After the role report exists, apply it:

```bash
python skills/tradingagents/scripts/skill_runner.py apply-step reports/skill_runs/NVDA_2026-05-04 --role-id market_analyst
```

Repeat `next-step`, role execution, and `apply-step` until `next_step.json` reports completion.

Finalize the run:

```bash
python skills/tradingagents/scripts/skill_runner.py finalize-run reports/skill_runs/NVDA_2026-05-04
```

Finalization creates `complete_report.md`, writes `TradingAgentsStrategy_logs/full_states_log_<TRADE_DATE>.json`, updates `state.json`, and returns the parsed final rating.

## Output layout

Reports are written under:

```text
<results_dir>/<TICKER>_<TRADE_DATE>/
```

For example:

```text
reports/skill_runs/NVDA_2026-05-04/
```

Expected role report paths:

```text
1_analysts/market.md
1_analysts/sentiment.md
1_analysts/news.md
1_analysts/fundamentals.md
2_research/bull.md
2_research/bear.md
2_research/manager.md
3_trading/trader.md
4_risk/aggressive.md
4_risk/conservative.md
4_risk/neutral.md
5_portfolio/decision.md
complete_report.md
```

If you select only some analysts, only those selected analyst report files are required. The downstream research, trader, risk, and portfolio files are always required for a complete run.

## Important constraints

- Do not instantiate provider clients from `tradingagents/llm_clients/`; the host coding agent is the model runtime.
- Do not change the source prompts in `tradingagents/agents/`.
- Do not change the source workflow in `tradingagents/graph/`.
- Preserve load-bearing output markers such as `**Recommendation**:`, `**Action**:`, `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`, and `**Rating**:`.
- Do not commit API keys, `.env`, generated caches, or live credentials.
