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

## Prompt Claude Code

Use a prompt like this:

```text
Use the tradingagents skill with config at my-trading-run.json.
Follow SKILL.md exactly. Use the existing prompt files under tradingagents/agents/ and workflow files under tradingagents/graph/ as source of truth.
Do not instantiate TradingAgents LLM provider clients.
Generate all role reports, then run the report assembler.
```

Claude Code should read:

1. `SKILL.md`
2. `prompt_manifest.json`
3. `workflow.json`
4. The source prompt/workflow files referenced by those manifests
5. Your JSON config

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

## Assemble the final report

After the role reports exist, run:

```bash
python skills/tradingagents/scripts/assemble_report.py reports/skill_runs/NVDA_2026-05-04 --config my-trading-run.json
```

The assembler fails if required fragments are missing, so a successful run means `complete_report.md` was created from the expected role outputs.

## Important constraints

- Do not instantiate provider clients from `tradingagents/llm_clients/`; the host coding agent is the model runtime.
- Do not change the source prompts in `tradingagents/agents/`.
- Do not change the source workflow in `tradingagents/graph/`.
- Preserve load-bearing output markers such as `**Recommendation**:`, `**Action**:`, `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`, and `**Rating**:`.
- Do not commit API keys, `.env`, generated caches, or live credentials.
