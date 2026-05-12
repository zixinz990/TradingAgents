# TradingAgents Skill README

This directory packages a deterministic, coding-agent-driven way to run the TradingAgents workflow. It is meant for Claude Code, Copilot CLI, Codex, or another coding agent that can read the skill files, follow JSON state packets, write role reports, and call approved local helper scripts.

The key difference from the interactive TradingAgents CLI is the model runtime: **the host coding agent performs each role**. Do not instantiate provider clients from `tradingagents/llm_clients/`, do not call the app LLM factory, and do not replace the existing role prompts with new prompts. The existing `tradingagents/agents/` prompts and `tradingagents/graph/` workflow remain the source of truth.

## Automated Agent Run

The easiest way to use this skill is the run to completion mode: ask a coding agent to run the whole packet loop for you.

```text
Use the tradingagents skill with this config and run it to completion: @JSON_FILE_NAME . Each subagent must use GPT-5.5 with extra high effort. Use the Python env in the current folder with uv.
```

In this mode, the agent should validate the config, initialize the run, process every `next_step.json` packet, write each role report, apply each step, run approved `tool_request.json` requests when data is needed, call `finalize-run`, and return the final rating plus report paths.

Do not stop after emitting or reading `next_step.json`. The intended automated path stops only after `finalize-run` succeeds or a real blocker needs user input, such as missing credentials, unavailable data, invalid config, or a runner validation error.

The detailed command sequence below is still useful for debugging or manual recovery, but it should not be necessary for a normal one-prompt run.

## What is included

| File | Purpose |
| --- | --- |
| `SKILL.md` | Agent-facing usage contract and non-negotiable rules. |
| `config.example.json` | Minimal runnable config shape to copy for a run. |
| `config.schema.json` | JSON schema for config fields and basic safety constraints. |
| `prompt_manifest.json` | Role IDs, source prompt paths, report paths, and allowed tools. |
| `workflow.json` | Machine-readable mirror of the TradingAgents graph order. |
| `scripts/validate_config.py` | Validates run config before initialization. |
| `scripts/skill_runner.py` | Main deterministic runner for `init-run`, `next-step`, `run-tool-request`, `apply-step`, `finalize-run`, and `parity-check`. |
| `scripts/runtime.py` | Runtime state transition implementation used by `skill_runner.py`. |
| `scripts/assemble_report.py` | Assembles role fragments into `complete_report.md`. |

## Install or expose the skill

For Claude Code, copy or symlink this directory so the skill loader can find it, for example:

```bash
mkdir -p .claude/skills
ln -s ../../skills/tradingagents .claude/skills/tradingagents
```

You can also install it user-wide as `~/.claude/skills/tradingagents` if that fits your workflow better. For other coding agents, register the `skills/tradingagents` directory using that agent's skill/plugin mechanism.

Run all helper commands from the repository root. Install the package in editable mode first so `tradingagents` is importable:

```bash
pip install -e .
```

If you plan to fetch live market data, configure the normal TradingAgents data dependencies and credentials outside this skill. Never commit `.env`, API keys, generated caches, or credential-bearing output.

## Source of truth rules

The manifests in this directory are maps for coding agents, not replacements for the app code.

- Role prompts live under `tradingagents/agents/`, including analysts, researchers, managers, trader, and risk debaters.
- Workflow wiring lives under `tradingagents/graph/`, especially `setup.py` and `conditional_logic.py`.
- Structured output markers come from `tradingagents/agents/schemas.py` and rating parsing in `tradingagents/agents/utils/rating.py`.

If `prompt_manifest.json` or `workflow.json` disagrees with those source files, the source files win. Preserve the original role intent and output contracts when writing each role report.

## Create a config

Start by copying the example:

```bash
cp skills/tradingagents/config.example.json /tmp/tradingagents-skill-config.json
```

Required fields:

| Field | Meaning |
| --- | --- |
| `ticker` | Instrument symbol to analyze. Must be safe as a filesystem path component. |
| `trade_date` | Analysis date in `YYYY-MM-DD` format. |
| `selected_analysts` | Ordered subset of `market`, `social`, `news`, and `fundamentals`. |
| `max_debate_rounds` | Number of bull/bear research debate rounds. |
| `max_risk_discuss_rounds` | Number of aggressive/conservative/neutral risk cycles. |
| `results_dir` | Safe relative base directory for generated run artifacts. |

Optional fields:

| Field | Meaning |
| --- | --- |
| `output_language` | User-facing report language. |
| `data_vendors` | Category-level vendor preferences such as `yfinance` or `alpha_vantage,yfinance`. |
| `tool_vendors` | Tool-level vendor overrides keyed by supported dataflow method. |
| `data_inputs` | Optional file references for user-provided data. |

Validate before initializing a run:

```bash
python skills/tradingagents/scripts/validate_config.py /tmp/tradingagents-skill-config.json
```

A valid config prints `Config valid`. Validation errors are printed as bullets.

## Run the deterministic workflow

Initialize a run:

```bash
python skills/tradingagents/scripts/skill_runner.py init-run /tmp/tradingagents-skill-config.json
```

The command prints a path like:

```text
reports/skill_runs/NVDA_2026-05-04/state.json
```

The run directory is the parent directory of `state.json`, for example:

```bash
REPORT_DIR=reports/skill_runs/NVDA_2026-05-04
```

Ask the runner for the next role packet:

```bash
python skills/tradingagents/scripts/skill_runner.py next-step "$REPORT_DIR"
```

This writes and prints `next_step.json`. Read that file before doing any role work. A role packet contains:

| Packet field | How to use it |
| --- | --- |
| `status` | `role_ready` means write the next role report; `complete` means all role reports have been applied. |
| `role_id` / `display_name` | Current role to perform. |
| `source_path` | Existing role source file to read from the repository root. Preserve this prompt's role intent. |
| `report_path` / `output_path` | Where the completed markdown report must be written. |
| `allowed_tools` | Only these tools may be requested for this role. |
| `required_markers` | Markdown markers that must appear before `apply-step` accepts the report. |
| `input_state` | The only workflow state the role should use, plus approved tool transcripts. |
| `tool_request_path` | Where to write `tool_request.json` if the role needs an approved data tool. |

For each `role_ready` packet:

1. Read the role source file listed in `source_path`.
2. Use the packet's `input_state` and any approved tool transcripts as context.
3. If live data is needed, write a valid `tool_request.json` for one of the packet's `allowed_tools`.
4. Run the tool request through the runner, then use the transcript as role context.
5. Write the final markdown report exactly to `output_path`.
6. Apply the step before asking for the next packet.

Apply a completed role report:

```bash
python skills/tradingagents/scripts/skill_runner.py apply-step "$REPORT_DIR" --role-id ROLE_ID
```

Repeat `next-step` and `apply-step` until `next_step.json` reports:

```json
{
  "status": "complete",
  "message": "all role steps have been applied"
}
```

Finalize the run:

```bash
python skills/tradingagents/scripts/skill_runner.py finalize-run "$REPORT_DIR"
```

Finalization writes:

- `complete_report.md`
- `TradingAgentsStrategy_logs/full_states_log_<TRADE_DATE>.json`
- updated `state.json` with `status`, `complete_report`, `state_log`, and parsed `rating`

It prints JSON containing the complete report path, state log path, and parsed final rating.

## Tool requests

Only analyst roles have allowed tools. The allowed list is declared in `prompt_manifest.json` and repeated in each `next_step.json` packet.

Example `tool_request.json` for a market analyst packet:

```json
{
  "role_id": "market_analyst",
  "tool": "get_stock_data",
  "arguments": {
    "symbol": "NVDA",
    "start_date": "2026-04-04",
    "end_date": "2026-05-04"
  }
}
```

Run it through the runner:

```bash
python skills/tradingagents/scripts/skill_runner.py run-tool-request "$REPORT_DIR"
```

The runner validates that the request matches the current role, checks that the tool is allowed, applies safe ticker validation to `ticker` or `symbol` arguments, runs the existing TradingAgents dataflow tool, and writes a transcript under `tool_transcripts/`.

Do not call data tools directly outside `skill_runner.py` during a skill run. The transcript path is appended to `state.json`, and the current role can use the transcript content when writing its report.

## Workflow order

The runner builds the step order from config:

1. Selected analysts in the order listed by `selected_analysts`.
2. `bull_researcher`, then `bear_researcher`, repeated `max_debate_rounds` times.
3. `research_manager`.
4. `trader`.
5. `risk_aggressive`, `risk_conservative`, then `risk_neutral`, repeated `max_risk_discuss_rounds` times.
6. `portfolio_manager`.

The runner owns `state.json` advancement. Do not manually edit `step_index`, `completed_steps`, debate counters, or prior role outputs unless you are intentionally repairing a failed local run.

## Output markers that must not change

Some downstream parsing depends on exact markdown markers:

| Role | Required marker |
| --- | --- |
| Research Manager | `**Recommendation**:` |
| Trader | `**Action**:` and a final line matching `FINAL TRANSACTION PROPOSAL: **BUY**`, `**HOLD**`, or `**SELL**` |
| Portfolio Manager | `**Rating**:`, `**Executive Summary**:`, and `**Investment Thesis**:` |

If a marker is missing or malformed, `apply-step` or `assemble_report.py` fails. Keep these markers even when `output_language` requests another language.

## Assembling reports manually

Normally `finalize-run` assembles the final report. If you only need to reassemble existing fragments, run:

```bash
python skills/tradingagents/scripts/assemble_report.py "$REPORT_DIR" --config /tmp/tradingagents-skill-config.json
```

The config lets `assemble_report.py` enforce the selected analyst subset and confirm the report directory stays inside `results_dir`.

## Parity checks

If you need to compare a skill-generated state log against an API-generated state log:

```bash
python skills/tradingagents/scripts/skill_runner.py parity-check path/to/api_state.json path/to/skill_state.json
```

The command reports whether comparable top-level state fields and debate histories match.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| `ModuleNotFoundError: tradingagents` | Run from the repository root after `pip install -e .`, or set `PYTHONPATH` to the repo root. The package must be importable. |
| `state.json already exists for this run` | A run for the same `ticker`, `trade_date`, and `results_dir` already exists. Use a different config or intentionally remove the old run directory. |
| `cannot finalize before all role steps are applied` | Keep running `next-step`, writing role reports, and `apply-step` until the packet status is `complete`. |
| `cannot apply role X while current role is Y` | Use the `role_id` from the current `next_step.json`; do not skip or reorder roles. |
| `tool ... is not allowed for role ...` | Check the packet's `allowed_tools`; only those tools can be requested. |
| `missing required marker` | Add the exact required markdown marker to the role report and rerun `apply-step`. |
| `missing valid final transaction proposal` | The trader report must end with `FINAL TRANSACTION PROPOSAL: **BUY**`, `**HOLD**`, or `**SELL**`. |
| `report_dir must be inside results_dir` | Keep `results_dir` relative and write reports only under the configured run directory. |

## Safety checklist

- Keep `results_dir` relative; never use absolute paths or `..`.
- Let `safe_ticker_component()` validation protect ticker-derived paths.
- Do not instantiate LLM provider clients for a skill run; the coding agent is the model runtime.
- Do not modify the original role prompts or graph workflow while running the skill.
- Do not commit credentials, `.env`, generated caches, or accidental live-data artifacts.
- Treat generated reports as research artifacts, not guaranteed trading advice.
