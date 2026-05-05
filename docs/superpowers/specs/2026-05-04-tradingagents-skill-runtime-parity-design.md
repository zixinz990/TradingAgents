# TradingAgents Skill Runtime Parity Design

## Problem

The current TradingAgents skill preserves the original prompts and workflow order, but it relies heavily on the host coding agent to manually follow LangGraph-like behavior. That makes skill runs useful, but not as close as possible to the original API-driven code path. The largest gaps are state transitions, tool-call loops, structured-output enforcement, debate counters, risk counters, full-state logging, and repeatable validation.

## Goal

Improve the TradingAgents skill so CLI-agent runs mirror the original codebase's runtime semantics as closely as possible while still using the host coding agent as the model runtime. The deterministic code should own ordering, state, validation, tool gating, report assembly, and final artifact creation. The CLI agent should only perform the role reasoning and write role content.

This does not aim to guarantee identical model outputs, identical final decisions, or identical trading performance. It aims to minimize avoidable differences caused by orchestration and artifact handling.

## Non-goals

- Do not instantiate LLM provider clients from `tradingagents/llm_clients/` during a skill run.
- Do not replace or copy the existing prompt text into the skill.
- Do not modify the authoritative LangGraph workflow or agent prompts.
- Do not make API-baseline comparisons mandatory for every skill run.
- Do not let later roles rewrite earlier role outputs.

## Architecture

Add a deterministic skill-runner layer around the existing skill. The runner behaves like a finite-state adapter between the original TradingAgents workflow and the host coding agent.

The runner reads the existing skill config, `prompt_manifest.json`, `workflow.json`, and authoritative source files under `tradingagents/agents/` and `tradingagents/graph/`. It creates a run directory, seeds an AgentState-like JSON artifact, emits one role-execution packet at a time, validates the role output written by the CLI agent, applies that output back into state, and advances to the next workflow step.

The host coding agent remains the model runtime. Deterministic scripts own everything else that should not depend on model judgment: safe paths, selected analyst order, tool allowlists, debate counts, risk counts, structured markers, final report assembly, state logging, and rating extraction.

## Components

### `init_run`

Validates the JSON config, creates `results_dir/<TICKER>_<TRADE_DATE>/`, and writes the initial state artifact. The initial state should include the same high-level fields used by the original graph: company of interest, trade date, analyst reports, investment debate state, trader plan, risk debate state, final decision, and optional past context.

### `next_step`

Reads the current state and emits the next role packet. A packet contains the role id, display name, source prompt path, allowed tools, input state fields, prior reports or debate history, output path, expected markers, and transition metadata.

The role packet is an execution contract for the CLI agent. It tells the agent what context it may use and where it must write its output.

### `run_tool_request`

Supports analyst tool loops without giving the CLI agent unrestricted tool access. If an analyst needs data, the agent writes a structured `tool_request.json`. The helper validates that the requested tool is allowed for that role, executes the matching existing dataflow utility, records raw output and transcript metadata, and returns control to the same role.

Disallowed tools, malformed requests, unsafe tickers, and unsupported vendor settings fail closed with clear errors.

### `apply_step`

Validates the role output and applies it into the state artifact. It enforces the expected report path, required markers, selected analyst subset, debate history updates, risk history updates, and counter increments.

For structured-output roles, it validates the load-bearing rendered markdown contract:

- Research Manager: `**Recommendation**:`
- Trader: `**Action**:` and trailing `FINAL TRANSACTION PROPOSAL: **BUY|HOLD|SELL**`
- Portfolio Manager: `**Rating**:`, `**Executive Summary**:`, and `**Investment Thesis**:`

### `finalize_run`

Runs report assembly, writes `complete_report.md`, emits an original-like `full_states_log_<TRADE_DATE>.json`, and extracts the final rating using the existing rating parser. Finalization fails if any required fragment, marker, transition, or final decision field is missing.

### `parity_check`

Optionally compares a completed skill run against a saved API-run baseline. The comparison checks structure and orchestration fields first: role order, selected analysts, debate counts, risk counts, required markers, final action/rating fields, and state-log shape. Textual content comparison should be advisory because identical model outputs are not guaranteed.

## Data flow

1. A user supplies a validated skill config.
2. `init_run` creates the run directory and initial state.
3. `next_step` emits the first role packet.
4. The CLI agent reads the packet and either writes a final role report or writes `tool_request.json`.
5. `run_tool_request` executes approved data requests and records the transcript when needed.
6. The CLI agent writes the role report.
7. `apply_step` validates and applies the report into state.
8. Steps 3 through 7 repeat until the Portfolio Manager output is applied.
9. `finalize_run` assembles the complete report, logs full state, and extracts the final rating.

Only deterministic helpers may advance workflow state. The CLI agent may generate role content, but it does not decide which role runs next or how counters are updated.

## Error handling

The runner should fail closed and visibly when parity-sensitive assumptions are violated. It should not silently skip roles, infer missing reports, ignore malformed tool requests, or continue after invalid state transitions.

Expected failure cases include:

- invalid config fields
- unsafe ticker or result paths
- unknown role ids
- unsupported selected analysts
- out-of-order step application
- malformed state artifacts
- malformed `tool_request.json`
- tool requests outside the role allowlist
- missing report files
- missing structured-output markers
- invalid trader action values
- invalid portfolio rating values
- finalization before workflow completion

Errors should identify the artifact and field that need correction.

## Testing

Add tests around deterministic behavior rather than model quality:

- config validation remains strict and schema-aligned
- run initialization creates safe paths and expected initial state
- `next_step` follows selected analyst order and graph stage order
- analyst tool requests enforce role-specific allowlists
- `apply_step` rejects out-of-order or malformed role outputs
- debate counters advance as `2 * max_debate_rounds`
- risk counters advance as `3 * max_risk_discuss_rounds`
- structured markers are enforced for manager, trader, and portfolio roles
- finalization writes `complete_report.md` and original-like full-state logs
- final rating extraction uses the existing parser
- fixture-based end-to-end skill run completes without LLM calls
- optional parity checks compare saved API and skill artifacts without requiring exact prose matches

## Success criteria

The improved skill is successful when a user can run the workflow through CLI-agent role execution while deterministic helpers preserve the original codebase's orchestration semantics. A completed skill run should have the expected role reports, tool transcripts where applicable, state artifact, complete report, original-like full-state log, and extracted final rating.

The remaining differences from the API path should be limited to model-runtime behavior, provider/system-prompt differences, and natural LLM nondeterminism rather than preventable workflow drift.
